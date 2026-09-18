from django.urls import path

from offers.api.views import OfferVersionSubmitActionView

app_name = "offers"

urlpatterns = [
    path(
        "offer-versions/<uuid:version_id>/submit/",
        OfferVersionSubmitActionView.as_view(),
        name="offer-version-submit",
    ),
]
