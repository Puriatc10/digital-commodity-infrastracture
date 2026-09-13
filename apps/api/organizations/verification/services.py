from django.db import transaction
from .models import OrganizationVerification, VerificationStatus, VerificationDecision, VerificationNote, VerificationChecklistReview
from documents.models import VerificationDocument, DocumentType

class VerificationDomainException(Exception):
    pass

class VerificationService:
    @staticmethod
    def _create_decision(verification: OrganizationVerification, actor, action: str, previous_status: str, new_status: str, reason: str = ""):
        VerificationDecision.objects.create(
            verification=verification,
            actor=actor,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason
        )

    @staticmethod
    def _lock_and_validate_verification(organization_id, expected_version, require_version=True):
        try:
            verification = OrganizationVerification.objects.select_for_update().get(organization_id=organization_id)
        except OrganizationVerification.DoesNotExist:
            raise VerificationDomainException("Verification record does not exist")

        if require_version and expected_version is None:
            raise VerificationDomainException("Expected version is required for mutation")

        if expected_version is not None and verification.version != expected_version:
             raise VerificationDomainException("Stale object error: another transaction modified this verification")

        return verification

    @staticmethod
    @transaction.atomic
    def _transition(organization_id, actor, action: str, expected_status_list, new_status: str, reason: str = "", expected_version: int = None, require_version: bool = True):
        verification = VerificationService._lock_and_validate_verification(organization_id, expected_version, require_version=require_version)

        if verification.status not in expected_status_list:
            raise VerificationDomainException(f"Invalid transition from {verification.status} to {new_status}")

        previous_status = verification.status
        verification.status = new_status
        verification.version += 1
        verification.save()

        VerificationService._create_decision(verification, actor, action, previous_status, new_status, reason)
        return verification

    @staticmethod
    def get_or_create_verification(organization_id):
        verification, _ = OrganizationVerification.objects.get_or_create(organization_id=organization_id)
        return verification


    @staticmethod
    @transaction.atomic
    def review_checklist_item(organization_id, document_id, actor, outcome: str, expected_version: int = None):
        if outcome not in ["accepted", "rejected"]:
            raise VerificationDomainException("Outcome must be 'accepted' or 'rejected'")

        verification = VerificationService._lock_and_validate_verification(organization_id, expected_version)

        try:
            document = VerificationDocument.objects.get(id=document_id, organization_id=organization_id)
        except VerificationDocument.DoesNotExist:
            raise VerificationDomainException("Document not found for this organization")

        if not document.is_current:
            raise VerificationDomainException("Cannot review superseded evidence")

        # Do not allow review if it would cause contradictory trust state, unless we downgrade trust
        if outcome == "rejected" and verification.status in [VerificationStatus.VERIFIED, VerificationStatus.BASIC_VERIFIED]:
            # For simplicity, prevent contradictory states instead of auto-downgrading here.
            # If they need to reject, they must suspend or reject the whole verification first,
            # or the system must downgrade. As per rules, rejection cannot leave contradictory trusted state.
            raise VerificationDomainException(f"Cannot reject evidence while status is {verification.status}. Please suspend or reject verification first.")

        # Always append immutable review and update document status for legacy/cache compatibility
        VerificationChecklistReview.objects.create(
            verification=verification,
            document=document,
            reviewer=actor,
            outcome=outcome
        )

        # We also update the document status so _check_documents_accepted still works efficiently
        document.verification_status = outcome
        document.verification_version = verification.version
        document.save()

        verification.version += 1
        verification.save()

        return verification

    @staticmethod
    @transaction.atomic
    def submit(organization_id, actor, expected_version: int = None):
        verification = VerificationService.get_or_create_verification(organization_id)
        if verification.status == VerificationStatus.UNVERIFIED:
            return VerificationService._transition(
                organization_id, actor, "submit",
                [VerificationStatus.UNVERIFIED],
                VerificationStatus.DOCUMENTS_SUBMITTED,
                expected_version=expected_version,
                require_version=False # Can be first submission
            )
        raise VerificationDomainException(f"Invalid transition from {verification.status} to {VerificationStatus.DOCUMENTS_SUBMITTED}")

    @staticmethod
    @transaction.atomic
    def start_review(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor, "start_review",
            [VerificationStatus.DOCUMENTS_SUBMITTED],
            VerificationStatus.UNDER_REVIEW,
            expected_version=expected_version
        )

    @staticmethod
    def _check_documents_accepted(organization_id, required_types):
        accepted_docs = VerificationDocument.objects.filter(
            organization_id=organization_id,
            is_current=True,
            verification_status="accepted",
            type__in=required_types
        ).values_list("type", flat=True)

        missing = set(required_types) - set(accepted_docs)
        if missing:
            raise VerificationDomainException(f"Missing accepted documents for: {', '.join(missing)}")

    @staticmethod
    @transaction.atomic
    def basic_approval(organization_id, actor, expected_version: int = None):
        VerificationService._lock_and_validate_verification(organization_id, expected_version)
        VerificationService._check_documents_accepted(
            organization_id,
            [DocumentType.COMPANY_REGISTRATION, DocumentType.TAX_ID, DocumentType.AUTHORIZED_REPRESENTATIVE]
        )
        return VerificationService._transition(
            organization_id, actor, "approve_basic",
            [VerificationStatus.UNDER_REVIEW],
            VerificationStatus.BASIC_VERIFIED,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def full_approval(organization_id, actor, expected_version: int = None):
        VerificationService._lock_and_validate_verification(organization_id, expected_version)
        VerificationService._check_documents_accepted(
            organization_id,
            [DocumentType.COMPANY_REGISTRATION, DocumentType.TAX_ID, DocumentType.AUTHORIZED_REPRESENTATIVE, DocumentType.TRADE_LICENSE, DocumentType.BANK_DETAILS]
        )
        return VerificationService._transition(
            organization_id, actor, "approve_full",
            [VerificationStatus.UNDER_REVIEW],
            VerificationStatus.VERIFIED,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def reject(organization_id, actor, reason: str, expected_version: int = None):
        if not reason:
            raise VerificationDomainException("Rejection requires a reason")
        return VerificationService._transition(
            organization_id, actor, "reject",
            [VerificationStatus.UNDER_REVIEW],
            VerificationStatus.UNVERIFIED,
            reason,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def suspend(organization_id, actor, reason: str, expected_version: int = None):
        if not reason:
            raise VerificationDomainException("Suspension requires a reason")
        return VerificationService._transition(
            organization_id, actor, "suspend",
            [VerificationStatus.BASIC_VERIFIED, VerificationStatus.VERIFIED],
            VerificationStatus.SUSPENDED,
            reason,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def reopen(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor, "reopen",
            [VerificationStatus.SUSPENDED, VerificationStatus.BASIC_VERIFIED],
            VerificationStatus.UNDER_REVIEW,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def reset_due_to_evidence_replacement(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor, "evidence_replacement_invalidation",
            [VerificationStatus.BASIC_VERIFIED, VerificationStatus.VERIFIED],
            VerificationStatus.DOCUMENTS_SUBMITTED,
            "Required evidence replacement",
            expected_version=expected_version,
            require_version=False # triggered by system internally
        )

    @staticmethod
    @transaction.atomic
    def add_internal_note(organization_id, actor, note: str):
        if not note:
             raise VerificationDomainException("Note cannot be empty")
        verification = VerificationService.get_or_create_verification(organization_id)
        return VerificationNote.objects.create(
            verification=verification,
            actor=actor,
            note=note
        )
