from dataclasses import FrozenInstanceError
from decimal import Decimal
import inspect
import uuid

from offers.api.serializers import NormalizedOfferVersionResponseSerializer
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import OfferNormalizationError, OfferVersionNotFoundError
from offers.models import OfferVersion
from offers.services.creation import create_offer
from offers.services.normalization import (
    DEFAULT_NORMALIZATION_POLICY_VERSION,
    NormalizedOfferVersion,
    normalize_offer_version,
)
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.version_services import create_draft_offer_version
from offers.tests.base import BaseOffersTestCase


class OfferNormalizationArithmeticTests(BaseOffersTestCase):
    """
    Tests for exact Decimal product cost arithmetic, partial quantities, and surplus.
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_decimal_product_cost_exact_arithmetic(self):
        """Exact Decimal calculation for unit_price * offered_quantity (no float artifacts)."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("123.456"),
            quantity_unit="MT",
            unit_price=Decimal("456.78"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        # 123.456 * 456.78 = 56392.23168 -> quantized to 56392.23
        expected_product_cost = Decimal("56392.23")
        self.assertEqual(res.product_cost, expected_product_cost)
        self.assertEqual(res.known_cost_total, expected_product_cost)
        self.assertEqual(res.landed_cost, expected_product_cost)
        # landed_unit_cost = 56392.23 / 123.456 = 456.7800... -> 456.78
        self.assertEqual(res.landed_unit_cost, Decimal("456.78"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())
        self.assertEqual(res.currency, "USD")
        self.assertEqual(res.policy_version, DEFAULT_NORMALIZATION_POLICY_VERSION)

    def test_partial_quantity_uses_offered_not_rfq_quantity(self):
        """Partial quantity offer uses offered_quantity, never RFQ requested quantity."""
        # RFQ requested quantity is 500.000 MT
        self.assertEqual(self.published_rfq.quantity, Decimal("500.000"))

        # Offer offers 200.000 MT (partial quantity)
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("300.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        # Must be 200 * 300 = 60000.00, NOT 500 * 300 = 150000.00
        self.assertEqual(res.product_cost, Decimal("60000.00"))
        self.assertNotEqual(res.product_cost, Decimal("150000.00"))
        self.assertEqual(res.landed_cost, Decimal("60000.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("300.00"))

    def test_surplus_quantity_uncapped(self):
        """Surplus quantity offer is never capped to RFQ requested quantity."""
        # RFQ requested quantity is 500.000 MT
        # Offer offers 800.000 MT (surplus)
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("800.000"),
            quantity_unit="MT",
            unit_price=Decimal("250.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        # Must be 800 * 250 = 200000.00, NOT 500 * 250 = 125000.00
        self.assertEqual(res.product_cost, Decimal("200000.00"))
        self.assertNotEqual(res.product_cost, Decimal("125000.00"))
        self.assertEqual(res.landed_cost, Decimal("200000.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("250.00"))


class OfferNormalizationLogisticsSemanticsTests(BaseOffersTestCase):
    """
    Tests for KNOWN_SEPARATE, INCLUDED_IN_PRICE, NOT_APPLICABLE, and UNKNOWN semantics.
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_known_separate_logistics_addition(self):
        """KNOWN_SEPARATE correctly adds explicit logistics amount."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("35.50"),
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        # product_cost = 100 * 400 = 40000.00
        # known_cost_total = 40000.00 + 35.50 = 40035.50
        # landed_cost = 40035.50
        # landed_unit_cost = 40035.50 / 100 = 400.36 (rounded)
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40035.50"))
        self.assertEqual(res.landed_cost, Decimal("40035.50"))
        self.assertEqual(res.landed_unit_cost, Decimal("400.36"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())

    def test_included_in_price_known_zero_extra_cost(self):
        """INCLUDED_IN_PRICE represents known zero extra cost and is complete."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40000.00"))
        self.assertEqual(res.landed_cost, Decimal("40000.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("400.00"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())

    def test_not_applicable_known_zero_extra_cost(self):
        """NOT_APPLICABLE represents known zero extra cost with distinct semantic state."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            incoterm="EXW",
            logistics_cost_status=LogisticsCostStatus.NOT_APPLICABLE,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40000.00"))
        self.assertEqual(res.landed_cost, Decimal("40000.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("400.00"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())

    def test_unknown_logistics_yields_no_landed_cost_or_unit_cost(self):
        """UNKNOWN logistics leaves landed_cost and landed_unit_cost as None and records missing component."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
            specifications={"penetration_grade": "60/70"},
        )

        res = normalize_offer_version(version)
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40000.00"))
        self.assertIsNone(res.landed_cost)
        self.assertIsNone(res.landed_unit_cost)
        self.assertFalse(res.normalization_complete)
        self.assertEqual(res.missing_components, ("LOGISTICS",))

    def test_unknown_is_not_known_zero_p0_invariant(self):
        """
        P0 Invariant: UNKNOWN is strictly distinct from KNOWN ZERO.
        UNKNOWN does not substitute 0.00 and does not produce landed_cost.
        """
        # Offer A: INCLUDED_IN_PRICE (known zero extra cost)
        version_included = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )
        res_included = normalize_offer_version(version_included)

        # Offer B: In-memory copy with UNKNOWN logistics
        version_unknown = OfferVersion(
            offer=self.offer,
            version_number=2,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
            logistics_cost_amount=None,
        )
        res_unknown = normalize_offer_version(version_unknown)

        # Both have the same product_cost
        self.assertEqual(res_included.product_cost, res_unknown.product_cost)

        # But UNKNOWN produces None for landed_cost and landed_unit_cost
        self.assertIsNotNone(res_included.landed_cost)
        self.assertIsNone(res_unknown.landed_cost)

        self.assertIsNotNone(res_included.landed_unit_cost)
        self.assertIsNone(res_unknown.landed_unit_cost)

        # Incompleteness vs Completeness
        self.assertTrue(res_included.normalization_complete)
        self.assertFalse(res_unknown.normalization_complete)

        # Missing components
        self.assertEqual(res_included.missing_components, ())
        self.assertEqual(res_unknown.missing_components, ("LOGISTICS",))


class OfferNormalizationCostComponentsTests(BaseOffersTestCase):
    """
    Tests for OfferCostComponent summation, child logistics, and mixed currency rejection.
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_other_cost_components_summed_correctly(self):
        """OTHER cost components are summed into known_cost_total and landed_cost."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("20.00"),
            specifications={"penetration_grade": "60/70"},
            cost_components=[
                {
                    "kind": CostComponentKind.OTHER,
                    "amount": Decimal("15.00"),
                    "currency": "USD",
                    "description": "Port handling fee",
                },
                {
                    "kind": CostComponentKind.OTHER,
                    "amount": Decimal("10.50"),
                    "currency": "USD",
                    "description": "Inspection fee",
                },
            ],
        )

        res = normalize_offer_version(version)
        # product_cost = 40000.00
        # logistics = 20.00
        # other = 15.00 + 10.50 = 25.50
        # known_cost_total = landed_cost = 40000.00 + 20.00 + 25.50 = 40045.50
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40045.50"))
        self.assertEqual(res.landed_cost, Decimal("40045.50"))
        self.assertEqual(res.landed_unit_cost, Decimal("400.46"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())

    def test_other_components_with_unknown_logistics(self):
        """OTHER components are known even when logistics is UNKNOWN (known_cost_total exists, landed_cost is None)."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
            specifications={"penetration_grade": "60/70"},
            cost_components=[
                {
                    "kind": CostComponentKind.OTHER,
                    "amount": Decimal("50.00"),
                    "currency": "USD",
                    "description": "Customs documentation",
                },
            ],
        )

        res = normalize_offer_version(version)
        # product_cost = 40000.00
        # other = 50.00
        # known_cost_total = 40050.00
        # landed_cost = None (logistics is UNKNOWN)
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40050.00"))
        self.assertIsNone(res.landed_cost)
        self.assertIsNone(res.landed_unit_cost)
        self.assertFalse(res.normalization_complete)
        self.assertEqual(res.missing_components, ("LOGISTICS",))

    def test_child_logistics_component_summed_when_known_separate(self):
        """Child LOGISTICS component is summed with logistics_cost_amount when KNOWN_SEPARATE."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("30.00"),
            specifications={"penetration_grade": "60/70"},
            cost_components=[
                {
                    "kind": CostComponentKind.LOGISTICS,
                    "amount": Decimal("10.00"),
                    "currency": "USD",
                    "description": "Additional inland freight",
                },
            ],
        )

        res = normalize_offer_version(version)
        # product_cost = 40000.00
        # logistics = 30.00 + 10.00 = 40.00
        # known_cost_total = landed_cost = 40040.00
        self.assertEqual(res.product_cost, Decimal("40000.00"))
        self.assertEqual(res.known_cost_total, Decimal("40040.00"))
        self.assertEqual(res.landed_cost, Decimal("40040.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("400.40"))
        self.assertTrue(res.normalization_complete)

    def test_child_logistics_component_rejected_when_not_known_separate(self):
        """Child LOGISTICS component is rejected when status is INCLUDED_IN_PRICE or UNKNOWN."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        # Attempting to normalize with an extra child logistics component when status is INCLUDED_IN_PRICE
        with self.assertRaises(OfferNormalizationError) as ctx:
            normalize_offer_version(
                version,
                cost_components=[
                    {
                        "kind": CostComponentKind.LOGISTICS,
                        "amount": Decimal("10.00"),
                        "currency": "USD",
                    }
                ],
            )
        self.assertIn("Child LOGISTICS cost components cannot be specified", str(ctx.exception))

    def test_mismatched_child_component_currency_rejected(self):
        """Child cost component currency mismatching OfferVersion currency is strictly rejected."""
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("30.00"),
            specifications={"penetration_grade": "60/70"},
        )

        with self.assertRaises(OfferNormalizationError) as ctx:
            normalize_offer_version(
                version,
                cost_components=[
                    {
                        "kind": CostComponentKind.OTHER,
                        "amount": Decimal("10.00"),
                        "currency": "EUR",  # mismatch with USD
                    }
                ],
            )
        self.assertIn("does not match OfferVersion currency", str(ctx.exception))


class OfferNormalizationCurrencyAndIncotermTests(BaseOffersTestCase):
    """
    Tests verifying cross-currency independence (no FX) and Incoterm neutrality.
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_cross_currency_separate_normalization_no_fx(self):
        """USD Offer and EUR Offer normalize separately; currency is preserved with no FX conversion."""
        version_usd = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )
        res_usd = normalize_offer_version(version_usd)
        self.assertEqual(res_usd.currency, "USD")
        self.assertEqual(res_usd.product_cost, Decimal("40000.00"))

        version_eur = OfferVersion(
            offer=self.offer,
            version_number=2,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("380.00"),
            currency="EUR",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        res_eur = normalize_offer_version(version_eur)
        self.assertEqual(res_eur.currency, "EUR")
        self.assertEqual(res_eur.product_cost, Decimal("38000.00"))

        # No FX or base conversion occurred
        self.assertNotEqual(res_usd.currency, res_eur.currency)

    def test_incoterm_does_not_infer_freight(self):
        """Incoterm is preserved as source context only and never used to infer logistics costs."""
        # Incoterm FOB with UNKNOWN logistics remains UNKNOWN
        version_fob = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            incoterm="FOB",
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
            specifications={"penetration_grade": "60/70"},
        )
        res_fob = normalize_offer_version(version_fob)
        self.assertIsNone(res_fob.landed_cost)
        self.assertEqual(res_fob.missing_components, ("LOGISTICS",))

        # Incoterm CIF with UNKNOWN logistics also remains UNKNOWN (no automatic assumption)
        version_cif = OfferVersion(
            offer=self.offer,
            version_number=2,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            incoterm="CIF",
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
        )
        res_cif = normalize_offer_version(version_cif)
        self.assertIsNone(res_cif.landed_cost)
        self.assertEqual(res_cif.missing_components, ("LOGISTICS",))


class OfferNormalizationDeterminismAndImmutabilityTests(BaseOffersTestCase):
    """
    Tests verifying determinism, OfferVersion immutability, and value object freeze.
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("375.50"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("45.00"),
            specifications={"penetration_grade": "60/70"},
        )

    def test_normalization_determinism(self):
        """Repeated normalisations with identical inputs produce identical NormalizedOfferVersion results."""
        first_run = normalize_offer_version(self.version)
        for _ in range(10):
            repeated = normalize_offer_version(self.version)
            self.assertEqual(first_run, repeated)

    def test_offer_version_unmutated_after_normalization(self):
        """OfferVersion model and database state remain completely unmutated by normalisation."""
        initial_updated_at = self.version.updated_at
        initial_status = self.version.status
        initial_price = self.version.unit_price

        normalize_offer_version(self.version)

        self.version.refresh_from_db()
        self.assertEqual(self.version.updated_at, initial_updated_at)
        self.assertEqual(self.version.status, initial_status)
        self.assertEqual(self.version.unit_price, initial_price)

    def test_normalized_result_is_frozen_and_immutable(self):
        """NormalizedOfferVersion dataclass is frozen and rejects attribute mutation."""
        res = normalize_offer_version(self.version)
        with self.assertRaises(FrozenInstanceError):
            res.product_cost = Decimal("999.99")


class OfferNormalizationHistoricalExternalOfferTests(BaseOffersTestCase):
    """
    Regression test verifying Operator-entered ExternalCounterparty OfferVersion (T0804)
    normalizes identically to internal Supplier/Broker offers without special branches.
    """

    def test_operator_external_offer_normalizes_identically(self):
        """External counterparty offer submitted by Operator uses the identical normalisation path."""
        offer, submitted_version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("420.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("50.00"),
            specifications={"penetration_grade": "60/70"},
            notes="External counterparty quote entered by operator",
        )

        self.assertTrue(offer.is_external)
        self.assertTrue(offer.entered_by_operator)
        self.assertEqual(submitted_version.status, OfferVersionStatus.SUBMITTED)

        res = normalize_offer_version(submitted_version)

        # 300 * 420 = 126000.00
        # logistics = 50.00
        # landed_cost = 126050.00
        # landed_unit_cost = 126050 / 300 = 420.17
        self.assertEqual(res.product_cost, Decimal("126000.00"))
        self.assertEqual(res.known_cost_total, Decimal("126050.00"))
        self.assertEqual(res.landed_cost, Decimal("126050.00"))
        self.assertEqual(res.landed_unit_cost, Decimal("420.17"))
        self.assertTrue(res.normalization_complete)
        self.assertEqual(res.missing_components, ())
        self.assertEqual(res.currency, "USD")
        self.assertEqual(res.policy_version, "v1")


class OfferNormalizationCodeAuditTests(BaseOffersTestCase):
    """
    Audit tests verifying commodity neutrality, policy versioning, and serialization roundtrip.
    """

    def test_no_commodity_specific_branches(self):
        """Normalization engine source code contains zero commodity codes or dynamic attribute keys."""
        import offers.services.normalization as norm_module

        source_code = inspect.getsource(norm_module).lower()
        forbidden_terms = ["bitumen", "penetration_grade", "viscosity", "crude", "steel", "polymer"]
        for term in forbidden_terms:
            self.assertNotIn(
                term,
                source_code,
                f"Normalization engine must be commodity-agnostic; found forbidden term '{term}'.",
            )

    def test_policy_version_validation(self):
        """Unsupported policy version is rejected with OfferNormalizationError."""
        version = OfferVersion(
            offered_quantity=Decimal("100.000"),
            unit_price=Decimal("10.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        with self.assertRaises(OfferNormalizationError) as ctx:
            normalize_offer_version(version, policy_version="v99")
        self.assertIn("Unsupported normalisation policy version 'v99'", str(ctx.exception))

    def test_serializer_roundtrip(self):
        """NormalizedOfferVersionResponseSerializer correctly serializes NormalizedOfferVersion."""
        norm_result = NormalizedOfferVersion(
            product_cost=Decimal("12345.67"),
            known_cost_total=Decimal("12395.67"),
            landed_cost=Decimal("12395.67"),
            landed_unit_cost=Decimal("123.96"),
            normalization_complete=True,
            missing_components=(),
            currency="USD",
            policy_version="v1",
        )
        serializer = NormalizedOfferVersionResponseSerializer(norm_result)
        data = serializer.data
        self.assertEqual(data["product_cost"], "12345.67")
        self.assertEqual(data["known_cost_total"], "12395.67")
        self.assertEqual(data["landed_cost"], "12395.67")
        self.assertEqual(data["landed_unit_cost"], "123.96")
        self.assertTrue(data["normalization_complete"])
        self.assertEqual(data["missing_components"], [])
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["policy_version"], "v1")

    def test_serializer_with_null_landed_cost(self):
        """NormalizedOfferVersionResponseSerializer correctly serializes incomplete normalisation."""
        norm_result = NormalizedOfferVersion(
            product_cost=Decimal("12345.67"),
            known_cost_total=Decimal("12345.67"),
            landed_cost=None,
            landed_unit_cost=None,
            normalization_complete=False,
            missing_components=("LOGISTICS",),
            currency="USD",
            policy_version="v1",
        )
        serializer = NormalizedOfferVersionResponseSerializer(norm_result)
        data = serializer.data
        self.assertIsNone(data["landed_cost"])
        self.assertIsNone(data["landed_unit_cost"])
        self.assertFalse(data["normalization_complete"])
        self.assertEqual(data["missing_components"], ["LOGISTICS"])

    def test_normalize_by_uuid_or_str(self):
        """normalize_offer_version resolves OfferVersion by UUID or str."""
        offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
        )

        res_uuid = normalize_offer_version(version.id)
        self.assertEqual(res_uuid.product_cost, Decimal("40000.00"))

        res_str = normalize_offer_version(str(version.id))
        self.assertEqual(res_str.product_cost, Decimal("40000.00"))

    def test_nonexistent_offer_version_raises_not_found(self):
        """Passing nonexistent UUID raises OfferVersionNotFoundError."""
        random_id = uuid.uuid4()
        with self.assertRaises(OfferVersionNotFoundError):
            normalize_offer_version(random_id)
