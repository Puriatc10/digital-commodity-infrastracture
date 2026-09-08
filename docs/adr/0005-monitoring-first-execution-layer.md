# ADR 0005: Monitoring-first Execution Layer

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Execution Monitor follows the Qualified Deal stage and provides visibility, status tracking, and orchestration only. Do not implement real settlement, payment processing, escrow, financing, insurance, or logistics execution.

Monitor commercial terms, payment statuses (Expected, Reported, Confirmed), logistics, quality/inspection, documents, and issues. Use ExecutionWorkflowTemplate, ExecutionMilestoneDefinition, and Deal-instance ExecutionMilestone data instead of a completely hard-coded workflow. A demo workflow-builder UI is not required.

The initial Bitumen workflow in specification §33 and T1002 is:

```text
Awarded → Contract Signed → Payment Reported → Loading Scheduled
→ Loaded → Inspection Completed → In Transit → Delivered → Accepted → Closed
```

## Consequences and open detail

Document associations, timeline/panels, logistics tracking, inspection tracking, and issue management belong to monitoring. These features do not authorize money movement or physical execution.

Milestone labels in the Hero example and issue classifications differ within the sources; see [source review](../architecture/source-review.md). Exact transition and confirmation permissions remain to be defined; no Execution feature is implemented here.

Sources: [Product Specification](../product/product-spec.md) §§3.4, 32–36, 49, 57; [Delivery Roadmap](../delivery/roadmap.md) T1001–T1009.
