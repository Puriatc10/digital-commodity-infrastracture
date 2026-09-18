from typing import Protocol, Sequence, runtime_checkable

from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot


@runtime_checkable
class CandidateProvider(Protocol):
    """
    Narrow shared protocol for candidate discovery sources.

    Each provider searches an authorized domain source and produces deterministic,
    immutable candidate snapshots without performing scoring or ranking.
    """

    def find_candidates(
        self,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Discover and snapshot matching-relevant candidate evidence for a target context.

        Args:
            context: Discovery parameters including target RFQ, owner, commodity, and audience.
            actor_scope: Contextual caller authorization and organization scope.

        Returns:
            A sequence of immutable, normalized CandidateSnapshot value objects.
        """
        ...
