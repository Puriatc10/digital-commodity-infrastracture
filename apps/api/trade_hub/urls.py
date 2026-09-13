from django.urls import path

from trade_hub.api.views_invitation import (
    RFQInvitationDeclineActionView,
    RFQInvitationDetailView,
    RFQInvitationListCreateView,
    RFQInvitationMeView,
    RFQInvitationViewActionView,
)

app_name = "trade_hub"

urlpatterns = [
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
