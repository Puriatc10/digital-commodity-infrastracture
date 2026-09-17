from typing import Set
import uuid

from geography.models import GeographicArea


def are_same(area_a: GeographicArea, area_b: GeographicArea) -> bool:
    """Check if two geographic areas have the same canonical identity."""
    if not area_a or not area_b:
        return False
    if area_a.id and area_b.id and area_a.id == area_b.id:
        return True
    return bool(area_a.code and area_b.code and area_a.code == area_b.code)


def get_ancestor_ids(area: GeographicArea) -> Set[uuid.UUID]:
    """
    Return all ancestor UUIDs of the given area by traversing parent links.
    Given max depth 3 in v1 (Country -> Admin Area -> City), this is O(1).
    """
    ancestor_ids = set()
    curr = area.parent
    while curr is not None:
        if curr.id:
            ancestor_ids.add(curr.id)
        curr = curr.parent
    return ancestor_ids


def get_ancestor_codes(area: GeographicArea) -> Set[str]:
    """Return all ancestor codes of the given area."""
    ancestor_codes = set()
    curr = area.parent
    while curr is not None:
        if curr.code:
            ancestor_codes.add(curr.code)
        curr = curr.parent
    return ancestor_codes


def is_ancestor(ancestor: GeographicArea, descendant: GeographicArea) -> bool:
    """Return True if `ancestor` is an ancestor of `descendant`."""
    if not ancestor or not descendant:
        return False
    if ancestor.id:
        return ancestor.id in get_ancestor_ids(descendant)
    return ancestor.code in get_ancestor_codes(descendant)


def is_descendant(descendant: GeographicArea, ancestor: GeographicArea) -> bool:
    """Return True if `descendant` is a descendant of `ancestor`."""
    return is_ancestor(ancestor, descendant)


def contains_area(container: GeographicArea, contained: GeographicArea) -> bool:
    """
    Return True if `container` contains `contained` (either identical or ancestor).
    For example, Tehran Province contains Shahriar.
    """
    if are_same(container, contained):
        return True
    return is_ancestor(container, contained)


def get_area_and_descendant_ids(area: GeographicArea) -> Set[uuid.UUID]:
    """
    Return the area ID and all its descendant IDs in the database.
    Optimized for max-depth 3 hierarchy.
    """
    area_ids = {area.id}
    children = GeographicArea.objects.filter(parent=area).values_list("id", flat=True)
    child_ids = set(children)
    area_ids.update(child_ids)
    if child_ids:
        grandchild_ids = GeographicArea.objects.filter(parent_id__in=child_ids).values_list("id", flat=True)
        area_ids.update(grandchild_ids)
    return area_ids
