from django.db import transaction
from .models import OrganizationVerification, VerificationStatus, VerificationDecision, VerificationNote

class VerificationDomainException(Exception):
    pass

class VerificationService:
    @staticmethod
    def _create_decision(verification: OrganizationVerification, actor, previous_status: str, new_status: str, reason: str = ""):
        VerificationDecision.objects.create(
            verification=verification,
            actor=actor,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason
        )

    @staticmethod
    @transaction.atomic
    def _transition(organization_id, actor, expected_status_list, new_status: str, reason: str = "", expected_version: int = None):
        try:
            verification = OrganizationVerification.objects.select_for_update().get(organization_id=organization_id)
        except OrganizationVerification.DoesNotExist:
            raise VerificationDomainException(f"Verification record does not exist. Cannot transition to {new_status}")

        if expected_version is not None and verification.version != expected_version:
             raise VerificationDomainException("Stale object error: another transaction modified this verification")

        if verification.status not in expected_status_list:
            raise VerificationDomainException(f"Invalid transition from {verification.status} to {new_status}")

        previous_status = verification.status
        verification.status = new_status
        verification.version += 1
        verification.save()

        VerificationService._create_decision(verification, actor, previous_status, new_status, reason)
        return verification

    @staticmethod
    def get_or_create_verification(organization_id):
        verification, _ = OrganizationVerification.objects.get_or_create(organization_id=organization_id)
        return verification

    @staticmethod
    @transaction.atomic
    def submit(organization_id, actor, expected_version: int = None):
        verification = VerificationService.get_or_create_verification(organization_id)
        if verification.status == VerificationStatus.UNVERIFIED:
            return VerificationService._transition(
                organization_id, actor,
                [VerificationStatus.UNVERIFIED],
                VerificationStatus.DOCUMENTS_SUBMITTED,
                expected_version=expected_version
            )
        raise VerificationDomainException(f"Invalid transition from {verification.status} to {VerificationStatus.DOCUMENTS_SUBMITTED}")

    @staticmethod
    @transaction.atomic
    def start_review(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor,
            [VerificationStatus.DOCUMENTS_SUBMITTED],
            VerificationStatus.UNDER_REVIEW,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def basic_approval(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor,
            [VerificationStatus.UNDER_REVIEW],
            VerificationStatus.BASIC_VERIFIED,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def full_approval(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor,
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
            organization_id, actor,
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
            organization_id, actor,
            [VerificationStatus.BASIC_VERIFIED, VerificationStatus.VERIFIED],
            VerificationStatus.SUSPENDED,
            reason,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def reopen(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor,
            [VerificationStatus.SUSPENDED, VerificationStatus.BASIC_VERIFIED],
            VerificationStatus.UNDER_REVIEW,
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def reset_due_to_evidence_replacement(organization_id, actor, expected_version: int = None):
        return VerificationService._transition(
            organization_id, actor,
            [VerificationStatus.BASIC_VERIFIED, VerificationStatus.VERIFIED],
            VerificationStatus.DOCUMENTS_SUBMITTED,
            "Required evidence replacement",
            expected_version=expected_version
        )

    @staticmethod
    @transaction.atomic
    def add_internal_note(organization_id, actor, note: str):
        if not note:
             raise VerificationDomainException("Note cannot be empty")
        verification = OrganizationVerification.objects.get(organization_id=organization_id)
        return VerificationNote.objects.create(
            verification=verification,
            actor=actor,
            note=note
        )
