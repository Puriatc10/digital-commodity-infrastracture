from typing import Any, Optional

from commodities.models import CommodityAttributeDefinition
from deals.models import DealTermsSnapshot


def project_deal_specifications(terms_snapshot: DealTermsSnapshot) -> list[dict[str, Any]]:
    """
    Project dynamic specifications of a Deal using its historical schema version (Contract §71, §85, T0902).

    Critical Invariant:
    - Strictly bound to terms_snapshot.schema_version.
    - Never uses CommodityDefinition.active_schema_version.
    - Subsequent schema activations or retirements never alter Deal specification rendering.
    - Ordered deterministically by (sort_order, key).
    """
    schema_version = terms_snapshot.schema_version
    specs = terms_snapshot.specifications or {}

    attributes = (
        CommodityAttributeDefinition.objects.filter(schema_version=schema_version)
        .order_by("sort_order", "key")
    )

    projected = []
    seen_keys = set()

    for attr in attributes:
        seen_keys.add(attr.key)
        raw_val = specs.get(attr.key)

        display_val: Optional[Any] = raw_val
        if attr.data_type == CommodityAttributeDefinition.DataType.ENUM and raw_val is not None:
            options = (attr.enum_metadata or {}).get("options", [])
            for opt in options:
                if isinstance(opt, dict) and opt.get("value") == raw_val:
                    display_val = opt.get("label_fa") or opt.get("label_en") or raw_val
                    break

        unit = ""
        if isinstance(attr.unit_metadata, dict):
            unit = attr.unit_metadata.get("canonical_unit", "")

        projected.append(
            {
                "key": attr.key,
                "label_fa": attr.label_fa,
                "label_en": attr.label_en,
                "data_type": attr.data_type,
                "is_required": attr.is_required,
                "unit": unit,
                "display_group": attr.display_group,
                "sort_order": attr.sort_order,
                "raw_value": raw_val,
                "display_value": display_val,
            }
        )

    # If any keys exist in specs that are not in the schema attributes (historical safety)
    extra_keys = sorted(set(specs.keys()) - seen_keys)
    for key in extra_keys:
        val = specs.get(key)
        projected.append(
            {
                "key": key,
                "label_fa": key,
                "label_en": key,
                "data_type": "string",
                "is_required": False,
                "unit": "",
                "display_group": "additional",
                "sort_order": 9999,
                "raw_value": val,
                "display_value": val,
            }
        )

    return projected
