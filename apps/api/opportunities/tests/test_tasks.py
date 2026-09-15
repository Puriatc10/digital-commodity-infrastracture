import datetime
from decimal import Decimal

from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment, User
from opportunities.models import (
    OpportunityContactAttempt,
    OpportunityDirection,
    OpportunitySource,
    OpportunityTask,
    OpportunityTaskStatus,
)
from opportunities.services import (
    cancel_opportunity_task,
    complete_opportunity_task,
    create_opportunity,
    create_opportunity_task,
    get_follow_up_required_tasks,
    get_tasks_assigned_to_user,
    list_opportunity_tasks,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)


class OpportunityTaskTests(TestCase):
    """
    Comprehensive tests for T0607 Opportunity Tasks / Follow-ups.
    """

    def setUp(self):
        self.client = APIClient()

        # Actors
        self.operator = User.objects.create_user(email="operator@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.admin = User.objects.create_user(email="admin@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        self.other_operator = User.objects.create_user(
            email="other_operator@platform.com", password="password"
        )
        SystemRoleAssignment.objects.create(
            user=self.other_operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.buyer_org = Organization.objects.create(name="Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        self.supplier_org = Organization.objects.create(name="Supplier Org")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        self.broker_org = Organization.objects.create(name="Broker Org")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        self.staff_only = User.objects.create_user(
            email="staff@platform.com", password="password", is_staff=True
        )
        self.superuser_only = User.objects.create_superuser(
            email="superuser@platform.com", password="password"
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_task_test",
            name_en="Bitumen Task Test",
            name_fa="قیر تست تسک",
        )

        # Primary Opportunity
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("200.000"),
            indicative_price=Decimal("410.00"),
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
            created_by=self.operator,
        )

        # Second Opportunity for IDOR tests
        self.other_opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            indicative_price=Decimal("390.00"),
            source=OpportunitySource.OPERATOR_SOURCING,
            created_by=self.operator,
        )

    # -------------------------------------------------------------------------
    # 1. Creation & Basic Functionality
    # -------------------------------------------------------------------------

    def test_create_task_success(self):
        """Operator can create a follow-up task on an Opportunity."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=2)

        payload = {
            "title": "Follow up on sample specs",
            "description": "Call counterparty regarding flash point requirements",
            "due_at": due.isoformat(),
            "assigned_to": self.other_operator.id,
        }
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        data = resp.data
        self.assertEqual(data["title"], "Follow up on sample specs")
        self.assertEqual(data["description"], "Call counterparty regarding flash point requirements")
        self.assertEqual(data["status"], OpportunityTaskStatus.OPEN)
        self.assertFalse(data["is_overdue"])
        self.assertEqual(data["assigned_to"], self.other_operator.id)
        self.assertEqual(data["assigned_to_email"], self.other_operator.email)
        self.assertEqual(data["created_by"], self.operator.id)
        self.assertEqual(data["created_by_email"], self.operator.email)
        self.assertIsNone(data["completed_at"])
        self.assertEqual(data["opportunity_id"], str(self.opp.id))

    def test_create_task_with_canonical_identifier(self):
        """Can create task using human-readable opportunity identifier in path."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.identifier}/tasks/",
            {"title": "Check shipment schedule", "due_at": due.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["opportunity_id"], str(self.opp.id))

    def test_create_task_unassigned_allowed(self):
        """Follow-up task can be created without an assignee (assigned_to=None)."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {"title": "Unassigned follow-up", "due_at": due.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data["assigned_to"])
        self.assertIsNone(resp.data["assigned_to_email"])

    def test_create_task_empty_title_rejected(self):
        """Task creation fails when title is empty or whitespace."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {"title": "   ", "due_at": due.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", resp.data)

    def test_create_task_missing_due_at_rejected(self):
        """Task creation fails when due_at is missing."""
        self.client.force_authenticate(user=self.operator)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {"title": "Missing due date"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("due_at", resp.data)

    # -------------------------------------------------------------------------
    # 2. Creator Derivation & Mass Assignment Protection
    # -------------------------------------------------------------------------

    def test_creator_derived_server_side_spoof_ignored(self):
        """Client cannot spoof created_by or status or completed_at during creation."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        payload = {
            "title": "Spoof attempt",
            "due_at": due.isoformat(),
            "created_by": self.admin.id,
            "status": "COMPLETED",
            "completed_at": timezone.now().isoformat(),
            "opportunity_id": str(self.other_opp.id),
        }
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        data = resp.data
        self.assertEqual(data["created_by"], self.operator.id)
        self.assertEqual(data["status"], OpportunityTaskStatus.OPEN)
        self.assertIsNone(data["completed_at"])
        self.assertEqual(data["opportunity_id"], str(self.opp.id))

    # -------------------------------------------------------------------------
    # 3. Assignment Policy
    # -------------------------------------------------------------------------

    def test_assignment_to_operator_succeeds(self):
        """Assigning to an active user with OPERATOR role succeeds."""
        task = create_opportunity_task(
            self.opp.id,
            title="Operator task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.operator.id,
            actor=self.operator,
        )
        self.assertEqual(task.assigned_to, self.operator)

    def test_assignment_to_admin_succeeds(self):
        """Assigning to an active user with ADMIN role succeeds."""
        task = create_opportunity_task(
            self.opp.id,
            title="Admin task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.admin.id,
            actor=self.operator,
        )
        self.assertEqual(task.assigned_to, self.admin)

    def test_assignment_to_buyer_rejected(self):
        """Assigning to a Buyer user is rejected with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {
                "title": "Invalid assignment to buyer",
                "due_at": due.isoformat(),
                "assigned_to": self.buyer_user.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assigned_to", str(resp.data))

    def test_assignment_to_supplier_rejected(self):
        """Assigning to a Supplier user is rejected with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {
                "title": "Invalid assignment to supplier",
                "due_at": due.isoformat(),
                "assigned_to": self.supplier_user.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assigned_to", str(resp.data))

    def test_assignment_to_broker_rejected(self):
        """Assigning to a Broker user is rejected with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {
                "title": "Invalid assignment to broker",
                "due_at": due.isoformat(),
                "assigned_to": self.broker_user.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assigned_to", str(resp.data))

    def test_assignment_to_non_existent_user_rejected(self):
        """Assigning to a non-existent user ID is rejected with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        due = timezone.now() + datetime.timedelta(days=1)

        resp = self.client.post(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/",
            {
                "title": "Invalid assignment to phantom",
                "due_at": due.isoformat(),
                "assigned_to": 999999,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assigned_to", str(resp.data))

    # -------------------------------------------------------------------------
    # 4. Authorization Matrix
    # -------------------------------------------------------------------------

    def test_authorization_matrix_for_list_create(self):
        """Verify strict authorization matrix on tasks list/create endpoint."""
        endpoint = f"/api/opportunities/opportunities/{self.opp.id}/tasks/"
        due = (timezone.now() + datetime.timedelta(days=1)).isoformat()
        payload = {"title": "Auth test", "due_at": due}

        # 1. Anonymous -> Denied (401 or 403)
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.client.get(endpoint).status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            self.client.post(endpoint, payload, format="json").status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )


        # 2. Operator -> 200 / 201
        self.client.force_authenticate(user=self.operator)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_201_CREATED)

        # 3. Admin -> 200 / 201
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_201_CREATED)

        # 4. Buyer -> 403
        self.client.force_authenticate(user=self.buyer_user)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_403_FORBIDDEN)

        # 5. Supplier -> 403
        self.client.force_authenticate(user=self.supplier_user)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_403_FORBIDDEN)

        # 6. Broker -> 403
        self.client.force_authenticate(user=self.broker_user)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_403_FORBIDDEN)

        # 7. Django Staff-only without SystemRole -> 403
        self.client.force_authenticate(user=self.staff_only)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_403_FORBIDDEN)

        # 8. Django Superuser-only without SystemRole -> 403
        self.client.force_authenticate(user=self.superuser_only)
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(endpoint, payload, format="json").status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 5. Completion Lifecycle & Idempotency / Invalid Transitions
    # -------------------------------------------------------------------------

    def test_complete_task_success(self):
        """Explicit POST .../complete marks task as COMPLETED and sets completed_at."""
        task = create_opportunity_task(
            self.opp.id,
            title="Complete me",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        self.assertEqual(data["status"], OpportunityTaskStatus.COMPLETED)
        self.assertIsNotNone(data["completed_at"])

        task.refresh_from_db()
        self.assertEqual(task.status, OpportunityTaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_repeated_completion_rejected(self):
        """Attempting to complete an already COMPLETED task returns 400 Bad Request."""
        task = create_opportunity_task(
            self.opp.id,
            title="Complete twice",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        complete_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be completed", resp.data["detail"])

    def test_complete_cancelled_task_rejected(self):
        """Attempting to complete a CANCELLED task returns 400 Bad Request."""
        task = create_opportunity_task(
            self.opp.id,
            title="Cancelled then complete",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be completed", resp.data["detail"])

    # -------------------------------------------------------------------------
    # 6. Cancellation Lifecycle
    # -------------------------------------------------------------------------

    def test_cancel_task_success(self):
        """Explicit POST .../cancel marks task as CANCELLED; task is NOT deleted."""
        task = create_opportunity_task(
            self.opp.id,
            title="Cancel me",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        self.assertEqual(data["status"], OpportunityTaskStatus.CANCELLED)
        self.assertIsNone(data["completed_at"])

        task.refresh_from_db()
        self.assertEqual(task.status, OpportunityTaskStatus.CANCELLED)
        self.assertIsNone(task.completed_at)

    def test_repeated_cancel_rejected(self):
        """Attempting to cancel an already CANCELLED task returns 400 Bad Request."""
        task = create_opportunity_task(
            self.opp.id,
            title="Cancel twice",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be cancelled", resp.data["detail"])

    def test_cancel_completed_task_rejected(self):
        """Attempting to cancel a COMPLETED task returns 400 Bad Request."""
        task = create_opportunity_task(
            self.opp.id,
            title="Completed then cancel",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        complete_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be cancelled", resp.data["detail"])

    # -------------------------------------------------------------------------
    # 7. Overdue Semantics & No Stale Persisted Column
    # -------------------------------------------------------------------------

    def test_overdue_is_not_a_persisted_model_field(self):
        """Verify is_overdue is not a persisted database column."""
        with self.assertRaises(FieldDoesNotExist):
            OpportunityTask._meta.get_field("is_overdue")

    def test_overdue_computed_dynamically(self):
        """Verify is_overdue property dynamically derives from status == OPEN and due_at < now."""
        now = timezone.now()

        # 1. Open task with past due date -> overdue
        task_past = create_opportunity_task(
            self.opp.id,
            title="Past task",
            due_at=now - datetime.timedelta(hours=2),
            actor=self.operator,
        )
        self.assertTrue(task_past.is_overdue)

        # 2. Open task with future due date -> not overdue
        task_future = create_opportunity_task(
            self.opp.id,
            title="Future task",
            due_at=now + datetime.timedelta(hours=2),
            actor=self.operator,
        )
        self.assertFalse(task_future.is_overdue)

        # 3. Completed task with past due date -> NOT overdue
        complete_opportunity_task(self.opp.id, task_past.id, actor=self.operator)
        task_past.refresh_from_db()
        self.assertFalse(task_past.is_overdue)

        # 4. Cancelled task with past due date -> NOT overdue
        task_past_cancelled = create_opportunity_task(
            self.opp.id,
            title="Cancelled past task",
            due_at=now - datetime.timedelta(hours=5),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task_past_cancelled.id, actor=self.operator)
        task_past_cancelled.refresh_from_db()
        self.assertFalse(task_past_cancelled.is_overdue)

    def test_completed_and_cancelled_tasks_excluded_from_follow_up_required(self):
        """Completed and cancelled tasks do not appear in follow_up_required queries."""
        now = timezone.now()

        task_open_overdue = create_opportunity_task(
            self.opp.id,
            title="Open overdue",
            due_at=now - datetime.timedelta(hours=1),
            actor=self.operator,
        )
        task_completed = create_opportunity_task(
            self.opp.id,
            title="Completed overdue",
            due_at=now - datetime.timedelta(hours=2),
            actor=self.operator,
        )
        complete_opportunity_task(self.opp.id, task_completed.id, actor=self.operator)

        task_cancelled = create_opportunity_task(
            self.opp.id,
            title="Cancelled overdue",
            due_at=now - datetime.timedelta(hours=3),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task_cancelled.id, actor=self.operator)

        follow_up_tasks = list(get_follow_up_required_tasks(now=now))
        task_ids = [t.id for t in follow_up_tasks]

        self.assertIn(task_open_overdue.id, task_ids)
        self.assertNotIn(task_completed.id, task_ids)
        self.assertNotIn(task_cancelled.id, task_ids)

    # -------------------------------------------------------------------------
    # 8. Deterministic Ordering
    # -------------------------------------------------------------------------

    def test_deterministic_ordering_with_identical_due_at(self):
        """Tasks are deterministically ordered by due_at ASC, created_at ASC, id ASC."""
        fixed_due = timezone.now() + datetime.timedelta(days=3)

        t1 = create_opportunity_task(self.opp.id, title="Task A", due_at=fixed_due, actor=self.operator)
        t2 = create_opportunity_task(self.opp.id, title="Task B", due_at=fixed_due, actor=self.operator)
        t3 = create_opportunity_task(self.opp.id, title="Task C", due_at=fixed_due, actor=self.operator)
        earlier_task = create_opportunity_task(
            self.opp.id,
            title="Earlier Due",
            due_at=fixed_due - datetime.timedelta(hours=1),
            actor=self.operator,
        )

        tasks = list(list_opportunity_tasks(self.opp.id))
        ids = [t.id for t in tasks]

        self.assertEqual(ids[0], earlier_task.id)
        self.assertEqual(ids[1:], [t1.id, t2.id, t3.id])

    # -------------------------------------------------------------------------
    # 9. Scoping & IDOR Prevention
    # -------------------------------------------------------------------------

    def test_cross_opportunity_idor_retrieve(self):
        """Accessing Opportunity B's task through Opportunity A route returns 404."""
        task_on_b = create_opportunity_task(
            self.other_opp.id,
            title="Task on B",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.get(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task_on_b.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_opportunity_idor_complete(self):
        """Completing Opportunity B's task through Opportunity A route returns 404."""
        task_on_b = create_opportunity_task(
            self.other_opp.id,
            title="Task on B",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task_on_b.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        task_on_b.refresh_from_db()
        self.assertEqual(task_on_b.status, OpportunityTaskStatus.OPEN)

    def test_cross_opportunity_idor_cancel(self):
        """Cancelling Opportunity B's task through Opportunity A route returns 404."""
        task_on_b = create_opportunity_task(
            self.other_opp.id,
            title="Task on B",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task_on_b.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        task_on_b.refresh_from_db()
        self.assertEqual(task_on_b.status, OpportunityTaskStatus.OPEN)

    def test_malformed_opportunity_id_returns_404(self):
        """Malformed Opportunity UUID or invalid identifier returns 404, never 500."""
        self.client.force_authenticate(user=self.operator)
        resp = self.client.get("/api/opportunities/opportunities/not-a-valid-uuid-or-id/tasks/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_task_id_returns_404(self):
        """Malformed task UUID returns 404, never 500."""
        self.client.force_authenticate(user=self.operator)
        resp = self.client.get(f"/api/opportunities/opportunities/{self.opp.id}/tasks/not-a-uuid/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # 10. Separation from Opportunity Lifecycle and Contact Attempts
    # -------------------------------------------------------------------------

    def test_task_operations_do_not_mutate_opportunity_lifecycle(self):
        """Creating, completing, or cancelling tasks must NOT mutate parent Opportunity."""
        initial_status = self.opp.status
        initial_version = self.opp.version
        initial_contacted_at = self.opp.contacted_at
        initial_qualified_at = self.opp.qualified_at

        # 1. Create
        task = create_opportunity_task(
            self.opp.id,
            title="Lifecycle isolation test",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, initial_status)
        self.assertEqual(self.opp.version, initial_version)
        self.assertEqual(self.opp.contacted_at, initial_contacted_at)
        self.assertEqual(self.opp.qualified_at, initial_qualified_at)

        # 2. Complete
        complete_opportunity_task(self.opp.id, task.id, actor=self.operator)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, initial_status)
        self.assertEqual(self.opp.version, initial_version)
        self.assertEqual(self.opp.contacted_at, initial_contacted_at)
        self.assertEqual(self.opp.qualified_at, initial_qualified_at)

        # 3. Create second & Cancel
        task2 = create_opportunity_task(
            self.opp.id,
            title="Lifecycle isolation test 2",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task2.id, actor=self.operator)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, initial_status)
        self.assertEqual(self.opp.version, initial_version)

    def test_task_operations_do_not_create_contact_attempts(self):
        """Creating, completing, or cancelling tasks must create 0 Contact Attempt rows."""
        initial_count = OpportunityContactAttempt.objects.filter(opportunity=self.opp).count()

        task = create_opportunity_task(
            self.opp.id,
            title="Contact attempt isolation",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        self.assertEqual(
            OpportunityContactAttempt.objects.filter(opportunity=self.opp).count(),
            initial_count,
        )

        complete_opportunity_task(self.opp.id, task.id, actor=self.operator)
        self.assertEqual(
            OpportunityContactAttempt.objects.filter(opportunity=self.opp).count(),
            initial_count,
        )

    # -------------------------------------------------------------------------
    # 11. Task Update & Mutation Safety
    # -------------------------------------------------------------------------

    def test_update_open_task_success(self):
        """Can update title, description, due_at, and assigned_to of an OPEN task."""
        task = create_opportunity_task(
            self.opp.id,
            title="Original title",
            description="Original desc",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.operator.id,
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        new_due = timezone.now() + datetime.timedelta(days=5)
        resp = self.client.patch(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/",
            {
                "title": "Updated title",
                "description": "Updated desc",
                "due_at": new_due.isoformat(),
                "assigned_to": self.other_operator.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["title"], "Updated title")
        self.assertEqual(resp.data["description"], "Updated desc")
        self.assertEqual(resp.data["assigned_to"], self.other_operator.id)

    def test_update_completed_task_rejected(self):
        """Cannot update a task once it has been COMPLETED."""
        task = create_opportunity_task(
            self.opp.id,
            title="Completed task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        complete_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.patch(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/",
            {"title": "Try to change"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be updated", str(resp.data))

    def test_update_cancelled_task_rejected(self):
        """Cannot update a task once it has been CANCELLED."""
        task = create_opportunity_task(
            self.opp.id,
            title="Cancelled task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )
        cancel_opportunity_task(self.opp.id, task.id, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        resp = self.client.patch(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/",
            {"title": "Try to change"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only OPEN tasks can be updated", str(resp.data))

    def test_update_cannot_mutate_status_or_opportunity(self):
        """Update payload cannot modify status, opportunity, created_by, or completed_at."""
        task = create_opportunity_task(
            self.opp.id,
            title="Safety test",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.patch(
            f"/api/opportunities/opportunities/{self.opp.id}/tasks/{task.id}/",
            {
                "status": "COMPLETED",
                "completed_at": timezone.now().isoformat(),
                "opportunity_id": str(self.other_opp.id),
                "created_by": self.admin.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        task.refresh_from_db()
        self.assertEqual(task.status, OpportunityTaskStatus.OPEN)
        self.assertIsNone(task.completed_at)
        self.assertEqual(task.opportunity_id, self.opp.id)
        self.assertEqual(task.created_by, self.operator)

    # -------------------------------------------------------------------------
    # 12. Query Support for T0612 Opportunity Desk Views
    # -------------------------------------------------------------------------

    def test_t0612_assigned_to_me_opportunity_filter(self):
        """Opportunity listing with ?assigned_to_me=true returns only opportunities with open task assigned to caller."""
        # Opp 1 has an open task assigned to self.operator
        create_opportunity_task(
            self.opp.id,
            title="My open task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.operator.id,
            actor=self.operator,
        )

        # Other Opp has an open task assigned to other_operator
        create_opportunity_task(
            self.other_opp.id,
            title="Other operator task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.other_operator.id,
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.get("/api/opportunities/opportunities/?assigned_to_me=true")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        results = resp.data["results"] if "results" in resp.data else resp.data
        returned_ids = [r["id"] for r in results]
        self.assertIn(str(self.opp.id), returned_ids)
        self.assertNotIn(str(self.other_opp.id), returned_ids)

    def test_t0612_follow_up_required_opportunity_filter(self):
        """Opportunity listing with ?follow_up_required=true returns only opportunities with open tasks due or overdue."""
        now = timezone.now()

        # Opp 1 has an overdue open task
        create_opportunity_task(
            self.opp.id,
            title="Overdue task on Opp 1",
            due_at=now - datetime.timedelta(hours=2),
            actor=self.operator,
        )

        # Other Opp has only a future task
        create_opportunity_task(
            self.other_opp.id,
            title="Future task on Opp 2",
            due_at=now + datetime.timedelta(days=5),
            actor=self.operator,
        )

        self.client.force_authenticate(user=self.operator)
        resp = self.client.get("/api/opportunities/opportunities/?follow_up_required=true")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        results = resp.data["results"] if "results" in resp.data else resp.data
        returned_ids = [r["id"] for r in results]
        self.assertIn(str(self.opp.id), returned_ids)
        self.assertNotIn(str(self.other_opp.id), returned_ids)

    def test_t0612_service_get_tasks_assigned_to_user(self):
        """Service function get_tasks_assigned_to_user returns open tasks assigned to user."""
        t1 = create_opportunity_task(
            self.opp.id,
            title="Assigned to me",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.operator.id,
            actor=self.operator,
        )
        t2 = create_opportunity_task(
            self.opp.id,
            title="Completed assigned to me",
            due_at=timezone.now() + datetime.timedelta(days=1),
            assigned_to_id=self.operator.id,
            actor=self.operator,
        )
        complete_opportunity_task(self.opp.id, t2.id, actor=self.operator)

        open_tasks = list(get_tasks_assigned_to_user(self.operator))
        self.assertEqual([t.id for t in open_tasks], [t1.id])
