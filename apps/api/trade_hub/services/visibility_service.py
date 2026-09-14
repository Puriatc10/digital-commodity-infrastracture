import uuid
from typing import Any

from django.db import models
from django.db.models import QuerySet

from identity.models import SystemRoleAssignment
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
)
from trade_hub.exceptions import RFQNotFoundError, SupplyListingNotFoundError
from trade_hub.models.rfq import RFQ, RFQStatus, RFQVisibility
from trade_hub.models.supply import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


def _extract_rfq_id(rfq_or_id: Any) -> uuid.UUID:
    if isinstance(rfq_or_id, RFQ):
        return rfq_or_id.pk
    if isinstance(rfq_or_id, uuid.UUID):
        return rfq_or_id
    if isinstance(rfq_or_id, str):
        try:
            return uuid.UUID(rfq_or_id)
        except (ValueError, AttributeError) as exc:
            raise RFQNotFoundError(f"Invalid RFQ ID: '{rfq_or_id}'") from exc
    raise RFQNotFoundError(f"Invalid RFQ identifier: '{rfq_or_id}'")


def _extract_organization_id(org_or_id: Any) -> uuid.UUID | None:
    if isinstance(org_or_id, Organization):
        return org_or_id.pk
    if isinstance(org_or_id, uuid.UUID):
        return org_or_id
    if isinstance(org_or_id, str):
        try:
            return uuid.UUID(org_or_id)
        except (ValueError, AttributeError):
            return None
    return None


class RFQVisibilityService:
    """
    Authoritative domain service governing server-side RFQ visibility and QuerySet scoping.

    Centralizes all visibility rules across Public, Network, and Private visibility tiers,
    ensuring strict separation of business capabilities and system roles, preventing IDOR,
    and avoiding information leakage across lifecycle states.
    """

    _invitation_resolver = None

    @classmethod
    def register_invitation_resolver(cls, resolver: Any) -> None:
        """
        Register a collaborator for resolving private invitations.
        Provided as an integration boundary for T0506.
        """
        cls._invitation_resolver = resolver

    @classmethod
    def get_invitation_q(cls, organization: Organization) -> models.Q:
        """
        T0506 integration boundary hook.
        Returns a Q object matching RFQs where the organization is an invited participant
        with an active invitation status (invited, viewed, responded).
        Declined and expired invitations do not grant visibility.
        """
        if callable(cls._invitation_resolver):
            return cls._invitation_resolver(organization)

        from trade_hub.models.invitation import RFQInvitation, RFQInvitationStatus

        active_rfq_ids = RFQInvitation.objects.filter(
            organization=organization,
            status__in=[
                RFQInvitationStatus.INVITED,
                RFQInvitationStatus.VIEWED,
                RFQInvitationStatus.RESPONDED,
            ],
        ).values_list("rfq_id", flat=True)
        return models.Q(id__in=active_rfq_ids)

    @staticmethod
    def has_global_visibility(user: Any) -> bool:
        """
        Verify if user has global operational visibility.
        Conferred ONLY by SystemRoleAssignment(OPERATOR or ADMIN).
        Django is_staff and is_superuser alone grant NO global operational access.
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

    @staticmethod
    def resolve_authoritative_organization(
        user: Any, organization: Any = None
    ) -> Organization | None:
        """
        Resolve the authoritative active organization for the user.

        Guarantees that client-supplied organization IDs are never trusted blindly:
        the user MUST have an active membership in an active organization.
        If no organization is provided, checks if the user has exactly one active membership.
        """
        if not user or not getattr(user, "is_authenticated", False):
            return None

        org_id = _extract_organization_id(organization)
        if org_id is None:
            if organization is not None:
                # Invalid organization representation supplied
                return None
            # If no organization provided, check if user has exactly one active membership
            memberships = list(
                OrganizationMembership.objects.filter(
                    user=user,
                    is_active=True,
                    organization__is_active=True,
                ).values_list("organization_id", flat=True)
            )
            if len(memberships) == 1:
                org_id = memberships[0]
            else:
                return None

        membership = (
            OrganizationMembership.objects.filter(
                user=user,
                organization_id=org_id,
                is_active=True,
                organization__is_active=True,
            )
            .select_related("organization")
            .first()
        )
        if not membership:
            return None
        return membership.organization

    @classmethod
    def get_visible_rfqs(
        cls,
        user: Any,
        organization: Any = None,
        base_queryset: QuerySet[RFQ] | None = None,
    ) -> QuerySet[RFQ]:
        """
        Return the visibility-scoped QuerySet of RFQs for a given user and organization context.

        Scoping rules:
        - Anonymous / unauthenticated -> none()
        - Operator / Product Admin -> all RFQs (Draft, Published, Closed, Cancelled, all tiers)
        - Non-operator without valid active organization -> none()
        - Owning Buyer Organization -> all RFQs owned by that organization (all statuses, all tiers)
        - External Organizations:
            - Must be Published (Draft, Closed, Cancelled are hidden)
            - Must have Supplier or Broker capability (Buyer-only orgs cannot see external RFQs)
            - Public tier: visible to any external Supplier or Broker
            - Network tier: visible only if organization has matching OrganizationCommodity
            - Private tier: visible only if explicitly invited (via T0506 invitation hook)
        """
        if base_queryset is None:
            base_queryset = RFQ.objects.all()

        if not user or not getattr(user, "is_authenticated", False):
            return base_queryset.none()

        # 1. Global operational access (Operator / Admin)
        if cls.has_global_visibility(user):
            return base_queryset.all()

        # 2. Resolve authoritative current organization
        current_org = cls.resolve_authoritative_organization(user, organization)
        if current_org is None:
            return base_queryset.none()

        # 3. Owner access: can view own RFQs in any lifecycle state
        owner_q = models.Q(organization=current_org)

        # 4. External access:
        # Check active capabilities for current organization ONLY
        capabilities = set(
            OrganizationCapability.objects.filter(
                organization=current_org,
            ).values_list("capability", flat=True)
        )
        has_supplier_or_broker = bool(
            capabilities
            & {
                OrganizationCapability.CapabilityType.SUPPLIER,
                OrganizationCapability.CapabilityType.BROKER,
            }
        )

        # External discovery rule: only Published RFQs owned by other organizations
        external_published_base = models.Q(status=RFQStatus.PUBLISHED) & ~models.Q(
            organization=current_org
        )

        external_q = models.Q(pk__in=[])

        if has_supplier_or_broker:
            # Public tier: visible to any external Supplier or Broker
            public_q = models.Q(visibility=RFQVisibility.PUBLIC)

            # Network tier: requires OrganizationCommodity matching RFQ commodity
            org_commodities = OrganizationCommodity.objects.filter(
                organization=current_org
            ).values("commodity_id")
            network_q = models.Q(
                visibility=RFQVisibility.NETWORK,
                commodity_id__in=org_commodities,
            )

            external_q = public_q | network_q

        # Private tier hook (T0506 boundary): invited organizations
        invitation_q = cls.get_invitation_q(current_org)
        if invitation_q:
            external_q = external_q | (
                models.Q(visibility=RFQVisibility.PRIVATE) & invitation_q
            )

        final_q = owner_q | (external_published_base & external_q)
        return base_queryset.filter(final_q).distinct()

    @classmethod
    def get_visible_rfq(
        cls,
        rfq_or_id: Any,
        user: Any,
        organization: Any = None,
        base_queryset: QuerySet[RFQ] | None = None,
    ) -> RFQ:
        """
        Perform a direct ID lookup of an RFQ through the visibility-scoped QuerySet.

        Raises RFQNotFoundError if the RFQ does not exist OR is not visible to the user/org,
        ensuring 404-like hidden resource semantics and preventing existence/timing leaks.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        qs = cls.get_visible_rfqs(
            user, organization=organization, base_queryset=base_queryset
        )
        try:
            return qs.get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise RFQNotFoundError(
                f"RFQ with id '{rfq_id}' does not exist or is not visible."
            ) from exc

    @classmethod
    def is_rfq_visible(
        cls,
        rfq_or_id: Any,
        user: Any,
        organization: Any = None,
    ) -> bool:
        """Helper predicate returning boolean visibility without raising exceptions."""
        try:
            cls.get_visible_rfq(rfq_or_id, user, organization=organization)
            return True
        except RFQNotFoundError:
            return False


def get_visible_rfqs_for_request(
    request: Any,
    base_queryset: QuerySet[RFQ] | None = None,
) -> QuerySet[RFQ]:
    """
    Convenience helper for API views to resolve visibility scope directly from a DRF request.
    Extracts user and organization hint, resolving authoritative membership server-side.
    """
    user = getattr(request, "user", None)
    org_hint = getattr(request, "current_organization", None) or getattr(
        request, "organization", None
    )
    if org_hint is None and hasattr(request, "session"):
        org_hint = request.session.get("organization_id")
    if org_hint is None and hasattr(request, "headers"):
        org_hint = request.headers.get("X-Organization-Id")
    if org_hint is None and hasattr(request, "query_params"):
        org_hint = request.query_params.get("organization")

    return RFQVisibilityService.get_visible_rfqs(
        user=user,
        organization=org_hint,
        base_queryset=base_queryset,
    )


def get_visible_rfq_for_request(
    rfq_or_id: Any,
    request: Any,
    base_queryset: QuerySet[RFQ] | None = None,
) -> RFQ:
    """Convenience helper for API views to retrieve a single visible RFQ from a DRF request."""
    user = getattr(request, "user", None)
    org_hint = getattr(request, "current_organization", None) or getattr(
        request, "organization", None
    )
    if org_hint is None and hasattr(request, "session"):
        org_hint = request.session.get("organization_id")
    if org_hint is None and hasattr(request, "headers"):
        org_hint = request.headers.get("X-Organization-Id")
    if org_hint is None and hasattr(request, "query_params"):
        org_hint = request.query_params.get("organization")

    return RFQVisibilityService.get_visible_rfq(
        rfq_or_id=rfq_or_id,
        user=user,
        organization=org_hint,
        base_queryset=base_queryset,
    )


# Module-level convenience functions
get_visible_rfqs = RFQVisibilityService.get_visible_rfqs
get_visible_rfq = RFQVisibilityService.get_visible_rfq
is_rfq_visible = RFQVisibilityService.is_rfq_visible
has_global_visibility = RFQVisibilityService.has_global_visibility
resolve_authoritative_organization = (
    RFQVisibilityService.resolve_authoritative_organization
)


def _extract_supply_id(supply_or_id: Any) -> uuid.UUID:
    if isinstance(supply_or_id, SupplyListing):
        return supply_or_id.pk
    if isinstance(supply_or_id, uuid.UUID):
        return supply_or_id
    if isinstance(supply_or_id, str):
        try:
            return uuid.UUID(supply_or_id)
        except (ValueError, AttributeError) as exc:
            raise SupplyListingNotFoundError(
                f"Invalid supply listing ID: '{supply_or_id}'"
            ) from exc
    raise SupplyListingNotFoundError(f"Invalid supply listing identifier: '{supply_or_id}'")


class SupplyListingVisibilityService:
    """
    Authoritative domain service governing server-side SupplyListing visibility and QuerySet scoping.

    Centralizes all visibility rules across Public, Network, and Private visibility tiers,
    ensuring strict separation of business capabilities and system roles, preventing IDOR,
    and avoiding information leakage across lifecycle states.
    """

    @classmethod
    def get_visible_supply_listings(
        cls,
        user: Any,
        organization: Any = None,
        base_queryset: QuerySet[SupplyListing] | None = None,
    ) -> QuerySet[SupplyListing]:
        """
        Return the visibility-scoped QuerySet of SupplyListings for a given user and organization context.

        Scoping rules:
        - Anonymous / unauthenticated -> none()
        - Operator / Product Admin -> all supply listings (Draft, Active, Closed, Expired, all tiers)
        - Non-operator without valid active organization -> none()
        - Owning Supplier Organization -> all listings owned by that organization (all statuses, all tiers)
        - External Organizations:
            - Must be Active (Draft, Closed, Expired are hidden)
            - Public tier: visible to any authenticated organization
            - Network tier: visible only if organization has matching OrganizationCommodity
            - Private tier: hidden from external parties (only owner and operators can view)
        """
        if base_queryset is None:
            base_queryset = SupplyListing.objects.all()

        if not user or not getattr(user, "is_authenticated", False):
            return base_queryset.none()

        # 1. Global operational access (Operator / Admin)
        if has_global_visibility(user):
            return base_queryset.all()

        # 2. Resolve authoritative current organization
        current_org = resolve_authoritative_organization(user, organization)
        if current_org is None:
            return base_queryset.none()

        # 3. Owner access: can view own supply listings in any lifecycle state
        owner_q = models.Q(organization=current_org)

        # 4. External access:
        # External discovery rule: only Active supply listings owned by other organizations
        external_active_base = models.Q(
            status=SupplyListingStatus.ACTIVE
        ) & ~models.Q(organization=current_org)

        # Public tier: visible to any external authenticated organization
        public_q = models.Q(visibility=SupplyListingVisibility.PUBLIC)

        # Network tier: requires OrganizationCommodity matching listing commodity
        org_commodities = OrganizationCommodity.objects.filter(
            organization=current_org
        ).values("commodity_id")
        network_q = models.Q(
            visibility=SupplyListingVisibility.NETWORK,
            commodity_id__in=org_commodities,
        )

        external_q = public_q | network_q
        final_q = owner_q | (external_active_base & external_q)
        return base_queryset.filter(final_q).distinct()

    @classmethod
    def get_visible_supply_listing(
        cls,
        supply_or_id: Any,
        user: Any,
        organization: Any = None,
        base_queryset: QuerySet[SupplyListing] | None = None,
    ) -> SupplyListing:
        """
        Perform a direct ID lookup of a SupplyListing through the visibility-scoped QuerySet.

        Raises SupplyListingNotFoundError if the listing does not exist OR is not visible to the caller,
        ensuring 404-like hidden resource semantics and preventing existence/timing leaks.
        """
        supply_id = _extract_supply_id(supply_or_id)
        qs = cls.get_visible_supply_listings(
            user, organization=organization, base_queryset=base_queryset
        )
        try:
            return qs.get(pk=supply_id)
        except SupplyListing.DoesNotExist as exc:
            raise SupplyListingNotFoundError(
                f"Supply listing with id '{supply_id}' does not exist or is not visible."
            ) from exc

    @classmethod
    def is_supply_listing_visible(
        cls,
        supply_or_id: Any,
        user: Any,
        organization: Any = None,
    ) -> bool:
        """Helper predicate returning boolean visibility without raising exceptions."""
        try:
            cls.get_visible_supply_listing(supply_or_id, user, organization=organization)
            return True
        except SupplyListingNotFoundError:
            return False


def get_visible_supply_listings_for_request(
    request: Any,
    base_queryset: QuerySet[SupplyListing] | None = None,
) -> QuerySet[SupplyListing]:
    """
    Convenience helper for API views to resolve visibility scope directly from a DRF request.
    Extracts user and organization hint, resolving authoritative membership server-side.
    """
    user = getattr(request, "user", None)
    org_hint = getattr(request, "current_organization", None) or getattr(
        request, "organization", None
    )
    if org_hint is None and hasattr(request, "session"):
        org_hint = request.session.get("organization_id")
    if org_hint is None and hasattr(request, "headers"):
        org_hint = request.headers.get("X-Organization-Id")
    if org_hint is None and hasattr(request, "query_params"):
        org_hint = request.query_params.get("organization")

    return SupplyListingVisibilityService.get_visible_supply_listings(
        user=user,
        organization=org_hint,
        base_queryset=base_queryset,
    )


def get_visible_supply_listing_for_request(
    supply_or_id: Any,
    request: Any,
    base_queryset: QuerySet[SupplyListing] | None = None,
) -> SupplyListing:
    """Convenience helper for API views to retrieve a single visible SupplyListing from a DRF request."""
    user = getattr(request, "user", None)
    org_hint = getattr(request, "current_organization", None) or getattr(
        request, "organization", None
    )
    if org_hint is None and hasattr(request, "session"):
        org_hint = request.session.get("organization_id")
    if org_hint is None and hasattr(request, "headers"):
        org_hint = request.headers.get("X-Organization-Id")
    if org_hint is None and hasattr(request, "query_params"):
        org_hint = request.query_params.get("organization")

    return SupplyListingVisibilityService.get_visible_supply_listing(
        supply_or_id=supply_or_id,
        user=user,
        organization=org_hint,
        base_queryset=base_queryset,
    )


get_visible_supply_listings = SupplyListingVisibilityService.get_visible_supply_listings
get_visible_supply_listing = SupplyListingVisibilityService.get_visible_supply_listing
is_supply_listing_visible = SupplyListingVisibilityService.is_supply_listing_visible
