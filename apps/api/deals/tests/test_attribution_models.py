from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealAttributionResolutionMethod,
    DealAttributionStatus,
)
from deals.tests.base import BaseDealsTestCase

User = get_user_model()


class DealAttributionModelTests(BaseDealsTestCase):
    """
    Unit tests for DealAttribution model, status/channel constraints, and immutability (T0903).
    """

    def setUp(self):
        super().setUp()
        award, alloc = self.create_and_finalize_single_award()
        self.deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

    def test_attribution_pending_valid(self):
        """PENDING attribution with null primary_channel is valid."""
        attr = DealAttribution.objects.create(
            deal=self.deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            evidence_snapshot={"key": "val"},
        )
        self.assertIsNotNone(attr.id)
        self.assertEqual(attr.status, DealAttributionStatus.PENDING)
        self.assertIsNone(attr.primary_channel)
        self.assertEqual(attr.version, 1)

    def test_attribution_pending_with_primary_channel_rejected(self):
        """PENDING attribution with a non-null primary_channel violates DB check constraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealAttribution.objects.create(
                    deal=self.deal,
                    status=DealAttributionStatus.PENDING,
                    primary_channel=DealAttributionChannel.DIRECT_SUPPLIER,
                )

    def test_attribution_resolved_without_primary_channel_rejected(self):
        """RESOLVED attribution with a null primary_channel violates DB check constraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealAttribution.objects.create(
                    deal=self.deal,
                    status=DealAttributionStatus.RESOLVED,
                    primary_channel=None,
                    resolution_method=DealAttributionResolutionMethod.AUTOMATIC,
                )

    def test_attribution_resolved_valid(self):
        """RESOLVED attribution with valid channel and metadata is valid."""
        attr = DealAttribution.objects.create(
            deal=self.deal,
            status=DealAttributionStatus.RESOLVED,
            primary_channel=DealAttributionChannel.DIRECT_SUPPLIER,
            resolution_method=DealAttributionResolutionMethod.AUTOMATIC,
            resolved_at=self.deal.created_at,
            evidence_snapshot={"source": "direct"},
        )
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.primary_channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertEqual(attr.resolution_method, DealAttributionResolutionMethod.AUTOMATIC)

    def test_attribution_invalid_channel_choice_rejected(self):
        """Invalid primary_channel string violates DB constraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealAttribution.objects.create(
                    deal=self.deal,
                    status=DealAttributionStatus.RESOLVED,
                    primary_channel="INVALID_CHANNEL",
                    resolution_method=DealAttributionResolutionMethod.AUTOMATIC,
                )

    def test_attribution_cardinality_one_to_one(self):
        """Exactly one DealAttribution per Deal. Second attribution fails unique constraint."""
        DealAttribution.objects.create(
            deal=self.deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DealAttribution.objects.create(
                    deal=self.deal,
                    status=DealAttributionStatus.PENDING,
                    primary_channel=None,
                )

    def test_attribution_resolved_immutability(self):
        """Direct mutation of an already RESOLVED DealAttribution raises ValidationError."""
        attr = DealAttribution.objects.create(
            deal=self.deal,
            status=DealAttributionStatus.RESOLVED,
            primary_channel=DealAttributionChannel.DIRECT_SUPPLIER,
            resolution_method=DealAttributionResolutionMethod.AUTOMATIC,
            resolved_at=self.deal.created_at,
            evidence_snapshot={"source": "direct"},
        )
        attr.primary_channel = DealAttributionChannel.BROKER
        with self.assertRaises(ValidationError):
            attr.save()

    def test_attribution_version_positive_constraint(self):
        """Non-positive version violates DB check constraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealAttribution.objects.create(
                    deal=self.deal,
                    status=DealAttributionStatus.PENDING,
                    primary_channel=None,
                    version=0,
                )
