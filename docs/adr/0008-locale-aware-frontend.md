# ADR 0008: Locale-aware Frontend

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Use Next.js + TypeScript, Tailwind CSS, and shadcn/ui. The frontend is locale-aware from day one, with Persian and English as architectural targets:

- /fa: Persian, RTL; active in demo.
- /en: English, LTR; future support, inactive in demo.

Do not hard-code user-facing text in reusable components. The demo is Persian only; locale readiness does not authorize an English demo UI. Use the generated OpenAPI contract/client infrastructure for backend interaction.

## Consequences and open detail

The UX is a desktop-first, responsive enterprise operations product centered on workspaces, dense tables, filters, comparison, side panels, timelines, and Operator efficiency. T1303–T1304 require a Persian localization pass and RTL UX review.

Localization libraries, translation management, and date/number/currency formatting conventions are not selected here. No frontend scaffolding or UI feature is implemented in this foundation.

Sources: [Product Specification](../product/product-spec.md) §§45–46, 52; [Delivery Roadmap](../delivery/roadmap.md) T0103, T0105, T1303–T1304.
