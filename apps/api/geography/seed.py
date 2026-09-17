from typing import Dict, List, Optional
from django.db import transaction

from geography.models import AreaType, GeographicArea


class SeedConflictError(Exception):
    """Raised when an existing GeographicArea has conflicting structural identity during seed."""
    pass


IRAN_COUNTRY = {
    "code": "IR",
    "area_type": AreaType.COUNTRY,
    "country_code": "IR",
    "name_en": "Iran",
    "name_fa": "ایران",
    "parent_code": None,
}

IRAN_PROVINCES: List[Dict[str, Optional[str]]] = [
    {"code": "IR-01", "name_en": "East Azerbaijan", "name_fa": "آذربایجان شرقی"},
    {"code": "IR-02", "name_en": "West Azerbaijan", "name_fa": "آذربایجان غربی"},
    {"code": "IR-03", "name_en": "Ardabil", "name_fa": "اردبیل"},
    {"code": "IR-04", "name_en": "Isfahan", "name_fa": "اصفهان"},
    {"code": "IR-05", "name_en": "Ilam", "name_fa": "ایلام"},
    {"code": "IR-06", "name_en": "Bushehr", "name_fa": "بوشهر"},
    {"code": "IR-07", "name_en": "Tehran", "name_fa": "تهران"},
    {"code": "IR-08", "name_en": "Chaharmahal and Bakhtiari", "name_fa": "چهارمحال و بختیاری"},
    {"code": "IR-10", "name_en": "Khuzestan", "name_fa": "خوزستان"},
    {"code": "IR-11", "name_en": "Zanjan", "name_fa": "زنجان"},
    {"code": "IR-12", "name_en": "Semnan", "name_fa": "سمنان"},
    {"code": "IR-13", "name_en": "Sistan and Baluchestan", "name_fa": "سیستان و بلوچستان"},
    {"code": "IR-14", "name_en": "Fars", "name_fa": "فارس"},
    {"code": "IR-15", "name_en": "Kerman", "name_fa": "کرمان"},
    {"code": "IR-16", "name_en": "Kurdistan", "name_fa": "کردستان"},
    {"code": "IR-17", "name_en": "Kermanshah", "name_fa": "کرمانشاه"},
    {"code": "IR-18", "name_en": "Kohgiluyeh and Boyer-Ahmad", "name_fa": "کهگیلویه و بویراحمد"},
    {"code": "IR-19", "name_en": "Gilan", "name_fa": "گیلان"},
    {"code": "IR-20", "name_en": "Lorestan", "name_fa": "لرستان"},
    {"code": "IR-21", "name_en": "Mazandaran", "name_fa": "مازندران"},
    {"code": "IR-22", "name_en": "Markazi", "name_fa": "مرکزی"},
    {"code": "IR-23", "name_en": "Hormozgan", "name_fa": "هرمزگان"},
    {"code": "IR-24", "name_en": "Hamadan", "name_fa": "همدان"},
    {"code": "IR-25", "name_en": "Yazd", "name_fa": "یزد"},
    {"code": "IR-26", "name_en": "Qom", "name_fa": "قم"},
    {"code": "IR-27", "name_en": "Golestan", "name_fa": "گلستان"},
    {"code": "IR-28", "name_en": "Qazvin", "name_fa": "قزوین"},
    {"code": "IR-29", "name_en": "South Khorasan", "name_fa": "خراسان جنوبی"},
    {"code": "IR-30", "name_en": "Razavi Khorasan", "name_fa": "خراسان رضوی"},
    {"code": "IR-31", "name_en": "North Khorasan", "name_fa": "خراسان شمالی"},
    {"code": "IR-32", "name_en": "Alborz", "name_fa": "البرز"},
]

PILOT_CITIES: List[Dict[str, Optional[str]]] = [
    {"code": "IR-07-THR", "parent_code": "IR-07", "name_en": "Tehran", "name_fa": "تهران"},
    {"code": "IR-07-SHH", "parent_code": "IR-07", "name_en": "Shahriar", "name_fa": "شهریار"},
    {"code": "IR-23-BND", "parent_code": "IR-23", "name_en": "Bandar Abbas", "name_fa": "بندرعباس"},
    {"code": "IR-04-ISF", "parent_code": "IR-04", "name_en": "Isfahan", "name_fa": "اصفهان"},
    {"code": "IR-32-KRJ", "parent_code": "IR-32", "name_en": "Karaj", "name_fa": "کرج"},
    {"code": "IR-26-QOM", "parent_code": "IR-26", "name_en": "Qom", "name_fa": "قم"},
]


def _upsert_area(
    *,
    code: str,
    area_type: str,
    country_code: str,
    name_en: str,
    name_fa: str,
    parent: Optional[GeographicArea] = None,
    is_active: bool = True,
) -> GeographicArea:
    existing = GeographicArea.objects.filter(code=code).first()
    if existing:
        # Check structural identity invariants
        expected_parent_id = parent.id if parent else None
        if (
            existing.area_type != area_type
            or existing.country_code != country_code
            or existing.parent_id != expected_parent_id
        ):
            raise SeedConflictError(
                f"Conflicting structural identity for existing GeographicArea code '{code}': "
                f"existing(parent_id={existing.parent_id}, type={existing.area_type}, country={existing.country_code}) vs "
                f"incoming(parent_id={expected_parent_id}, type={area_type}, country={country_code}). "
                f"Silent reparenting or structural redefinition is prohibited."
            )
        # Safe label update if needed
        dirty = False
        if existing.name_en != name_en:
            existing.name_en = name_en
            dirty = True
        if existing.name_fa != name_fa:
            existing.name_fa = name_fa
            dirty = True
        if existing.is_active != is_active:
            existing.is_active = is_active
            dirty = True
        if dirty:
            existing.save()
        return existing

    area = GeographicArea(
        code=code,
        area_type=area_type,
        country_code=country_code,
        name_en=name_en,
        name_fa=name_fa,
        parent=parent,
        is_active=is_active,
    )
    area.full_clean()
    area.save()
    return area


@transaction.atomic
def seed_iran_geography() -> Dict[str, GeographicArea]:
    """
    Deterministically and idempotently seed:
    1. Iran Country node ('IR')
    2. All 31 Iranian Provinces (ISO 3166-2:IR)
    3. Demo/pilot cities under their respective provinces
    """
    created_map: Dict[str, GeographicArea] = {}

    # 1. Iran country
    iran = _upsert_area(
        code=IRAN_COUNTRY["code"],
        area_type=IRAN_COUNTRY["area_type"],
        country_code=IRAN_COUNTRY["country_code"],
        name_en=IRAN_COUNTRY["name_en"],
        name_fa=IRAN_COUNTRY["name_fa"],
        parent=None,
    )
    created_map["IR"] = iran

    # 2. All 31 Provinces
    for prov in IRAN_PROVINCES:
        province_obj = _upsert_area(
            code=prov["code"],
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en=prov["name_en"],
            name_fa=prov["name_fa"],
            parent=iran,
        )
        created_map[prov["code"]] = province_obj

    # 3. Pilot Cities
    for city in PILOT_CITIES:
        parent_prov = created_map[city["parent_code"]]
        city_obj = _upsert_area(
            code=city["code"],
            area_type=AreaType.CITY,
            country_code="IR",
            name_en=city["name_en"],
            name_fa=city["name_fa"],
            parent=parent_prov,
        )
        created_map[city["code"]] = city_obj

    return created_map
