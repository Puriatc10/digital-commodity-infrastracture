import datetime
from decimal import Decimal
import unittest
import uuid

from matching.fingerprint import canonical_json_bytes, canonical_normalize, compute_fingerprint


class FingerprintUtilityTests(unittest.TestCase):
    def test_key_ordering_deterministic(self):
        """Prove {"a": 1, "b": 2} and reversed insertion order have identical fingerprints."""
        dict1 = {"a": 1, "b": 2}
        dict2 = {"b": 2, "a": 1}

        fp1 = compute_fingerprint(dict1)
        fp2 = compute_fingerprint(dict2)

        self.assertEqual(fp1, fp2)
        self.assertEqual(canonical_json_bytes(dict1), canonical_json_bytes(dict2))

    def test_nested_key_ordering_deterministic(self):
        """Prove nested dictionaries with different insertion orders yield identical fingerprints."""
        dict1 = {
            "outer_a": {"z": 1, "y": 2, "x": {"nested_b": True, "nested_a": "val"}},
            "outer_b": [1, 2, {"k2": "v2", "k1": "v1"}],
        }
        dict2 = {
            "outer_b": [1, 2, {"k1": "v1", "k2": "v2"}],
            "outer_a": {"x": {"nested_a": "val", "nested_b": True}, "y": 2, "z": 1},
        }

        self.assertEqual(compute_fingerprint(dict1), compute_fingerprint(dict2))

    def test_semantic_value_change_changes_fingerprint(self):
        """Prove that changing any value alters the resulting fingerprint."""
        base = {"a": 1, "b": "text", "c": Decimal("10.5")}
        changed_val = {"a": 2, "b": "text", "c": Decimal("10.5")}
        changed_key = {"a": 1, "b_other": "text", "c": Decimal("10.5")}

        self.assertNotEqual(compute_fingerprint(base), compute_fingerprint(changed_val))
        self.assertNotEqual(compute_fingerprint(base), compute_fingerprint(changed_key))

    def test_decimal_normalization(self):
        """Prove stable string representation of Decimals regardless of trailing zeros."""
        d1 = {"qty": Decimal("10.50")}
        d2 = {"qty": Decimal("10.5")}
        d3 = {"qty": Decimal("100.00")}
        d4 = {"qty": Decimal("100")}
        d5 = {"qty": Decimal("0.00")}
        d6 = {"qty": Decimal("-0.00")}

        self.assertEqual(compute_fingerprint(d1), compute_fingerprint(d2))
        self.assertEqual(compute_fingerprint(d3), compute_fingerprint(d4))
        self.assertEqual(compute_fingerprint(d5), compute_fingerprint(d6))

    def test_uuid_normalization(self):
        """Prove UUID normalization to canonical lowercase string representation."""
        u_str = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        u_obj = uuid.UUID(u_str)

        self.assertEqual(canonical_normalize(u_obj), u_str)
        self.assertEqual(compute_fingerprint({"id": u_obj}), compute_fingerprint({"id": u_str}))

    def test_date_and_datetime_normalization(self):
        """Prove stable representation of dates and timezone-aware datetimes."""
        d = datetime.date(2026, 9, 17)
        self.assertEqual(canonical_normalize(d), "2026-09-17")

        # Two timezone-aware datetimes at the exact same instant
        utc_dt = datetime.datetime(2026, 9, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)
        tehran_tz = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
        tehran_dt = datetime.datetime(2026, 9, 17, 15, 30, 0, tzinfo=tehran_tz)

        self.assertEqual(compute_fingerprint({"timestamp": utc_dt}), compute_fingerprint({"timestamp": tehran_dt}))

    def test_rejection_of_naive_datetime(self):
        """Prove that naive datetimes without timezone information are rejected."""
        naive_dt = datetime.datetime(2026, 9, 17, 12, 0, 0)
        with self.assertRaises(ValueError):
            canonical_normalize(naive_dt)

    def test_rejection_of_floats(self):
        """Prove that float types are rejected in favor of Decimal."""
        with self.assertRaises(TypeError):
            canonical_normalize({"score": 95.5})

    def test_rejection_of_sets(self):
        """Prove that non-deterministic unordered sets are rejected."""
        with self.assertRaises(TypeError):
            canonical_normalize({"items": {"a", "b"}})

    def test_rejection_of_arbitrary_objects(self):
        """Prove that unsupported arbitrary objects are rejected."""
        class Dummy:
            pass

        with self.assertRaises(TypeError):
            canonical_normalize({"obj": Dummy()})
