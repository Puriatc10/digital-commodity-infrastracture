import os
import re
import uuid
from typing import Any, Optional, Tuple, Union
from uuid import UUID

from django.db import transaction

from documents.storage import delete_document, get_document_bytes, upload_document
from execution.enums import ExecutionDocumentCategory
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionDocumentNotFoundError,
    ExecutionNotFoundError,
    ExecutionStorageError,
    ExecutionValidationError,
)
from execution.models.document import ExecutionDocument
from execution.models.execution import Execution
from execution.models.inspection import ExecutionInspection
from execution.models.milestone import ExecutionMilestone
from execution.permissions import (
    check_document_read_authority,
    check_document_upload_authority,
)

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


def _sanitize_filename(filename: str) -> str:
    """Extract safe basename from filename, stripping path traversals and control characters."""
    if not filename:
        return "document"
    # Strip paths
    basename = os.path.basename(filename.replace("\\", "/"))
    # Remove control characters and non-printable characters
    clean = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
    return clean[:200] if clean else "document"


def _validate_file_content(file_obj: Any) -> Tuple[str, int]:
    """
    Validate file content-type, magic bytes signature, and non-empty size.

    Allowed MIME types:
    - application/pdf: magic bytes start with %PDF-
    - image/jpeg: magic bytes start with \xff\xd8\xff
    - image/png: magic bytes start with \x89PNG\r\n\x1a\n
    """
    size = getattr(file_obj, "size", None)
    if size is None:
        pos = file_obj.tell()
        file_obj.seek(0, os.SEEK_END)
        size = file_obj.tell()
        file_obj.seek(pos)

    if size <= 0:
        raise ExecutionValidationError("Uploaded file cannot be empty.")
    if size > MAX_DOCUMENT_SIZE_BYTES:
        raise ExecutionValidationError("Uploaded file exceeds maximum allowed size of 10 MB.")

    content_type = getattr(file_obj, "content_type", "").lower().strip()
    if content_type not in ["application/pdf", "image/jpeg", "image/png"]:
        raise ExecutionValidationError(
            f"Unsupported content type '{content_type}'. Allowed types are application/pdf, image/jpeg, image/png."
        )

    # Magic byte verification
    header = file_obj.read(16)
    file_obj.seek(0)

    is_valid = False
    if content_type == "application/pdf":
        is_valid = header.startswith(b"%PDF-")
    elif content_type == "image/jpeg":
        is_valid = header.startswith(b"\xff\xd8\xff")
    elif content_type == "image/png":
        is_valid = header.startswith(b"\x89PNG\r\n\x1a\n")

    if not is_valid:
        raise ExecutionValidationError(
            f"File content does not match declared MIME type '{content_type}'."
        )

    return content_type, size


def upload_execution_document(
    execution_id: Union[UUID, str],
    *,
    file_obj: Any,
    category: str,
    actor: Any,
    milestone_id: Optional[Union[UUID, str]] = None,
    inspection_id: Optional[Union[UUID, str]] = None,
) -> ExecutionDocument:
    """
    Authorized multipart evidence upload for an Execution aggregate (Epic 10 Contract §60–§64, T1007).

    Invariants:
    - Execution exists and is accessible.
    - Side-specific category authorization verified for actor.
    - File size, content type, and magic bytes strictly validated.
    - Same-Execution Guard: optional milestone and inspection MUST belong to the same execution.
    - Server derives storage identity (UUID-based object_key); client cannot control or substitute keys.
    - Bytes reside strictly in MinIO/S3 object storage; PostgreSQL persists metadata only.
    - Storage atomicity: storage succeeds + DB fails -> immediate practical compensation deletes orphaned object.
    - Append-only evidence: creates a new ExecutionDocument record; does not mutate existing evidence or domain state.
    """
    try:
        execution = Execution.objects.select_related("deal").get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if category not in ExecutionDocumentCategory.values:
        raise ExecutionValidationError(
            f"Invalid document category '{category}'. Must be one of: {list(ExecutionDocumentCategory.values)}."
        )

    # 1. Authorization check
    check_document_upload_authority(actor, execution, category)

    # 2. File validation
    content_type, size = _validate_file_content(file_obj)
    safe_filename = _sanitize_filename(getattr(file_obj, "name", "document.pdf"))

    # 3. Same-Execution Guard (Epic 10 Contract §62)
    milestone = None
    if milestone_id:
        try:
            milestone = ExecutionMilestone.objects.get(pk=milestone_id)
        except ExecutionMilestone.DoesNotExist:
            raise ExecutionValidationError(f"Milestone '{milestone_id}' does not exist.")
        if milestone.execution_id != execution.id:
            raise CrossObjectIntegrityError(
                f"Milestone '{milestone_id}' belongs to execution '{milestone.execution_id}', "
                f"not target execution '{execution.id}'."
            )

    inspection = None
    if inspection_id:
        try:
            inspection = ExecutionInspection.objects.get(pk=inspection_id)
        except ExecutionInspection.DoesNotExist:
            raise ExecutionValidationError(f"Inspection '{inspection_id}' does not exist.")
        if inspection.execution_id != execution.id:
            raise CrossObjectIntegrityError(
                f"Inspection '{inspection_id}' belongs to execution '{inspection.execution_id}', "
                f"not target execution '{execution.id}'."
            )

    # 4. Generate server-side storage identity (Client cannot control or substitute)
    storage_uuid = uuid.uuid4()
    object_key = f"execution-documents/{execution.id}/{storage_uuid}-{safe_filename}"

    # 5. Upload bytes to object storage
    try:
        upload_document(file_obj, object_key, content_type, size)
    except Exception as exc:
        raise ExecutionStorageError(f"Failed to upload document to object storage: {exc}") from exc

    # 6. Persist metadata in DB with practical compensation
    try:
        with transaction.atomic():
            doc = ExecutionDocument.objects.create(
                execution=execution,
                milestone=milestone,
                inspection=inspection,
                category=category,
                file_name=safe_filename,
                content_type=content_type,
                size_bytes=size,
                object_key=object_key,
                uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
            )
            return doc
    except Exception as exc:
        # Practical compensation: remove orphaned storage object
        try:
            delete_document(object_key)
        except Exception:
            pass
        raise exc


def get_execution_documents(
    execution_id: Union[UUID, str],
    *,
    actor: Any,
    category: Optional[str] = None,
    milestone_id: Optional[Union[UUID, str]] = None,
    inspection_id: Optional[Union[UUID, str]] = None,
):
    """
    List metadata for documents belonging to an Execution, with optional contextual filtering.
    """
    try:
        execution = Execution.objects.select_related("deal").get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    check_document_read_authority(actor, execution)

    qs = (
        ExecutionDocument.objects.filter(execution=execution)
        .select_related("uploaded_by", "milestone__definition", "inspection")
        .order_by("-uploaded_at", "-id")
    )

    if category:
        qs = qs.filter(category=category)
    if milestone_id:
        qs = qs.filter(milestone_id=milestone_id)
    if inspection_id:
        qs = qs.filter(inspection_id=inspection_id)

    return qs


def get_execution_document_detail(
    execution_id: Union[UUID, str],
    document_id: Union[UUID, str],
    *,
    actor: Any,
) -> ExecutionDocument:
    """
    Retrieve single document metadata record for an Execution.
    """
    try:
        execution = Execution.objects.select_related("deal").get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    check_document_read_authority(actor, execution)

    try:
        return (
            ExecutionDocument.objects.select_related("uploaded_by", "milestone__definition", "inspection")
            .get(pk=document_id, execution=execution)
        )
    except ExecutionDocument.DoesNotExist:
        raise ExecutionDocumentNotFoundError(
            f"Execution document '{document_id}' not found for execution '{execution_id}'."
        )


def get_execution_document_download(
    execution_id: Union[UUID, str],
    document_id: Union[UUID, str],
    *,
    actor: Any,
) -> Tuple[bytes, str, str]:
    """
    Retrieve document binary bytes, MIME type, and safe filename for controlled authorized streaming download.
    """
    doc = get_execution_document_detail(execution_id, document_id, actor=actor)

    data = get_document_bytes(doc.object_key)
    if data is None:
        raise ExecutionStorageError(f"Document content for '{doc.id}' not found in object storage.")

    return data, doc.content_type, doc.file_name
