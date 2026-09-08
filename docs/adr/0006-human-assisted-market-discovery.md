# ADR 0006: Human-assisted Market Discovery

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Market Discovery is the capability; Opportunity Desk is its operational workspace. Discovery is intentionally human-assisted during the pilot: support Operators, not replace them.

Operators capture Supply/Demand Opportunities, record external counterparties without requiring accounts, log contact attempts and follow-ups, qualify Opportunities, and preserve source links through conversion to RFQs, Supply Listings, or Offers.

Broker referrals preserve the originating Broker. Attribution remains Opportunity/Deal-specific, never permanent customer ownership; the platform must not force Brokers to surrender their private networks. Operator-entered Offers must be traceable. Rule-based matching includes Qualified Opportunities alongside network participants and listings.

## Consequences and open detail

AI matching/agents are outside v1. Qualification requirements and permitted transitions still require task-level definition. The sequencing of Opportunity-originated Offers versus the later Offer domain epic is an unresolved delivery dependency; see [source review](../architecture/source-review.md). No Opportunities, Matching, or Offers are implemented here.

Sources: [Product Specification](../product/product-spec.md) §§3.2–3.3, 16–24, 30, 56; [Delivery Roadmap](../delivery/roadmap.md) T0601–T0612, T0706, T0804.
