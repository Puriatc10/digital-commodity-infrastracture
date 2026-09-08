# Domain Glossary

Derived from the authoritative [Product Specification](../product/product-spec.md) and [Delivery Roadmap](../delivery/roadmap.md), particularly specification sections 4–10, 11–36 and roadmap T0002. This reference does not replace their complete requirements or define additional permissions.

## Actors and organizations

| Term | Meaning in this product | Source |
| --- | --- | --- |
| Buyer | Creates RFQs, invites Suppliers/Brokers, views and compares Offers, requests revisions, awards Offers, and views related Deals, Execution, Documents, and Issues. | Spec §4.1 |
| Supplier | Creates Supply Listings, views invited RFQs, submits Offers/revisions, and views its own Deals and related Execution statuses. | Spec §4.2 |
| Broker | Introduces Supply/Demand Opportunities and supply sources, responds with Offers, and views relevant RFQs and attributed Deals. Attribution is Opportunity/Deal-specific; the Broker neither permanently owns a customer nor must surrender a private network. | Spec §§3.2, 4.3, 30 |
| Operator | Qualifies RFQs and Opportunities, matches/invites participants, records external counterparties/contact attempts, submits Offers on behalf of counterparties, reviews verification, manages Deals, updates Execution monitoring, and manages Documents, Issues, and Internal Notes. | Spec §4.4 |
| Admin | Manages users, organizations, commodity definitions, verification rules, permissions, settings, and audit access. | Spec §4.5 |
| Organization | Company/party that may hold multiple business capabilities rather than one exclusive business role. | Spec §5 |
| Organization Capability | Buyer, Supplier, or Broker capability attached to an Organization; multiple capabilities are allowed. | Spec §5; T0202 |
| Organization Membership | User-to-Organization membership in the identity model. Owner, Manager, Member, and Viewer are example organization roles, not additional business actors. | T0202–T0203 |
| System Role | Operator or Admin; distinct from an Organization's business capabilities. | Spec §5; T0203 |
| External Counterparty | Off-platform party recorded by an Operator without requiring a user account; stores identity/contact/geography/source information and can later be converted to an Organization. | Spec §21; T0604 |

The allowed business actor vocabulary is Buyer, Supplier, Broker, Operator, and Admin. Do not introduce additional business roles.

## Procurement and discovery

| Term | Meaning in this product | Source |
| --- | --- | --- |
| Trade Hub | Supply/Demand entry point: RFQs on the demand side and Supply Listings on the supply side, with Private/Network/Public visibility. | Spec §§2, 11 |
| Procurement Engine | Business area for procurement workflows, matching, Offer comparison/evaluation, negotiation, and award. | Spec §§2–3, 15, 24–29 |
| RFQ | Request for quotation with commodity specifications, quantity/unit, commercial and delivery terms, quality requirements, visibility, invitations, and its own workspace. | Spec §§12–13; T0501–T0507 |
| Supply Listing | Formal supply record created by a Supplier or Operator, containing specifications, quantity, origin, availability, indicative price, commercial terms, and visibility. Distinct from an Opportunity. | Spec §14 |
| Market Discovery | Human-assisted capability for finding supply/demand beyond the existing network during the pilot. | Spec §§3.3, 16 |
| Opportunity Desk | Operational workspace for Market Discovery; supports sourcing, contact, qualification, follow-up, conversion, and traceability. | Spec §§16–22; T0601–T0612 |
| Opportunity | Supply- or Demand-directed lead with source, specifications, commercial/geographic information, confidence, confidentiality, operator assignment, and related business records. It is not automatically a formal listing or Offer. | Spec §§17–20 |
| Qualified Opportunity | Opportunity that has passed Operator qualification and can participate in matching. A Qualified Supply Opportunity can produce an Operator-entered Offer on an RFQ. Detailed qualification requirements still need definition. | Spec §§20, 23; T0608, T0611 |
| Contact Attempt | Recorded contact activity: call, message, email, meeting, or note. | Spec §22; T0606 |
| Matching | Rule-based, explainable suggestions across Organizations, Brokers, Supply Listings, and Qualified Opportunities using commodity/specification, geography, capability, availability, verification, relationship, and available historical signals. | Spec §§15, 23; T0701–T0708 |
| Offer | Commercial response submitted by a Supplier/Broker or entered by an Operator on behalf of a counterparty; includes price, quantity, delivery/payment/inspection terms, dynamic specifications, validity, and notes. Has an independent parent identity. | Spec §24; T0801, T0803–T0804 |
| Offer Version | Historical revision of an Offer. New revisions do not overwrite previous versions, and history remains visible. | Spec §25; T0802, T0811–T0812 |
| Normalisation / Landed Cost | Initial comparison calculation combining product price/cost, logistics, and known additional costs. Comparison also shows payment, delivery, trust, quality, and verification. Precise calculation conventions are not defined here. | Spec §26; T0805–T0807 |
| Decision Support | Explainable weighted recommendations to inform the Buyer/Operator, not an automatic final decision. Configurability timing differs between sources; see source review. | Spec §27; T0808–T0809 |
| Negotiation | Request revision, submit a revised Offer, and view Offer history; full chat is unnecessary in v1. | Spec §28 |
| Award | Buyer/Operator selects an Offer after reviewing final parties, price, quantity/value, delivery/payment terms, attribution, and conditions; creates a Deal. | Spec §29; T0813, T0901 |

## Deals, execution, and trust

| Term | Meaning in this product | Source |
| --- | --- | --- |
| Qualified Deal | Conceptual stage before Execution Monitor in the product flow. The specification defines Award as the Deal-creation trigger; a separate qualification state machine is not supplied. | Spec §§2, 29 |
| Deal | Award-created record with an immutable initial commercial snapshot of quantity, price, specifications, payment, delivery, and counterparties; later RFQ changes must not alter it. | Spec §§29–31; T0901–T0902 |
| Attribution | Record of Opportunity/Deal origin and relevant originators. Broker involvement preserves demand/supply originator, Broker, and Opportunity source; attribution is specific to the transaction/Opportunity. | Spec §§18–19, 30; T0605, T0903–T0904 |
| Execution Monitor | Visibility/orchestration workspace covering commercial, payment-status, logistics, quality, document, and issue tracking. It does not move money or execute settlement, financing, insurance, or logistics. | Spec §§3.4, 32–33; T1001–T1009 |
| Execution Workflow Template | Data-defined workflow using ExecutionWorkflowTemplate, ExecutionMilestoneDefinition, and Deal-instance ExecutionMilestone records. Demo requires no workflow-builder UI. | Spec §33; T1001–T1003 |
| Payment Monitoring | Expected, Reported, and Confirmed payment statuses only; no payment execution. | Spec §32; T1006 |
| Verification / KYB | Manual company verification with document review and statuses from Unverified through Verified or Suspended; no real KYC provider integration. | Spec §34; T0403–T0406 |
| Document | File stored in object storage, with database metadata such as object key, name, MIME/type, uploader, verification status, and creation time. | Spec §35 |
| Issue | Quality, quantity, logistics, payment, document, contract, or other problem tracked as Open, Investigating, Resolved, or Rejected. Execution's shorter issue list differs; see source review. | Spec §§32, 36; T1008 |
| Internal Note | Operator note on Organization, Opportunity, RFQ, or Deal; not visible to customers. | Spec §42; T1101 |
| Audit Trail | Important mutations recorded with who, what, when, old value, and new value, including verification, RFQ, Offer, Award, Deal, and Execution activity. | Spec §43; T1102 |
| Data / Trust / Intelligence | Procurement, Deal, supplier/broker performance, Opportunity conversion, and market metrics derived from recorded activity. Show insufficient-data messaging instead of fabricated price indices. | Spec §§37–40; T1201–T1208 |

## Commodity and locale concepts

| Term | Meaning in this product | Source |
| --- | --- | --- |
| Commodity Definition | CommodityDefinition identifies a commodity by code/name and active schema version reference. | Spec §8 |
| Commodity Schema / Schema Version | CommoditySchemaVersion identifies commodity/version/status and has runtime JSON Schema validation. RFQ/Supply/Offer records store the version used; later definitions must not reinterpret history. | Spec §§8–10; T0301–T0303 |
| Commodity Attribute Definition | Version-scoped attribute definition with key/label, data type, units, required flag, enum choices, validation rules, display group, and order. | Spec §8 |
| Dynamic Specifications | Commodity-specific values held in PostgreSQL JSONB and validated against versioned JSON Schema; never hard-coded core-table columns or reusable form fields. | Spec §§6–10, 50 |
| Bitumen | Initial product/demo commodity. Penetration grade, penetration, softening point, flash point, and ductility are example dynamic seed attributes, not core database columns. | Spec §§1, 7, 10; T0304 |
| Base Oil Architecture Test | Small secondary schema to demonstrate adding another commodity without migration; does not expand the primary Bitumen demo or authorize a generic builder UI. | T0305 |
| Locale-aware Frontend | Persian and English architectural targets with /fa RTL and /en LTR routing; only Persian is active in the demo. User-facing text must not be hard-coded in reusable components. | Spec §45; T0103, T1303–T1304 |

Unresolved source differences are recorded in the [source review](../architecture/source-review.md). Lifecycle transition matrices, detailed permission rules, and example values are not expanded into new requirements here.
