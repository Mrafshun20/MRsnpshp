import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import licensing as L

TSEC = "test-secret-123"


class Keys(unittest.TestCase):
    def test_roundtrip_all_plans(self):
        today = datetime.date(2026, 10, 18)
        for plan, (label, days) in L.PLANS.items():
            k = L.make_key(TSEC, plan, today)
            self.assertTrue(k.startswith("SSV-"), k)
            ok, p, exp, err = L.validate_key(k, TSEC, today)
            self.assertTrue(ok, (plan, err))
            self.assertEqual(p, plan)
            self.assertEqual(exp, (today + datetime.timedelta(days=days)).isoformat())

    def test_tampered_rejected(self):
        k = L.make_key(TSEC, "m", datetime.date(2026, 10, 18))
        bad = k[:-1] + ("A" if k[-1] != "A" else "B")
        ok, _, _, _ = L.validate_key(bad, TSEC, datetime.date(2026, 10, 18))
        self.assertFalse(ok)

    def test_wrong_secret_rejected(self):
        k = L.make_key(TSEC, "m", datetime.date(2026, 10, 18))
        ok, _, _, _ = L.validate_key(k, "other-secret", datetime.date(2026, 10, 18))
        self.assertFalse(ok)

    def test_expired_rejected(self):
        k = L.make_key(TSEC, "t", datetime.date(2026, 10, 1))  # 7-day trial
        ok, _, _, err = L.validate_key(k, TSEC, datetime.date(2026, 10, 18))
        self.assertFalse(ok)
        self.assertIn("منقضی", err)

    def test_bad_format(self):
        for bad in ["", "SSV-123", "not-a-key", "SSV-" + "A" * 27]:
            ok, _, _, _ = L.validate_key(bad, TSEC)
            self.assertFalse(ok, bad)

    def test_bad_plan(self):
        with self.assertRaises(ValueError):
            L.make_key(TSEC, "z")

    def test_normalize(self):
        k = L.make_key(TSEC, "m", datetime.date(2026, 10, 18))
        messy = "  " + k.lower().replace("-", " ") + " "
        ok, _, _, _ = L.validate_key(messy, TSEC, datetime.date(2026, 10, 18))
        self.assertTrue(ok)

    def test_days_left(self):
        self.assertEqual(L.days_left("2026-10-25", datetime.date(2026, 10, 18)), 7)
        self.assertEqual(L.days_left("2026-10-10", datetime.date(2026, 10, 18)), -8)


if __name__ == "__main__":
    unittest.main()
