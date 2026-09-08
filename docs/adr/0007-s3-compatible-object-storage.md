# ADR 0007: S3-compatible Object Storage

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Actual document files use S3-compatible object storage. Use MinIO for the demo. PostgreSQL stores document metadata, including id, file_name, object_key, mime_type, type, uploaded_by, verification_status, and created_at.

Local infrastructure is planned as Docker Compose with PostgreSQL and MinIO (T0104). T0405 explicitly requires verification document metadata and MinIO upload.

## Consequences and open detail

This replaces the earlier foundation placeholder: storage requirements are now explicitly supplied. PostgreSQL remains the source of truth, with object storage holding file bytes.

Provider/library configuration, production storage choice, retention, upload constraints, and detailed object access controls remain unspecified. Server-side authorization still applies. No buckets, services, uploads, or infrastructure are created by this ADR.

Sources: [Product Specification](../product/product-spec.md) §§35, 50, 53–54; [Delivery Roadmap](../delivery/roadmap.md) T0003, T0104, T0405, T1007.
