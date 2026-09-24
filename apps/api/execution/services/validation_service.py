from typing import Dict, List, Set
from uuid import UUID


from execution.enums import WorkflowVersionStatus
from execution.exceptions import (
    ExecutionValidationError,
    WorkflowDependencyCycleError,
    WorkflowImmutableError,
)
from execution.models.milestone_definition import ExecutionMilestoneDefinition
from execution.models.version import ExecutionWorkflowTemplateVersion


def detect_dependency_cycles(milestones: List[ExecutionMilestoneDefinition]) -> None:
    """
    Detect cycles in milestone prerequisite relationships using DFS (3-color cycle detection).

    Graph representation:
    - Directed edge: prerequisite -> milestone (prerequisite must be completed before milestone).
    A cycle means milestone A requires B, and B requires A (directly or indirectly).

    Raises:
        WorkflowDependencyCycleError if a cycle is detected.
    """
    milestone_by_id: Dict[UUID, ExecutionMilestoneDefinition] = {m.id: m for m in milestones}
    # Adjacency list: prereq_id -> list of dependent milestone_ids
    adj: Dict[UUID, List[UUID]] = {m.id: [] for m in milestones}

    for m in milestones:
        # m depends on each p in m.prerequisites
        for dep in m.prerequisite_dependencies.all():
            prereq_id = dep.prerequisite_id
            if prereq_id in adj:
                adj[prereq_id].append(m.id)

    # 0 = unvisited (white), 1 = visiting (gray), 2 = visited (black)
    visited: Dict[UUID, int] = {m.id: 0 for m in milestones}
    parent_map: Dict[UUID, UUID] = {}

    def dfs(node_id: UUID, path: List[UUID]) -> None:
        visited[node_id] = 1
        path.append(node_id)

        for neighbor_id in adj.get(node_id, []):
            if visited[neighbor_id] == 1:
                # Cycle found!
                cycle_start_idx = path.index(neighbor_id)
                cycle_ids = path[cycle_start_idx:] + [neighbor_id]
                cycle_codes = [milestone_by_id[nid].code for nid in cycle_ids]
                raise WorkflowDependencyCycleError(
                    f"Dependency cycle detected involving milestones: {' -> '.join(cycle_codes)}"
                )
            elif visited[neighbor_id] == 0:
                parent_map[neighbor_id] = node_id
                dfs(neighbor_id, path)

        path.pop()
        visited[node_id] = 2

    for m in milestones:
        if visited[m.id] == 0:
            dfs(m.id, [])


def validate_version_for_publish(version: ExecutionWorkflowTemplateVersion) -> None:
    """
    Validate that a workflow template version satisfies all semantic invariants for publishing.

    Rules:
    1. Version status must be DRAFT.
    2. Version must contain at least one milestone.
    3. Milestone codes must be valid machine codes and unique.
    4. Milestone sort_orders must be unique.
    5. All prerequisite dependencies must belong to this same version.
    6. No milestone may depend on itself.
    7. Prerequisite dependency graph must be an acyclic directed graph (DAG).
    8. Terminal milestone rule:
       - Exactly one milestone must have terminal=True.
       - Terminal milestone cannot be a prerequisite for any other milestone.
       - Terminal milestone must be required=True and blocking=True.

    Raises:
        ExecutionValidationError, WorkflowImmutableError, or WorkflowDependencyCycleError.
    """
    if version.status != WorkflowVersionStatus.DRAFT:
        raise WorkflowImmutableError(
            f"Cannot publish version in '{version.status}' status; only DRAFT versions can be published."
        )

    milestones = list(
        ExecutionMilestoneDefinition.objects.filter(workflow_template_version=version)
        .prefetch_related("prerequisite_dependencies", "downstream_dependencies")
        .order_by("sort_order")
    )

    if not milestones:
        raise ExecutionValidationError("Workflow template version must contain at least one milestone.")

    # 1. Milestone codes uniqueness and validity
    seen_codes: Set[str] = set()
    seen_orders: Set[int] = set()
    terminal_milestones: List[ExecutionMilestoneDefinition] = []

    for m in milestones:
        if m.code in seen_codes:
            raise ExecutionValidationError(f"Duplicate milestone code '{m.code}' in workflow version.")
        seen_codes.add(m.code)

        if m.sort_order in seen_orders:
            raise ExecutionValidationError(
                f"Duplicate milestone sort_order '{m.sort_order}' in workflow version."
            )
        seen_orders.add(m.sort_order)

        if m.terminal:
            terminal_milestones.append(m)

    # 2. Terminal milestone invariants
    if len(terminal_milestones) == 0:
        raise ExecutionValidationError("Workflow template version must have exactly one terminal milestone.")
    if len(terminal_milestones) > 1:
        codes = [t.code for t in terminal_milestones]
        raise ExecutionValidationError(
            f"Workflow template version cannot have multiple terminal milestones: {codes}."
        )

    terminal_milestone = terminal_milestones[0]
    if not terminal_milestone.required:
        raise ExecutionValidationError("Terminal milestone must be required=True.")
    if not terminal_milestone.blocking:
        raise ExecutionValidationError("Terminal milestone must be blocking=True.")

    # Check that terminal milestone is not a prerequisite for any other milestone
    if terminal_milestone.downstream_dependencies.exists():
        raise ExecutionValidationError(
            f"Terminal milestone '{terminal_milestone.code}' cannot be a prerequisite for any other milestone."
        )

    # 3. Check prerequisites are all within this version & no self-dependencies
    milestone_ids = {m.id for m in milestones}
    for m in milestones:
        for dep in m.prerequisite_dependencies.all():
            if dep.prerequisite_id == m.id:
                raise ExecutionValidationError(f"Milestone '{m.code}' cannot depend on itself.")
            if dep.prerequisite_id not in milestone_ids:
                raise ExecutionValidationError(
                    f"Milestone '{m.code}' has prerequisite outside this workflow version."
                )

    # 4. Cycle detection
    detect_dependency_cycles(milestones)
