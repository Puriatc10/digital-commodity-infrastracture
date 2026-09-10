from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from .services import publish_schema, retire_schema, clone_schema_to_draft


class CommodityDefinitionTests(TestCase):
    def test_commodity_creation(self):
        commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.assertEqual(commodity.code, "bitumen")
        self.assertTrue(commodity.is_active)
        self.assertIsNone(commodity.active_schema_version)

    def test_code_uniqueness(self):
        CommodityDefinition.objects.create(code="test", name_fa="test", name_en="test")
        with self.assertRaises(IntegrityError):
            CommodityDefinition.objects.create(code="test", name_fa="test2", name_en="test2")

    def test_active_schema_must_be_published(self):
        commodity = CommodityDefinition.objects.create(code="test1", name_en="Test1", name_fa="Test1")
        draft_schema = CommoditySchemaVersion.objects.create(commodity=commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        commodity.active_schema_version = draft_schema
        with self.assertRaises(ValidationError):
            commodity.save()

    def test_active_schema_must_belong_to_same_commodity(self):
        comm1 = CommodityDefinition.objects.create(code="c1", name_en="C1", name_fa="C1")
        comm2 = CommodityDefinition.objects.create(code="c2", name_en="C2", name_fa="C2")
        schema = CommoditySchemaVersion.objects.create(commodity=comm2, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        comm1.active_schema_version = schema
        with self.assertRaises(ValidationError):
            comm1.save()

    def test_valid_active_schema(self):
        commodity = CommodityDefinition.objects.create(code="valid", name_en="Valid", name_fa="Valid")
        pub_schema = CommoditySchemaVersion.objects.create(commodity=commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(pub_schema)
        commodity.active_schema_version = pub_schema
        commodity.save()
        self.assertEqual(commodity.active_schema_version, pub_schema)


class CommoditySchemaVersionTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.commodity2 = CommodityDefinition.objects.create(
            code="base_oil",
            name_fa="روغن پایه",
            name_en="Base Oil"
        )

    def test_schema_belongs_to_commodity(self):
        schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )
        self.assertEqual(schema.commodity.code, "bitumen")

    def test_multiple_versions(self):
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2)
        self.assertEqual(self.commodity.schema_versions.count(), 2)

    def test_duplicate_version_rejected(self):
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)

    def test_same_version_different_commodities(self):
        schema1 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        schema2 = CommoditySchemaVersion.objects.create(commodity=self.commodity2, version=1)
        self.assertEqual(schema1.version, schema2.version)

    def test_invalid_status_rejection(self):
        # We need to test DB check constraint
        # Django's TestCase wraps tests in transactions, so IntegrityError will be raised
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(
                commodity=self.commodity,
                version=1,
                status="invalid_status"
            )

    def test_cannot_mutate_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        schema.version = 2
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_revert_published_to_draft(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        schema.status = CommoditySchemaVersion.SchemaStatus.DRAFT
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_mutate_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        # Retire the schema properly using explicit domain service
        retire_schema(schema)

        schema.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_delete_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        with self.assertRaises(ValidationError):
            schema.delete()

    def test_cannot_delete_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        retire_schema(schema)
        with self.assertRaises(ValidationError):
            schema.delete()

    def test_publish_service(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema, activate=True)
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version, schema)

    def test_retire_service(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        retire_schema(schema)
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.RETIRED)

    def test_clone_service(self):
        # Create as DRAFT first, as expected in real application lifecycle
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=schema, key="test", data_type=CommodityAttributeDefinition.DataType.STRING
        )

        # Publish the schema to verify we can clone from a published source
        publish_schema(schema)

        new_schema = clone_schema_to_draft(schema)

        self.assertEqual(new_schema.version, 2)
        self.assertEqual(new_schema.status, CommoditySchemaVersion.SchemaStatus.DRAFT)
        self.assertEqual(new_schema.commodity, self.commodity)
        self.assertEqual(new_schema.attributes.count(), 1)

        new_attr = new_schema.attributes.first()
        self.assertEqual(new_attr.key, attr.key)
        self.assertNotEqual(new_attr.id, attr.id)

        # Ensure the source remains unchanged
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        self.assertEqual(schema.attributes.count(), 1)


class CommodityAttributeDefinitionTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.schema1 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        self.schema2 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2)

    def test_attribute_belongs_to_schema(self):
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        self.assertEqual(attr.schema_version.version, 1)

    def test_duplicate_key_rejected(self):
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        with self.assertRaises(IntegrityError):
            CommodityAttributeDefinition.objects.create(
                schema_version=self.schema1,
                key="softening_point",
                data_type=CommodityAttributeDefinition.DataType.NUMBER
            )

    def test_same_key_across_versions_allowed(self):
        attr1 = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        attr2 = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema2,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        self.assertEqual(attr1.key, attr2.key)

    def test_invalid_data_type_rejected(self):
        with self.assertRaises(IntegrityError):
            CommodityAttributeDefinition.objects.create(
                schema_version=self.schema1,
                key="test",
                data_type="invalid_type"
            )

    def test_metadata_fields(self):
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="penetration_grade",
            label_fa="گرید نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.ENUM,
            is_required=True,
            unit_metadata={"allowed_units": []},
            enum_metadata={"options": [{"value": "60_70", "label_en": "60/70"}]},
            validation_metadata={},
            display_group="Main",
            sort_order=10
        )
        self.assertTrue(attr.is_required)
        self.assertEqual(attr.enum_metadata["options"][0]["value"], "60_70")

    def test_can_mutate_attribute_of_draft_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=3, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=draft_schema, key="k1", data_type="string"
        )
        attr.label_en = "Updated"
        attr.save() # Should not raise
        self.assertEqual(attr.label_en, "Updated")
        attr.delete() # Should not raise
        self.assertEqual(CommodityAttributeDefinition.objects.count(), 0)

    def test_cannot_mutate_attribute_of_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=4, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(schema_version=draft_schema, key="k2", data_type="string")
        publish_schema(draft_schema)

        attr.label_en = "Mutate"
        with self.assertRaises(ValidationError):
            attr.save()

    def test_cannot_add_attribute_to_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=5, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(draft_schema)
        with self.assertRaises(ValidationError):
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_schema, key="k3", data_type="string"
            )

    def test_cannot_delete_attribute_of_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=6, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(schema_version=draft_schema, key="k4", data_type="string")
        publish_schema(draft_schema)

        with self.assertRaises(ValidationError):
            attr.delete()

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from identity.models import User
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


class CommodityAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")
        self.client.force_login(self.user)

        self.commodity1 = CommodityDefinition.objects.create(
            code="bitumen", name_fa="قیر", name_en="Bitumen"
        )
        self.commodity2 = CommodityDefinition.objects.create(
            code="base-oil", name_fa="روغن پایه", name_en="Base Oil", is_active=False
        )

        self.v1 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity1, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
        )
        self.v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity1, version=2, status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )
        self.draft = CommoditySchemaVersion.objects.create(
            commodity=self.commodity1, version=3, status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )

        # Add some attributes to v2
        CommodityAttributeDefinition.objects.create(
            schema_version=self.v2,
            key="test_attr",
            label_fa="تست",
            label_en="Test",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True
        )

        self.v2.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        self.v2.save()
        self.commodity1.active_schema_version = self.v2
        self.commodity1.save()

    def test_authenticated_list_succeeds(self):
        url = reverse("commodity-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return active commodity (bitumen)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["code"], "bitumen")

    def test_unauthenticated_behavior(self):
        self.client.logout()
        url = reverse("commodity-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_active_published_schema_returned(self):
        url = reverse("commodity-active-schema", kwargs={"code": "bitumen"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["status"], "published")
        self.assertEqual(len(response.data["attributes"]), 1)
        self.assertEqual(response.data["attributes"][0]["key"], "test_attr")

    def test_no_active_schema_not_found(self):
        self.commodity1.active_schema_version = None
        self.commodity1.save()
        url = reverse("commodity-active-schema", kwargs={"code": "bitumen"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_commodity_not_found(self):
        url = reverse("commodity-active-schema", kwargs={"code": "unknown"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_historical_published_schema_retrieval(self):
        url = reverse("commodity-schema-detail", kwargs={"pk": self.v1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version"], 1)

    def test_historical_retired_schema_retrieval(self):
        # Retire v1 for test
        self.v1.status = CommoditySchemaVersion.SchemaStatus.RETIRED
        self.v1.save()
        url = reverse("commodity-schema-detail", kwargs={"pk": self.v1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version"], 1)

    def test_draft_historical_retrieval_denied(self):
        url = reverse("commodity-schema-detail", kwargs={"pk": self.draft.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unsupported_write_methods_unavailable(self):
        url = reverse("commodity-list")
        response = self.client.post(url, data={"code": "new"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.patch(url, data={"code": "new"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
