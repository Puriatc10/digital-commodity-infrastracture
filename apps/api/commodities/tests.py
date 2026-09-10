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
        schema = CommoditySchemaVersion.objects.create(commodity=comm2, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        comm1.active_schema_version = schema
        with self.assertRaises(ValidationError):
            comm1.save()

    def test_valid_active_schema(self):
        commodity = CommodityDefinition.objects.create(code="valid", name_en="Valid", name_fa="Valid")
        pub_schema = CommoditySchemaVersion.objects.create(commodity=commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
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

    def test_duplicate_version_rejected(self):
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)

    def test_invalid_status_rejection(self):
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(
                commodity=self.commodity,
                version=1,
                status="invalid_status"
            )

    def test_cannot_mutate_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        schema.version = 2
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_revert_published_to_draft(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        schema.status = CommoditySchemaVersion.SchemaStatus.DRAFT
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_mutate_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.RETIRED)
        schema.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_delete_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        with self.assertRaises(ValidationError):
            schema.delete()

    def test_cannot_delete_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.RETIRED)
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
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        retire_schema(schema)
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.RETIRED)

    def test_clone_service(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=schema, key="test", data_type=CommodityAttributeDefinition.DataType.STRING
        )

        new_schema = clone_schema_to_draft(schema)

        self.assertEqual(new_schema.version, 2)
        self.assertEqual(new_schema.status, CommoditySchemaVersion.SchemaStatus.DRAFT)
        self.assertEqual(new_schema.commodity, self.commodity)
        self.assertEqual(new_schema.attributes.count(), 1)

        new_attr = new_schema.attributes.first()
        self.assertEqual(new_attr.key, attr.key)
        self.assertNotEqual(new_attr.id, attr.id)


class CommodityAttributeDefinitionTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)

    def test_can_mutate_attribute_of_draft_schema(self):
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.draft_schema, key="k1", data_type="string"
        )
        attr.label_en = "Updated"
        attr.save() # Should not raise
        self.assertEqual(attr.label_en, "Updated")
        attr.delete() # Should not raise
        self.assertEqual(CommodityAttributeDefinition.objects.count(), 0)

    def test_cannot_mutate_attribute_of_published_schema(self):
        pub_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        # Bypassing clean to create it initially for testing update block
        attr = CommodityAttributeDefinition(schema_version=pub_schema, key="k2", data_type="string")
        models.Model.save(attr) # bypass custom save/clean just to inject it

        attr.label_en = "Mutate"
        with self.assertRaises(ValidationError):
            attr.save()

    def test_cannot_add_attribute_to_published_schema(self):
        pub_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        with self.assertRaises(ValidationError):
            CommodityAttributeDefinition.objects.create(
                schema_version=pub_schema, key="k3", data_type="string"
            )

    def test_cannot_delete_attribute_of_published_schema(self):
        pub_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        attr = CommodityAttributeDefinition(schema_version=pub_schema, key="k4", data_type="string")
        models.Model.save(attr)

        with self.assertRaises(ValidationError):
            attr.delete()
