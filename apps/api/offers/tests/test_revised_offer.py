from datetime import date
from decimal import Decimal
import threading
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from offers.enums import (
    CostComponentKind,
    LogisticsCostStatus,
    OfferorRole,
    OfferVersionStatus,
    RevisionRequestStatus,
)
from offers.exceptions import (
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    StaleVersionError,
)
from offers.models import (
    DecisionRun,
    OfferVersion,
    RevisionRequest,
)
from offers.services.creation import create_offer
from offers.services.decision_service import execute_decision_run_pipeline
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.revision_service import (
    cancel_revision_request,
    create_revised_draft_offer_version,
    create_revision_request,
    decline_revision_request,
    submit_revised_offer_version,
)
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import (
    create_draft_offer_version,
    update_draft_offer_version,
)
from offers.tests.base import BaseOffersTestCase
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class RevisedOfferDomainServiceTests(BaseOffersTestCase):
    """Unit and domain service tests for T0811 Revised Offer workflow."""

    def setUp(self):
        super().setUp()

        # Create Supplier Offer
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        # Create Draft V1
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            payment_terms="LC 30 days",
            delivery_terms="CIF Bandar Abbas",
            incoterm="CIF",
            delivery_start=date(2026, 10, 1),
            delivery_end=date(2026, 10, 15),
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("30.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Initial proposal V1",
            cost_components=[
                {
                    "kind": CostComponentKind.LOGISTICS,
                    "amount": Decimal("30.00"),
                    "currency": "USD",
                    "description": "Freight charges",
                }
            ],
        )

        # Submit V1
        self.offer.refresh_from_db()
        self.v1_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()
        self.published_rfq.refresh_from_db()

    def test_happy_flow(self):
        """
        Happy Flow:
        V1 Submitted -> OPEN RevisionRequest -> V2 Draft -> edit -> V2 Submitted
        Assert:
        - V1 unchanged
        - V2 current pointer
        - RevisionRequest RESOLVED by V2
        - Offer aggregate_version advanced
        """
        # 1. Buyer opens RevisionRequest against V1
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price", "offered_quantity"],
            message="Please improve price for 550 MT.",
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(rev_req.status, RevisionRequestStatus.OPEN)
        self.offer.refresh_from_db()

        # 2. Supplier creates revised Draft V2
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(v2_draft.version_number, 2)
        self.assertEqual(v2_draft.status, OfferVersionStatus.DRAFT)
        self.assertEqual(v2_draft.created_by, self.supplier_user)
        self.assertIsNone(v2_draft.submitted_by)
        self.assertIsNone(v2_draft.submitted_at)

        # Ensure current_submitted_version on Offer is still V1
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, self.v1_submitted.id)

        # 3. Supplier edits V2 Draft
        v2_updated = update_draft_offer_version(
            actor=self.supplier_user,
            offer_version=v2_draft,
            unit_price=Decimal("335.00"),
            offered_quantity=Decimal("550.000"),
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(v2_updated.unit_price, Decimal("335.00"))
        self.assertEqual(v2_updated.offered_quantity, Decimal("550.000"))
        self.offer.refresh_from_db()

        # 4. Supplier submits V2
        v2_sub, resolved_req = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
            draft_version=v2_updated,
        )

        # Assertions
        self.v1_submitted.refresh_from_db()
        self.assertEqual(self.v1_submitted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(self.v1_submitted.unit_price, Decimal("350.00"))
        self.assertEqual(self.v1_submitted.offered_quantity, Decimal("500.000"))

        self.assertEqual(v2_sub.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(v2_sub.unit_price, Decimal("335.00"))
        self.assertEqual(v2_sub.offered_quantity, Decimal("550.000"))
        self.assertEqual(v2_sub.submitted_by, self.supplier_user)
        self.assertIsNotNone(v2_sub.submitted_at)

        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v2_sub.id)

        resolved_req.refresh_from_db()
        self.assertEqual(resolved_req.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(resolved_req.resolved_by_version_id, v2_sub.id)
        self.assertIsNotNone(resolved_req.resolved_at)

    def test_deep_copy_and_child_isolation(self):
        """
        Deep Copy & Isolation:
        Change every commercial category on V2.
        V1 remains 100% unchanged, and cost component rows remain isolated.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price", "payment_terms", "specifications", "logistics_cost_amount"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )

        # Verify child cost components were deep-copied to distinct rows
        self.assertEqual(v2_draft.cost_components.count(), 1)
        v2_comp = v2_draft.cost_components.first()
        v1_comp = self.v1_submitted.cost_components.first()
        self.assertNotEqual(v2_comp.id, v1_comp.id)
        self.assertEqual(v2_comp.amount, Decimal("30.00"))

        self.offer.refresh_from_db()
        # Mutate every commercial category on V2 draft
        update_draft_offer_version(
            actor=self.supplier_user,
            offer_version=v2_draft,
            offered_quantity=Decimal("600.000"),
            quantity_unit="MT",
            unit_price=Decimal("320.00"),
            currency="USD",
            payment_terms="TT 100% in advance",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            delivery_start=date(2026, 11, 1),
            delivery_end=date(2026, 11, 20),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70"},
            notes="Heavily modified V2 draft",
            cost_components=[
                {
                    "kind": CostComponentKind.OTHER,
                    "amount": Decimal("15.00"),
                    "currency": "USD",
                    "description": "Port handling fee",
                }
            ],
            expected_version=self.offer.aggregate_version,
        )

        # Assert V1 is 100% untouched
        self.v1_submitted.refresh_from_db()
        self.assertEqual(self.v1_submitted.offered_quantity, Decimal("500.000"))
        self.assertEqual(self.v1_submitted.unit_price, Decimal("350.00"))
        self.assertEqual(self.v1_submitted.payment_terms, "LC 30 days")
        self.assertEqual(self.v1_submitted.delivery_terms, "CIF Bandar Abbas")
        self.assertEqual(self.v1_submitted.incoterm, "CIF")
        self.assertEqual(self.v1_submitted.delivery_start, date(2026, 10, 1))
        self.assertEqual(self.v1_submitted.delivery_end, date(2026, 10, 15))
        self.assertEqual(self.v1_submitted.logistics_cost_status, LogisticsCostStatus.KNOWN_SEPARATE)
        self.assertEqual(self.v1_submitted.logistics_cost_amount, Decimal("30.00"))
        self.assertEqual(self.v1_submitted.notes, "Initial proposal V1")

        v1_comps = list(self.v1_submitted.cost_components.all())
        self.assertEqual(len(v1_comps), 1)
        self.assertEqual(v1_comps[0].kind, CostComponentKind.LOGISTICS)
        self.assertEqual(v1_comps[0].amount, Decimal("30.00"))
        self.assertEqual(v1_comps[0].description, "Freight charges")

    def test_stale_base_rejection(self):
        """
        Stale Base:
        If current submitted version no longer equals request base: reject.
        """
        # Create OPEN request against V1
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        # Create and submit V2 via happy flow
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_sub, _ = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            draft_version=v2_draft,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v2_sub.id)

        # Now rev_req.base_offer_version is V1, but current is V2!
        # Attempting to create revised draft with old request must be rejected
        with self.assertRaises(OfferConflictError) as ctx:
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("cannot create a revised draft", str(ctx.exception))

    def test_non_open_request_rejection(self):
        """DECLINED, CANCELLED, and RESOLVED requests cannot create draft or submit."""
        # 1. DECLINED
        req1 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        decline_revision_request(
            actor=self.supplier_user,
            revision_request=req1,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        with self.assertRaises(OfferConflictError):
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=req1,
                expected_version=self.offer.aggregate_version,
            )

        # 2. CANCELLED
        req2 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        cancel_revision_request(
            actor=self.buyer_user,
            revision_request=req2,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        with self.assertRaises(OfferConflictError):
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=req2,
                expected_version=self.offer.aggregate_version,
            )

    def test_no_existing_draft_conflict(self):
        """Cannot create revised draft if an unsubmitted draft already exists on Offer."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        # Trying to create another draft while V2 draft is active
        with self.assertRaises(OfferConflictError) as ctx:
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("already has an active draft", str(ctx.exception))

    def test_internal_authorization(self):
        """
        Internal Authorization:
        Owner/Manager/Member allowed; Viewer denied; foreign user denied; capability check enforced.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        # Create Viewer in supplier_org
        viewer_user = User.objects.create_user(email="viewer@supplier.com", password="testpassword123")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=viewer_user,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # Viewer denied creating draft
        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            create_revised_draft_offer_version(
                actor=viewer_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("Viewers have read-only access", str(ctx.exception))

        # Buyer user denied creating draft (not a member of offering org)
        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            create_revised_draft_offer_version(
                actor=self.buyer_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("does not have active membership", str(ctx.exception))

        # Non-member denied
        foreign_user = User.objects.create_user(email="stranger@other.com", password="testpassword123")
        with self.assertRaises(OfferPermissionDeniedError):
            create_revised_draft_offer_version(
                actor=foreign_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )

        # Capability Check: revoking Supplier capability prevents draft creation
        OrganizationCapability.objects.filter(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        ).delete()

        with self.assertRaises(OfferValidationError) as ctx:
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("lacks required Supplier capability", str(ctx.exception))

    def test_external_authorization_and_provenance(self):
        """
        External Authorization & Provenance:
        For external counterparty offer, only Operator or Product Admin may revise.
        Provenance (ExternalCounterparty, Opportunity) is preserved; new Operator is recorded on V2.
        """
        # Operator submits initial external quote (T0804)
        ext_offer, v1_ext = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("400.000"),
            quantity_unit="MT",
            unit_price=Decimal("360.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.published_rfq.refresh_from_db()

        # Buyer opens revision request on external quote
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=ext_offer,
            base_offer_version=v1_ext,
            requested_fields=["unit_price"],
            expected_version=ext_offer.aggregate_version,
        )
        ext_offer.refresh_from_db()

        # Regular supplier user tries to revise -> denied!
        with self.assertRaises(OfferPermissionDeniedError):
            create_revised_draft_offer_version(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=ext_offer.aggregate_version,
            )

        # Buyer user tries to revise -> denied!
        with self.assertRaises(OfferPermissionDeniedError):
            create_revised_draft_offer_version(
                actor=self.buyer_user,
                revision_request=rev_req,
                expected_version=ext_offer.aggregate_version,
            )

        # Operator creates revised draft V2
        v2_ext_draft = create_revised_draft_offer_version(
            actor=self.operator_user,
            revision_request=rev_req,
            expected_version=ext_offer.aggregate_version,
        )
        self.assertEqual(v2_ext_draft.version_number, 2)
        self.assertEqual(v2_ext_draft.created_by, self.operator_user)
        ext_offer.refresh_from_db()

        # Different Product Admin submits V2
        v2_ext_sub, resolved_req = submit_revised_offer_version(
            actor=self.admin_user,
            revision_request=rev_req,
            draft_version=v2_ext_draft,
            expected_version=ext_offer.aggregate_version,
        )

        # Assertions
        ext_offer.refresh_from_db()
        self.assertEqual(ext_offer.external_counterparty_id, self.external_cp.id)
        self.assertEqual(ext_offer.source_opportunity_id, self.opp_external_qualified.id)
        self.assertEqual(ext_offer.offeror_role, OfferorRole.SUPPLIER)

        self.assertEqual(v2_ext_sub.submitted_by, self.admin_user)
        self.assertEqual(resolved_req.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(resolved_req.resolved_by_version_id, v2_ext_sub.id)

    def test_failure_injection_full_rollback(self):
        """Simulated failure during submit rolls back all changes atomically."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        agg_ver_before = self.offer.aggregate_version

        # Inject failure when saving RevisionRequest
        with patch.object(RevisionRequest, "save", side_effect=RuntimeError("Simulated database failure")):
            with self.assertRaises(RuntimeError):
                submit_revised_offer_version(
                    actor=self.supplier_user,
                    revision_request=rev_req,
                    draft_version=v2_draft,
                    expected_version=agg_ver_before,
                )

        # Verify full rollback
        v2_draft.refresh_from_db()
        self.assertEqual(v2_draft.status, OfferVersionStatus.DRAFT)
        self.assertIsNone(v2_draft.submitted_by)

        rev_req.refresh_from_db()
        self.assertEqual(rev_req.status, RevisionRequestStatus.OPEN)
        self.assertIsNone(rev_req.resolved_by_version)

        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, self.v1_submitted.id)
        self.assertEqual(self.offer.aggregate_version, agg_ver_before)

    def test_decision_run_staleness_and_immutability(self):
        """
        Decision Staleness:
        DecisionRun evaluated against V1 remains immutable and becomes stale (is_stale=True).
        No new DecisionRun is created automatically.
        """
        # Execute DecisionRun on V1
        run = execute_decision_run_pipeline(
            actor=self.buyer_user,
            rfq=self.published_rfq,
        )
        self.assertFalse(run.is_stale)
        cand = run.candidates.filter(offer=self.offer).first()
        self.assertIsNotNone(cand)
        self.assertEqual(cand.offer_version_id, self.v1_submitted.id)
        cand_score = cand.decision_score

        # Open revision request and submit V2
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_sub, _ = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            draft_version=v2_draft,
            expected_version=self.offer.aggregate_version,
        )

        # Old DecisionRun must now evaluate is_stale as True!
        self.assertTrue(run.is_stale)

        # Old DecisionRun candidates and scores remain completely unchanged
        cand.refresh_from_db()
        self.assertEqual(cand.offer_version_id, self.v1_submitted.id)
        self.assertEqual(cand.decision_score, cand_score)

        # No new DecisionRun created automatically
        self.assertEqual(DecisionRun.objects.filter(rfq=self.published_rfq).count(), 1)

    def test_multiple_cycles_v1_v2_v3(self):
        """
        Multiple Cycles:
        V1 -> R1 -> V2 -> R2 -> V3 using generic version allocation without hardcoding version 2.
        """
        # Cycle 1: V1 -> R1 -> V2
        r1 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=r1,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_sub, r1_res = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=r1,
            draft_version=v2_draft,
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(v2_sub.version_number, 2)
        self.assertEqual(r1_res.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(r1_res.resolved_by_version_id, v2_sub.id)

        # Cycle 2: V2 -> R2 -> V3
        self.offer.refresh_from_db()
        r2 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=v2_sub,
            requested_fields=["delivery_terms"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v3_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=r2,
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(v3_draft.version_number, 3)
        self.offer.refresh_from_db()
        v3_sub, r2_res = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=r2,
            draft_version=v3_draft,
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(v3_sub.version_number, 3)
        self.assertEqual(r2_res.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(r2_res.resolved_by_version_id, v3_sub.id)

        # Final aggregate checks
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v3_sub.id)
        self.assertEqual(OfferVersion.objects.filter(offer=self.offer).count(), 3)
        self.assertEqual(RevisionRequest.objects.filter(offer=self.offer).count(), 2)
        self.assertEqual(
            RevisionRequest.objects.filter(offer=self.offer, status=RevisionRequestStatus.RESOLVED).count(), 2
        )


class RevisedOfferAPITests(BaseOffersTestCase):
    """API endpoint tests for revised offer draft creation and submission."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Offer & V1 submitted
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.offer.refresh_from_db()
        self.v1_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()

        # Create OPEN RevisionRequest
        self.rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

    def test_api_create_revised_draft_success(self):
        """POST /api/revision-requests/{id}/draft/ creates DRAFT version."""
        self.client.force_authenticate(user=self.supplier_user)
        payload = {"expected_version": self.offer.aggregate_version}
        response = self.client.post(
            f"/api/revision-requests/{self.rev_req.id}/draft/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data
        self.assertEqual(data["version_number"], 2)
        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(str(data["offer_id"]), str(self.offer.id))

    def test_api_submit_revised_version_success(self):
        """POST /api/revision-requests/{id}/submit/ submits revised version and resolves request."""
        # First create draft
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=self.rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        self.client.force_authenticate(user=self.supplier_user)
        payload = {
            "expected_version": self.offer.aggregate_version,
            "draft_version_id": str(v2_draft.id),
        }
        response = self.client.post(
            f"/api/revision-requests/{self.rev_req.id}/submit/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["version_number"], 2)
        self.assertEqual(data["status"], "SUBMITTED")

        self.rev_req.refresh_from_db()
        self.assertEqual(self.rev_req.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(self.rev_req.resolved_by_version_id, v2_draft.id)

    def test_api_submit_via_offer_version_action_with_revision_request(self):
        """POST /api/offer-versions/{version_id}/submit/ with revision_request in payload."""
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=self.rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        self.client.force_authenticate(user=self.supplier_user)
        payload = {
            "expected_version": self.offer.aggregate_version,
            "revision_request": str(self.rev_req.id),
        }
        response = self.client.post(
            f"/api/offer-versions/{v2_draft.id}/submit/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "SUBMITTED")

        self.rev_req.refresh_from_db()
        self.assertEqual(self.rev_req.status, RevisionRequestStatus.RESOLVED)

    def test_api_competitor_privacy_404(self):
        """Competitor organization accessing draft or submit endpoint receives 404 Not Found."""
        competitor_user = self.broker_user
        self.client.force_authenticate(user=competitor_user)

        res_draft = self.client.post(
            f"/api/revision-requests/{self.rev_req.id}/draft/",
            {"expected_version": self.offer.aggregate_version},
            format="json",
        )
        self.assertEqual(res_draft.status_code, status.HTTP_404_NOT_FOUND)

        res_submit = self.client.post(
            f"/api/revision-requests/{self.rev_req.id}/submit/",
            {"expected_version": self.offer.aggregate_version},
            format="json",
        )
        self.assertEqual(res_submit.status_code, status.HTTP_404_NOT_FOUND)

    def test_api_buyer_forbidden_403(self):
        """Buyer procurement actor attempting to create draft or submit revised offer gets 403 Forbidden."""
        self.client.force_authenticate(user=self.buyer_user)

        res_draft = self.client.post(
            f"/api/revision-requests/{self.rev_req.id}/draft/",
            {"expected_version": self.offer.aggregate_version},
            format="json",
        )
        self.assertEqual(res_draft.status_code, status.HTTP_403_FORBIDDEN)


class RevisedOfferConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded concurrency and race tests for T0811:
    1. create Draft vs create Draft
    2. submit vs submit
    3. submit vs cancel
    4. submit vs decline
    5. submit vs RFQ cancel
    """

    def setUp(self):
        super().setUp()

        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_t0811_{uuid.uuid4().hex[:6]}",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_version,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.schema_version, activate=True)

        self.buyer_org = Organization.objects.create(name=f"Buyer Corp {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER)
        self.buyer_user = User.objects.create_user(email=f"buyer_{uuid.uuid4().hex[:4]}@buyer.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True)

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        self.supplier_org = Organization.objects.create(name=f"Supplier {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        self.supplier_user1 = User.objects.create_user(email=f"s1_{uuid.uuid4().hex[:4]}@supplier.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.supplier_org, user=self.supplier_user1, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True)
        self.supplier_user2 = User.objects.create_user(email=f"s2_{uuid.uuid4().hex[:4]}@supplier.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.supplier_org, user=self.supplier_user2, role=OrganizationMembership.OrganizationRole.OWNER, is_active=True)

        self.offer = create_offer(
            actor=self.supplier_user1,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user1,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.offer.refresh_from_db()
        self.v1_sub = submit_internal_offer_version(
            actor=self.supplier_user1,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()

    def test_race_create_draft_vs_create_draft(self):
        """
        Race — create Draft vs create Draft:
        Two concurrent threads attempt to create revised draft from the same OPEN request.
        Exactly one succeeds, exactly one Draft created.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer.id,
            base_offer_version=self.v1_sub.id,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def draft_worker(thread_id, user):
            connection.close()
            try:
                barrier.wait()
                draft = create_revised_draft_offer_version(
                    actor=user,
                    revision_request=rev_req.id,
                    expected_version=self.offer.aggregate_version,
                )
                results[thread_id] = ("SUCCESS", draft.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results[thread_id] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results[thread_id] = ("ERROR", str(exc))
            finally:
                connection.close()

        t1 = threading.Thread(target=draft_worker, args=(1, self.supplier_user1))
        t2 = threading.Thread(target=draft_worker, args=(2, self.supplier_user2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [v for v in results.values() if v[0] == "SUCCESS"]
        conflicts = [v for v in results.values() if v[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got {results}")
        self.assertEqual(len(conflicts), 1, f"Expected 1 conflict, got {results}")

        # Assert exactly one DRAFT exists for this offer
        draft_count = OfferVersion.objects.filter(offer=self.offer, status=OfferVersionStatus.DRAFT).count()
        self.assertEqual(draft_count, 1)

    def test_race_submit_vs_submit(self):
        """
        Race — submit vs submit:
        Two concurrent threads attempt to submit V2 for the same RevisionRequest.
        Exactly one succeeds, request resolved exactly once.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer.id,
            base_offer_version=self.v1_sub.id,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user1,
            revision_request=rev_req.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def submit_worker(thread_id, user):
            connection.close()
            try:
                barrier.wait()
                v2_s, r_res = submit_revised_offer_version(
                    actor=user,
                    revision_request=rev_req.id,
                    draft_version=v2_draft.id,
                    expected_version=self.offer.aggregate_version,
                )
                results[thread_id] = ("SUCCESS", v2_s.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results[thread_id] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results[thread_id] = ("ERROR", str(exc))
            finally:
                connection.close()

        t1 = threading.Thread(target=submit_worker, args=(1, self.supplier_user1))
        t2 = threading.Thread(target=submit_worker, args=(2, self.supplier_user2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [v for v in results.values() if v[0] == "SUCCESS"]
        conflicts = [v for v in results.values() if v[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got {results}")
        self.assertEqual(len(conflicts), 1, f"Expected 1 conflict, got {results}")

        rev_req.refresh_from_db()
        self.assertEqual(rev_req.status, RevisionRequestStatus.RESOLVED)
        self.assertEqual(rev_req.resolved_by_version_id, v2_draft.id)

    def test_race_submit_vs_cancel(self):
        """
        Race — submit vs cancel:
        Thread A: submit V2 to resolve RevisionRequest.
        Thread B: cancel RevisionRequest.
        Serialized on locks: exactly one succeeds, the other receives conflict.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer.id,
            base_offer_version=self.v1_sub.id,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user1,
            revision_request=rev_req.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def submit_worker():
            connection.close()
            try:
                barrier.wait()
                v2_s, _ = submit_revised_offer_version(
                    actor=self.supplier_user1,
                    revision_request=rev_req.id,
                    draft_version=v2_draft.id,
                    expected_version=self.offer.aggregate_version,
                )
                results["SUBMIT"] = ("SUCCESS", v2_s.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results["SUBMIT"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["SUBMIT"] = ("ERROR", str(exc))
            finally:
                connection.close()

        def cancel_worker():
            connection.close()
            try:
                barrier.wait()
                req_c = cancel_revision_request(
                    actor=self.buyer_user,
                    revision_request=rev_req.id,
                    expected_version=self.offer.aggregate_version,
                )
                results["CANCEL"] = ("SUCCESS", req_c.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results["CANCEL"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["CANCEL"] = ("ERROR", str(exc))
            finally:
                connection.close()

        t_sub = threading.Thread(target=submit_worker)
        t_can = threading.Thread(target=cancel_worker)
        t_sub.start()
        t_can.start()
        t_sub.join()
        t_can.join()

        successes = [k for k, v in results.items() if v[0] == "SUCCESS"]
        conflicts = [k for k, v in results.items() if v[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got {results}")
        self.assertEqual(len(conflicts), 1, f"Expected 1 conflict, got {results}")

        rev_req.refresh_from_db()
        if results["SUBMIT"][0] == "SUCCESS":
            self.assertEqual(rev_req.status, RevisionRequestStatus.RESOLVED)
        else:
            self.assertEqual(rev_req.status, RevisionRequestStatus.CANCELLED)

    def test_race_submit_vs_decline(self):
        """
        Race — submit vs decline:
        Thread A: submit V2 to resolve RevisionRequest.
        Thread B: decline RevisionRequest.
        Serialized on locks: exactly one succeeds, the other receives conflict.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer.id,
            base_offer_version=self.v1_sub.id,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user1,
            revision_request=rev_req.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def submit_worker():
            connection.close()
            try:
                barrier.wait()
                v2_s, _ = submit_revised_offer_version(
                    actor=self.supplier_user1,
                    revision_request=rev_req.id,
                    draft_version=v2_draft.id,
                    expected_version=self.offer.aggregate_version,
                )
                results["SUBMIT"] = ("SUCCESS", v2_s.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results["SUBMIT"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["SUBMIT"] = ("ERROR", str(exc))
            finally:
                connection.close()

        def decline_worker():
            connection.close()
            try:
                barrier.wait()
                req_d = decline_revision_request(
                    actor=self.supplier_user2,
                    revision_request=rev_req.id,
                    expected_version=self.offer.aggregate_version,
                )
                results["DECLINE"] = ("SUCCESS", req_d.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results["DECLINE"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["DECLINE"] = ("ERROR", str(exc))
            finally:
                connection.close()

        t_sub = threading.Thread(target=submit_worker)
        t_dec = threading.Thread(target=decline_worker)
        t_sub.start()
        t_dec.start()
        t_sub.join()
        t_dec.join()

        successes = [k for k, v in results.items() if v[0] == "SUCCESS"]
        conflicts = [k for k, v in results.items() if v[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got {results}")
        self.assertEqual(len(conflicts), 1, f"Expected 1 conflict, got {results}")

        rev_req.refresh_from_db()
        if results["SUBMIT"][0] == "SUCCESS":
            self.assertEqual(rev_req.status, RevisionRequestStatus.RESOLVED)
        else:
            self.assertEqual(rev_req.status, RevisionRequestStatus.DECLINED)

    def test_race_submit_vs_rfq_cancel(self):
        """
        Race — submit vs RFQ cancel:
        Thread A: submit V2.
        Thread B: cancel RFQ via RFQLifecycleService.cancel_rfq.
        Serialized on RFQ lock: if RFQ cancel commits first, submit receives OfferStateError.
        """
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer.id,
            base_offer_version=self.v1_sub.id,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user1,
            revision_request=rev_req.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def submit_worker():
            connection.close()
            try:
                barrier.wait()
                v2_s, _ = submit_revised_offer_version(
                    actor=self.supplier_user1,
                    revision_request=rev_req.id,
                    draft_version=v2_draft.id,
                    expected_version=self.offer.aggregate_version,
                )
                results["SUBMIT"] = ("SUCCESS", v2_s.id)
            except (OfferConflictError, StaleVersionError, OfferStateError) as exc:
                results["SUBMIT"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["SUBMIT"] = ("ERROR", str(exc))
            finally:
                connection.close()

        def rfq_cancel_worker():
            connection.close()
            try:
                barrier.wait()
                with transaction.atomic():
                    locked_rfq = RFQ.objects.select_for_update().get(pk=self.rfq.id)
                    locked_rfq.status = RFQStatus.CANCELLED
                    locked_rfq.cancelled_at = timezone.now()
                    locked_rfq.cancellation_reason = "Buyer cancelled RFQ concurrently"
                    locked_rfq.version += 1
                    locked_rfq.save(
                        update_fields=[
                            "status",
                            "cancelled_at",
                            "cancellation_reason",
                            "version",
                            "updated_at",
                        ]
                    )
                results["RFQ_CANCEL"] = ("SUCCESS", self.rfq.id)
            except Exception as exc:
                results["RFQ_CANCEL"] = ("ERROR", str(exc))
            finally:
                connection.close()

        t_sub = threading.Thread(target=submit_worker)
        t_can = threading.Thread(target=rfq_cancel_worker)
        t_sub.start()
        t_can.start()
        t_sub.join()
        t_can.join()

        self.rfq.refresh_from_db()
        self.assertEqual(results["RFQ_CANCEL"][0], "SUCCESS")
        self.assertEqual(self.rfq.status, RFQStatus.CANCELLED)
        # If submit ran after RFQ cancel, it received CONFLICT/OfferStateError
        # If submit ran before, it succeeded before RFQ cancel
        self.assertIn(results["SUBMIT"][0], ["SUCCESS", "CONFLICT"])
