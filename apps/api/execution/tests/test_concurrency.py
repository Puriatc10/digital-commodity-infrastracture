import threading
from django.db import connection
from django.test import TransactionTestCase

from execution.models import ExecutionWorkflowTemplateVersion
from execution.services import create_draft_version, create_workflow_template
from identity.models import SystemRoleAssignment, User


class ExecutionWorkflowConcurrencyTests(TransactionTestCase):
    """Real PostgreSQL concurrency tests verifying version number allocation under thread contention."""

    def setUp(self):
        super().setUp()
        self.operator_user = User.objects.create_user(
            email="operator_concurrency@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )
        self.template = create_workflow_template(
            code="concurrent_template",
            name_fa="قالب همزمان",
            name_en="Concurrent Template",
            actor=self.operator_user,
        )

    def test_concurrent_version_allocation_no_collision(self):
        """
        Multiple concurrent transactions creating draft versions on the same template
        serialize correctly via select_for_update locking and allocate distinct sequential versions.
        """
        num_threads = 5
        errors = []
        created_versions = []

        def worker():
            try:
                # In Django threads, each thread needs its own db connection
                connection.connect()
                v = create_draft_version(
                    self.template,
                    actor=self.operator_user,
                    change_summary="Concurrent thread creation",
                )
                created_versions.append(v.version_number)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors}")
        self.assertEqual(len(created_versions), num_threads)
        self.assertEqual(sorted(created_versions), list(range(1, num_threads + 1)))

        db_versions = list(
            ExecutionWorkflowTemplateVersion.objects.filter(template=self.template)
            .values_list("version_number", flat=True)
            .order_by("version_number")
        )
        self.assertEqual(db_versions, list(range(1, num_threads + 1)))
