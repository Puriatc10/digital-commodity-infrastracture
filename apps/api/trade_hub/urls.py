from django.urls import path

from trade_hub.api.views_invitation import (
    RFQInvitationDeclineActionView,
    RFQInvitationDetailView,
    RFQInvitationListCreateView,
    RFQInvitationMeView,
    RFQInvitationViewActionView,
)

from trade_hub.api.views_rfq import (
    RFQActivityView,
    RFQCancelActionView,
    RFQCloseActionView,
    RFQDetailView,
    RFQListCreateView,
    RFQPublishActionView,
)
from trade_hub.api.views_supply import (
    SupplyListingActivateActionView,
    SupplyListingCloseActionView,
    SupplyListingDetailView,
    SupplyListingListCreateView,
)

app_name = "trade_hub"

urlpatterns = [
    path(
        "rfqs/",
        RFQListCreateView.as_view(),
        name="rfq-list-create",
    ),
    path(
        "rfqs/<uuid:rfq_id>/",
        RFQDetailView.as_view(),
        name="rfq-detail",
    ),
    path(
        "rfqs/<uuid:rfq_id>/publish/",
        RFQPublishActionView.as_view(),
        name="rfq-publish",
    ),
    path(
        "rfqs/<uuid:rfq_id>/close/",
        RFQCloseActionView.as_view(),
        name="rfq-close",
    ),
    path(
        "rfqs/<uuid:rfq_id>/cancel/",
        RFQCancelActionView.as_view(),
        name="rfq-cancel",
    ),
    path(
        "rfqs/<uuid:rfq_id>/activity/",
        RFQActivityView.as_view(),
        name="rfq-activity",
    ),
    path(
        "rfqs/<uuid:rfq_id>/invitations/",
        RFQInvitationListCreateView.as_view(),
        name="rfq-invitation-list-create",
    ),
    path(
        "rfqs/<uuid:rfq_id>/invitations/me/",
        RFQInvitationMeView.as_view(),
        name="rfq-invitation-me",
    ),
    path(
        "rfqs/<uuid:rfq_id>/invitations/<uuid:invitation_id>/",
        RFQInvitationDetailView.as_view(),
        name="rfq-invitation-detail",
    ),
    path(
        "rfqs/<uuid:rfq_id>/invitations/<uuid:invitation_id>/view/",
        RFQInvitationViewActionView.as_view(),
        name="rfq-invitation-view",
    ),
    path(
        "rfqs/<uuid:rfq_id>/invitations/<uuid:invitation_id>/decline/",
        RFQInvitationDeclineActionView.as_view(),
        name="rfq-invitation-decline",
    ),
    path(
        "supply-listings/",
        SupplyListingListCreateView.as_view(),
        name="supply-listing-list-create",
    ),
    path(
        "supply-listings/<uuid:listing_id>/",
        SupplyListingDetailView.as_view(),
        name="supply-listing-detail",
    ),
    path(
        "supply-listings/<uuid:listing_id>/activate/",
        SupplyListingActivateActionView.as_view(),
        name="supply-listing-activate",
    ),
    path(
        "supply-listings/<uuid:listing_id>/close/",
        SupplyListingCloseActionView.as_view(),
        name="supply-listing-close",
    ),
]
