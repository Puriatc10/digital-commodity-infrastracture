"""Epic gate regressions: supported mutations and actual PostgreSQL state."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from identity.models import User
from .models import CommodityDefinition as Commodity, CommoditySchemaVersion as Schema
from .models import CommodityAttributeDefinition as Attribute
from .services import publish_schema, retire_schema, clone_schema_to_draft
from .services import validate_commodity_payload
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.core.management import call_command
from io import StringIO
from unittest.mock import patch


class ReviewGateTests(TestCase):
    def setUp(self):
        self.commodity = Commodity.objects.create(code="third_commodity", name_fa="آزمون", name_en="Third")
        self.schema = Schema.objects.create(commodity=self.commodity, version=1)
        self.attr = Attribute.objects.create(
            schema_version=self.schema, key="quality", label_fa="کیفیت", label_en="Quality",
            data_type="enum", enum_metadata={"options": [
                {"value": "a", "label_fa": "الف", "label_en": "A"}]},
        )

    def assert_rejected_unchanged(self, model, operation):
        before = list(model.objects.order_by("pk").values())
        with self.assertRaises(ValidationError), transaction.atomic():
            operation()
        self.assertEqual(before, list(model.objects.order_by("pk").values()))

    def test_attribute_cannot_move_from_draft_into_published(self):
        published = Schema.objects.create(commodity=self.commodity, version=2)
        publish_schema(published)
        self.attr.schema_version = published
        self.assert_rejected_unchanged(Attribute, self.attr.save)

    def test_cached_draft_cannot_add_or_delete_after_publication(self):
        cached = Schema.objects.get(pk=self.schema.pk)
        attr = Attribute.objects.select_related("schema_version").get(pk=self.attr.pk)
        publish_schema(self.schema)
        self.assert_rejected_unchanged(Attribute, lambda: Attribute.objects.create(
            schema_version=cached, key="late", data_type="string"))
        self.assert_rejected_unchanged(Attribute, attr.delete)
        self.assert_rejected_unchanged(Schema, cached.delete)

    def test_parent_delete_cannot_cascade_published_history(self):
        publish_schema(self.schema)
        self.assert_rejected_unchanged(Schema, self.commodity.delete)

    def test_queryset_deletion_cannot_remove_history(self):
        publish_schema(self.schema)
        for model in (Attribute, Schema, Commodity):
            with self.subTest(model=model):
                self.assert_rejected_unchanged(model, lambda: model.objects.all().delete())

    def test_cached_commodity_cannot_retire_current_active_schema(self):
        publish_schema(self.schema)
        stale = Schema.objects.select_related("commodity").get(pk=self.schema.pk)
        commodity = Commodity.objects.get(pk=self.commodity.pk)
        commodity.active_schema_version = self.schema
        commodity.save()
        self.assert_rejected_unchanged(Schema, lambda: retire_schema(stale))

    def test_cached_published_cannot_activate_retired_schema(self):
        publish_schema(self.schema)
        stale = Schema.objects.get(pk=self.schema.pk)
        retire_schema(self.schema)
        self.commodity.active_schema_version = stale
        self.assert_rejected_unchanged(Commodity, self.commodity.save)

    def test_draft_cannot_skip_to_retired(self):
        self.schema.status = "retired"
        self.assert_rejected_unchanged(Schema, self.schema.save)

    def test_published_and_retired_all_attribute_semantics_immutable(self):
        publish_schema(self.schema)
        changes = dict(key="changed", label_fa="تغییر", label_en="Changed", data_type="string",
                       is_required=True, unit_metadata={"canonical_unit": "m"},
                       enum_metadata={"options": []}, validation_metadata={"minLength": 2},
                       display_group="Changed", sort_order=22)
        for status in ("published", "retired"):
            if status == "retired":
                retire_schema(self.schema)
            for field, value in changes.items():
                with self.subTest(status=status, field=field):
                    attr = Attribute.objects.get(pk=self.attr.pk)
                    setattr(attr, field, value)
                    self.assert_rejected_unchanged(Attribute, attr.save)

    def test_commodity_code_is_stable_and_canonical(self):
        self.commodity.code = "renamed"
        self.assert_rejected_unchanged(Commodity, self.commodity.save)
        with self.assertRaises(ValidationError):
            Commodity.objects.create(code="Not Canonical", name_fa="x", name_en="x")

    def test_reverse_and_repeated_lifecycle_transitions_leave_state_unchanged(self):
        publish_schema(self.schema)
        for _ in range(2):
            self.assert_rejected_unchanged(Schema, lambda: publish_schema(self.schema))
        retire_schema(self.schema)
        for target in ("draft", "published"):
            for _ in range(2):
                self.schema.refresh_from_db()
                self.schema.status = target
                self.assert_rejected_unchanged(Schema, self.schema.save)

    def test_duplicate_enum_and_invalid_bounds_rejected_before_publish(self):
        # Trusted bulk paths can load draft data; publishing must still validate definitions.
        for metadata in ({"options": [{"value": "a"}, {"value": "a"}]},):
            Attribute.objects.filter(pk=self.attr.pk).update(enum_metadata=metadata)
            self.assert_rejected_unchanged(Schema, lambda: publish_schema(Schema.objects.get(pk=self.schema.pk)))
        Attribute.objects.filter(pk=self.attr.pk).update(
            data_type="number", enum_metadata={}, validation_metadata={"minimum": "bad"})
        self.assert_rejected_unchanged(Schema, lambda: publish_schema(Schema.objects.get(pk=self.schema.pk)))

    def test_unknown_fields_addressed_individually_in_stable_order(self):
        fields = ["z_extra", "a'quoted", "b_extra"]
        with self.assertRaises(ValidationError) as error:
            validate_commodity_payload(self.schema, dict.fromkeys(fields, 1))
        errors = error.exception.params["errors"]
        self.assertEqual([(e["field"], e["code"]) for e in errors],
                         [(key, "unknown_field") for key in sorted(fields)])

    def test_relational_constraints_bypassing_model_validation(self):
        factories = [
            (Commodity, dict(code=self.commodity.code, name_fa="x", name_en="x")),
            (Schema, dict(commodity=self.commodity, version=1)),
            (Schema, dict(commodity=self.commodity, version=2, status="invalid")),
            (Attribute, dict(schema_version=self.schema, key="quality", data_type="string")),
            (Attribute, dict(schema_version=self.schema, key="invalid", data_type="object")),
        ]
        for model, values in factories:
            with self.subTest(model=model, values=values), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.bulk_create([model(**values)])

    def test_historical_evolution_keeps_explicit_version_and_clone_metadata(self):
        publish_schema(self.schema, activate=True)
        before = deepcopy(list(self.schema.attributes.values()))
        v2 = clone_schema_to_draft(self.schema)
        new_attr = v2.attributes.get()
        self.assertNotEqual(new_attr.pk, self.attr.pk)
        for field in ("enum_metadata", "unit_metadata", "validation_metadata", "display_group", "sort_order"):
            self.assertEqual(getattr(new_attr, field), getattr(self.attr, field))
        new_attr.enum_metadata = {"options": [{"value": "b", "label_fa": "ب", "label_en": "B"}]}
        new_attr.save()
        publish_schema(v2, activate=True)
        self.schema.refresh_from_db()
        self.commodity.refresh_from_db()
        self.assertEqual(self.schema.status, "published")
        self.assertEqual(self.commodity.active_schema_version_id, v2.pk)
        self.assertEqual(before, list(self.schema.attributes.values()))
        validate_commodity_payload(self.schema, {"quality": "a"})
        with self.assertRaises(ValidationError):
            validate_commodity_payload(v2, {"quality": "a"})
        retire_schema(self.schema)
        validate_commodity_payload(self.schema, {"quality": "a"})
        client = APIClient()
        client.force_authenticate(User.objects.create_user(email="gate@example.test"))
        response = client.get(f"/api/commodity-schemas/{self.schema.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["attributes"][0]["enum_metadata"]["options"][0]["value"], "a")

    def test_active_api_rejects_cross_commodity_pointer_from_trusted_bypass(self):
        publish_schema(self.schema)
        other = Commodity.objects.create(code="other", name_fa="x", name_en="Other")
        Commodity.objects.filter(pk=other.pk).update(active_schema_version=self.schema)
        client = APIClient()
        client.force_authenticate(User.objects.create_user(email="gate@example.test"))
        self.assertEqual(client.get("/api/commodities/other/schema/").status_code, 404)

    def test_seed_conflicts_preserve_published_semantics_and_new_active_version(self):
        for code in ("bitumen", "base_oil"):
            with self.subTest(code=code):
                call_command(f"seed_{code}", stdout=StringIO())
                commodity = Commodity.objects.get(code=code)
                v1 = commodity.active_schema_version
                # Deliberate trusted bypass simulates a conflicting pre-existing seed.
                v1.attributes.update(label_fa="تاریخچه متفاوت")
                before = list(v1.attributes.values())
                v2 = clone_schema_to_draft(v1)
                publish_schema(v2, activate=True)
                for _ in range(2):
                    call_command(f"seed_{code}", stdout=StringIO())
                self.assertEqual(before, list(v1.attributes.values()))
                commodity.refresh_from_db()
                self.assertEqual(commodity.active_schema_version_id, v2.pk)
                self.assertEqual(commodity.schema_versions.count(), 2)

    def test_clone_and_publish_activation_roll_back_on_failure(self):
        publish_schema(self.schema)
        before = list(Schema.objects.values())
        with patch.object(Attribute, "save", side_effect=ValidationError("injected failure")):
            with self.assertRaises(ValidationError):
                clone_schema_to_draft(self.schema)
        self.assertEqual(before, list(Schema.objects.values()))
        v2 = clone_schema_to_draft(self.schema)
        with patch.object(Commodity, "save", side_effect=ValidationError("injected failure")):
            with self.assertRaises(ValidationError):
                publish_schema(v2, activate=True)
        v2.refresh_from_db()
        self.commodity.refresh_from_db()
        self.assertEqual(v2.status, "draft")
        self.assertIsNone(self.commodity.active_schema_version_id)

    def test_type_null_required_and_exact_numeric_string_boundaries(self):
        for key, data_type, metadata in (("text", "string", {"minLength": 2, "maxLength": 3}),
                                        ("count", "integer", {"minimum": 1, "maximum": 2}),
                                        ("density", "number", {"minimum": 1, "maximum": 2}),
                                        ("certified", "boolean", {})):
            Attribute.objects.create(schema_version=self.schema, key=key, data_type=data_type,
                                     is_required=True, validation_metadata=metadata)
        valid = {"text": "ab", "count": 1, "density": 1.5, "certified": False}
        validate_commodity_payload(self.schema, valid)
        validate_commodity_payload(self.schema, {**valid, "text": "abc", "count": 2, "density": 2})
        for key, bad_values in {"text": ("a", "abcd", None, 1), "count": (0, 3, 1.5, True, None),
                                "density": (0.9, 2.1, True, None, float("nan"), float("inf")), "certified": (0, "false", None),
                                "quality": (None, "الف", "unknown")}.items():
            for bad in bad_values:
                with self.subTest(key=key, value=bad), self.assertRaises(ValidationError):
                    validate_commodity_payload(self.schema, {**valid, key: bad})
        for key in valid:
            with self.subTest(missing=key), self.assertRaises(ValidationError) as error:
                validate_commodity_payload(self.schema, {k: v for k, v in valid.items() if k != key})
            self.assertIn({"field": key, "code": "required", "message": "This field is required."}, error.exception.params["errors"])

    def test_api_auth_read_only_and_query_counts(self):
        publish_schema(self.schema, activate=True)
        client = APIClient()
        urls = ["/api/commodities/", "/api/commodities/third_commodity/schema/",
                f"/api/commodity-schemas/{self.schema.pk}/"]
        for url in urls:
            self.assertEqual(client.get(url).status_code, 403)
        client.force_authenticate(User.objects.create_user(email="catalog@example.test"))
        for url, queries in zip(urls, (1, 4, 2)):
            with self.assertNumQueries(queries):
                self.assertEqual(client.get(url).status_code, 200)
            for method in ("post", "put", "patch", "delete"):
                self.assertEqual(getattr(client, method)(url, {}, format="json").status_code, 405)


class CommodityConcurrencyTests(TransactionTestCase):
    def test_concurrent_clones_allocate_distinct_complete_versions(self):
        commodity = Commodity.objects.create(code="concurrent", name_fa="x", name_en="Concurrent")
        schema = Schema.objects.create(commodity=commodity, version=1)
        Attribute.objects.create(schema_version=schema, key="density", data_type="number")
        publish_schema(schema)
        barrier = Barrier(2)

        def clone():
            close_old_connections()
            try:
                source = Schema.objects.get(pk=schema.pk)
                barrier.wait(timeout=10)
                result = clone_schema_to_draft(source)
                return result.version, result.attributes.count()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(clone) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(results), [(2, 1), (3, 1)])

    def test_concurrent_retirement_and_activation_never_leave_retired_active(self):
        commodity = Commodity.objects.create(code="race", name_fa="x", name_en="Race")
        schema = Schema.objects.create(commodity=commodity, version=1)
        publish_schema(schema)
        barrier = Barrier(2)

        def mutate(activate):
            close_old_connections()
            try:
                current = Schema.objects.get(pk=schema.pk)
                parent = Commodity.objects.get(pk=commodity.pk)
                barrier.wait(timeout=10)
                try:
                    if activate:
                        parent.active_schema_version = current
                        parent.save()
                    else:
                        retire_schema(current)
                    return True
                except ValidationError:
                    return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(mutate, activate) for activate in (True, False)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(outcomes), [False, True])
        commodity.refresh_from_db()
        schema.refresh_from_db()
        self.assertTrue(commodity.active_schema_version_id is None or schema.status == "published")
