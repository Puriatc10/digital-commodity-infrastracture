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
]
