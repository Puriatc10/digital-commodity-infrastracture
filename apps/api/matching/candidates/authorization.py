from typing import Any, Optional
import uuid

from django.core.exceptions import PermissionDenied

from identity.models import SystemRoleAssignment
from matching.candidates.context import ActorScope, CandidateContext
from matching.enums import MatchingAudience
from organizations.models import Organization, OrganizationMembership


class MatchingAuthorizationError(PermissionDenied):
    """Raised when an actor lacks authority to trigger matching or access candidate intelligence."""
    pass


class MatchingPrivacyViolationError(PermissionDenied):
    """Raised when a boundary rule or privacy invariant is violated during candidate discovery."""
    pass


def has_global_matching_authority(user: Any) -> bool:
    """
    Check whether a user holds global Operator or Product Admin matching authority.

    Critical Invariant: Conferred strictly by SystemRoleAssignment(OPERATOR or ADMIN).
    Django is_staff and is_superuser alone grant NO global operational authority.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


def is_active_organization_member(user: Any, organization_id: uuid.UUID | str) -> bool:
    """Verify that a user is an active member of the specified organization."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return OrganizationMembership.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
    ).exists()


def resolve_actor_scope(user: Any, organization: Optional[Any] = None) -> ActorScope:
    """Resolve an ActorScope from an authenticated user and optional organization context."""
    is_op_or_admin = has_global_matching_authority(user)
    org_instance = None
    if isinstance(organization, Organization):
        org_instance = organization
    elif organization is not None:
        try:
            org_instance = Organization.objects.filter(pk=organization).first()
        except (ValueError, TypeError):
            org_instance = None

    return ActorScope(
        user=user,
        organization=org_instance,
        is_operator_or_admin=is_op_or_admin,
    )


def validate_actor_audience_authorization(
    actor_scope: ActorScope,
    context: CandidateContext,
) -> None:
    """
    Validate that an actor is authorized to discover candidates under the requested audience and RFQ context.

    Rules:
    - Anonymous / unauthenticated callers are strictly rejected.
    - OPERATOR audience: requires Operator or Admin system role (SystemRoleAssignment).
      Django staff or superuser flags alone grant NO bypass.
    - BUYER audience: caller must be an active member of the RFQ owner organization,
      or hold global Operator/Admin system authority.
    - Third-party Suppliers, Brokers, or unrelated Organizations are forbidden from
      triggering matching or discovering candidate intelligence for an RFQ they do not own.
    """
    user = actor_scope.user
    if not user or not getattr(user, "is_authenticated", False):
        raise MatchingAuthorizationError("Authentication is required for candidate discovery.")

    if context.audience == MatchingAudience.OPERATOR:
        if not actor_scope.is_operator_or_admin:
            raise MatchingAuthorizationError(
                "Operator audience candidate discovery requires Operator or Admin system role."
            )
        return

    if context.audience == MatchingAudience.BUYER:
        if actor_scope.is_operator_or_admin:
            return  # Operators/Admins may view Buyer discovery context
        if not is_active_organization_member(user, context.rfq_owner_organization_id):
            raise MatchingAuthorizationError(
                "User is not an authorized member of the RFQ owner organization."
            )
        return

    raise MatchingAuthorizationError(f"Unsupported matching audience: '{context.audience}'.")
