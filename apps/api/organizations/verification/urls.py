from django.urls import path
from . import api_views

app_name = "verification"

urlpatterns = [
    path("", api_views.VerificationDetailView.as_view(), name="detail"),
    path("submit/", api_views.VerificationSubmitView.as_view(), name="submit"),
    path("start_review/", api_views.VerificationStartReviewView.as_view(), name="start-review"),
    path("approve_basic/", api_views.VerificationApproveBasicView.as_view(), name="approve-basic"),
    path("approve_full/", api_views.VerificationApproveFullView.as_view(), name="approve-full"),
    path("reject/", api_views.VerificationRejectView.as_view(), name="reject"),
    path("suspend/", api_views.VerificationSuspendView.as_view(), name="suspend"),
    path("checklist/", api_views.VerificationChecklistView.as_view(), name="checklist-review"),
    path("reopen/", api_views.VerificationReopenView.as_view(), name="reopen"),
    path("notes/", api_views.VerificationNoteCreateView.as_view(), name="notes-create"),
]
