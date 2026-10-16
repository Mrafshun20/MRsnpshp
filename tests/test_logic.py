# -*- coding: utf-8 -*-
"""Run:  python -m unittest discover -s tests -v     (stdlib only; no Kivy needed)"""
import datetime
import os
import sys
import tempfile
import unittest
import zipfile
import io
import xml.dom.minidom

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import logic as L  # noqa: E402

# trimmed from the real sample data supplied with the project (names/ids kept, customer data absent)
P1 = {"id": "vQk5oX", "vendor_product_info_id": "b8eGeJ", "sku": None, "product_number": 1741151696, "active": True,
      "stock": 8, "warehouse_stock": 0, "title": "اپیلاتور بانوان وی جی آر مدل v-722", "title_en": "VGR V-722 Women's Epilator",
      "price": 5600000, "is_buy_box": True, "is_blacklist": False, "buy_box": 3390000,
      "discount": {"special_price": 3390000, "stock": 8, "vendor_share": 2210000, "percent": 40,
                   "start_at": "2026-10-10 14:31:00", "end_at": "2027-01-20 23:59:00"},
      "variation_attributes": [{"attribute": {"title": "رنگ"}, "value": {"title": "قرمز"}}]}
P2 = {"id": "z681wQ", "vendor_product_info_id": "e8bW9d", "sku": None, "product_number": 1905871355, "active": True,
      "stock": 1, "warehouse_stock": 0, "title": "ماشین اصلاح سر و صورت وی جی آر مدل 906", "price": 6890000,
      "buy_box": 6150000, "is_blacklist": False, "discount": None,
      "variation_attributes": [{"attribute": {"title": "رنگ"}, "value": {"title": "طلایی - مشکی"}}]}
ORDER = {"order_number": 92537881, "created_at": "2026-09-14 02:46:04", "delivery_type": "NORMAL",
         "order_status": "CONFIRMED", "pickup_time": {"start": "2026-09-17 09:00:00", "end": "2026-09-17 18:00:00"},
         "items": [{"sku": None, "product_number": 1741151696, "inventory_product_id": "vQk5oX",
                    "vendor_product_info_id": "b8eGeJ", "item_status": "CONFIRMED", "quantity": 2,
                    "canceled_quantity": 1, "original_price": 10000000, "discount_amount": 2730000,
                    "final_price": 7270000},
                   {"sku": None, "product_number": 111, "inventory_product_id": "zz", "vendor_product_info_id": "e8bW9d",
                    "item_status": "CONFIRMED", "quantity": 1, "canceled_quantity": 0, "final_price": 5}]}


class FakeClient:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def patch_products(self, vid, items):
        self.sent.append(items)
        return [{"id": it.get("id"), "sku": it.get("sku"), "status": (it.get("sku") or it.get("id")) not in self.fail,
                 "messages": ["nope"] if (it.get("sku") or it.get("id")) in self.fail else []} for it in items]


class Dates(unittest.TestCase):
    def test_roundtrip(self):
        d = datetime.date(1990, 1, 1)
        while d < datetime.date(2060, 1, 1):
            self.assertEqual(L.j2g(*L.g2j(d.year, d.month, d.day)), (d.year, d.month, d.day), d)
            d += datetime.timedelta(days=7)

    def test_known(self):
        self.assertEqual(L.g2j(2026, 10, 12), (1405, 7, 20))
        self.assertEqual(L.parse_date("1405/07/20"), datetime.date(2026, 10, 12))
        self.assertEqual(L.parse_date("۱۴۰۵-۰۷-۲۰"), datetime.date(2026, 10, 12))
        self.assertEqual(L.parse_date("2026-10-12"), datetime.date(2026, 10, 12))
        self.assertEqual(L.parse_date(" 2026/1/2 "), datetime.date(2026, 1, 2))

    def test_bad(self):
        for t in ("", "abc", "2026-13-01", "1405/13/01", "1405/07/31", "2026-02-30", "26-1-1"):
            with self.assertRaises(ValueError, msg=t):
                L.parse_date(t)


class Text(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(L.norm_fa("كتاب يك ۱۲٣"), "کتاب یک 123")
        self.assertEqual(L.norm_fa("می‌خواهم"), "میخواهم")

    def test_search(self):
        p = L.norm_prod(P1)
        self.assertTrue(L.match_query(p, "اپیلاتور"))
        self.assertTrue(L.match_query(p, "اپيلاتور وی جی"))      # Arabic yeh typed
        self.assertTrue(L.match_query(p, "قرمز 722"))
        self.assertTrue(L.match_query(p, "VGR"))
        self.assertFalse(L.match_query(p, "اصلاح"))
        self.assertTrue(L.match_query(p, ""))

    def test_unshape(self):
        # logical "لاا" shaped = lam-alef ligature U+FEFB + final alef U+FE8E; visual order (RTL run) is reversed.
        rev = lambda s: s[::-1]
        self.assertEqual(L.unshape_line("\ufe8e\ufefb", rev), "\u0644\u0627\u0627")
        self.assertEqual(L.unshape_line("abc 123", lambda s: s), "abc 123")


class Products(unittest.TestCase):
    now = "2026-10-15 12:00:00"

    def test_fields(self):
        p = L.norm_prod(P1)
        self.assertEqual((p.key, p.sku, p.id, p.vpi), ("vQk5oX", "", "vQk5oX", "b8eGeJ"))
        self.assertEqual(p.variant, "رنگ: قرمز")
        self.assertEqual(p.discount_state(self.now), "active")
        self.assertEqual(p.eff_price(self.now), 3390000)
        self.assertEqual(p.buybox_state(self.now), "win")
        q = L.norm_prod(P2)
        self.assertIsNone(q.discount_state(self.now))
        self.assertEqual(q.buybox_state(self.now), "lose")

    def test_discount_states(self):
        p = L.norm_prod(P1)
        self.assertEqual(p.discount_state("2026-10-09 10:00:00"), "scheduled")
        self.assertEqual(p.discount_state("2026-10-10"), "active")
        self.assertEqual(p.discount_state("2027-01-20 23:59:00"), "active")
        self.assertEqual(p.discount_state("2027-01-21 00:00:00"), "expired")
        self.assertEqual(p.discount_state("2027-01-21"), "expired")
        self.assertTrue(p.has_discount("2026-10-15"))
        self.assertFalse(p.has_discount("2027-02-01"))

    def test_filters(self):
        ps = [L.norm_prod(P1), L.norm_prod(P2)]
        t = "2026-10-15"
        self.assertEqual([p.id for p in ps if L.match(p, "bbwin", 3, t)], ["vQk5oX"])
        self.assertEqual([p.id for p in ps if L.match(p, "bblose", 3, t)], ["z681wQ"])
        self.assertEqual([p.id for p in ps if L.match(p, "low", 3, t)], ["z681wQ"])
        self.assertEqual([p.id for p in ps if L.match(p, "disc", 3, t)], ["vQk5oX"])

    def test_item_uses_id_when_no_sku(self):
        p = L.norm_prod(P1)
        self.assertEqual(p.item(price=5000000, stock=3), {"id": "vQk5oX", "price": 5000000, "stock": 3})

    def test_index_and_report(self):
        ps = [L.norm_prod(P1), L.norm_prod(P2)]
        ix = L.ProdIndex(ps)
        self.assertEqual(ix.find(ORDER["items"][0]).id, "vQk5oX")       # by product_number
        self.assertEqual(ix.find(ORDER["items"][1]).id, "z681wQ")       # only vendor_product_info_id matches
        data = L.build_sales_workbook([ORDER], ps, 3)
        z = zipfile.ZipFile(io.BytesIO(data))
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                xml.dom.minidom.parseString(z.read(n))                  # well-formed
        sheet1 = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("اپیلاتور", sheet1)
        self.assertIn("ماشین اصلاح", sheet1)


class Undo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = L.UndoStore(os.path.join(self.tmp, "sub", "undo.json"))

    def _change(self, prod, **kw):
        b = L.snap(prod)
        item = prod.item(**kw)
        return b, item

    def test_price_stock_roundtrip(self):
        p = L.norm_prod(P1)
        pair = self._change(p, price=5000000, stock=3)
        e = L.make_undo_entry("test", [pair])
        self.assertEqual(e["n"], 1)
        self.assertEqual(e["items"][0]["after"]["price"], 5000000)
        items, rem, skipped = L.revert_items(e)
        self.assertEqual(items, [{"id": "vQk5oX", "price": 5600000, "stock": 8}])   # discount untouched
        self.assertEqual((rem, skipped), (0, 0))

    def test_no_change_not_recorded(self):
        p = L.norm_prod(P1)
        e = L.make_undo_entry("x", [self._change(p)])
        self.assertEqual(e["n"], 0)
        self.store.push(e)
        self.assertIsNone(self.store.last())

    def test_discount_restore_and_removal(self):
        p1, p2 = L.norm_prod(P1), L.norm_prod(P2)
        extra = dict(special_price=2000000, special_price_start_at="2026-10-15", special_price_end_at="2026-10-20", special_price_stock=5)
        e = L.make_undo_entry("disc", [self._change(p1, **extra), self._change(p2, special_price=6000000,
                              special_price_start_at="2026-10-15", special_price_end_at="2026-10-20")])
        items, rem, _ = L.revert_items(e, today=datetime.date(2026, 10, 15))
        by = {i["id"]: i for i in items}
        self.assertEqual(by["vQk5oX"], {"id": "vQk5oX", "price": 5600000, "stock": 8, "special_price": 3390000,
                         "special_price_start_at": "2026-10-10", "special_price_end_at": "2027-01-20", "special_price_stock": 8})
        self.assertEqual(rem, 1)                                    # p2 had no discount before -> end it
        self.assertEqual(by["z681wQ"]["special_price_end_at"], "2026-10-14")
        self.assertEqual(by["z681wQ"]["special_price_start_at"], "2026-10-14")

    def test_store_push_cap_and_pop(self):
        p = L.norm_prod(P1)
        for i in range(25):
            self.store.push(L.make_undo_entry(f"e{i}", [self._change(p, price=1000 + i)]))
        h = self.store.history()
        self.assertEqual(len(h), L.UndoStore.MAX_ENTRIES)
        self.assertEqual(h[-1]["label"], "e24")
        self.store.remove(h[-1]["id"])
        self.assertEqual(self.store.last()["label"], "e23")

    def test_run_undo_partial_failure_keeps_failed(self):
        p1, p2 = L.norm_prod(P1), L.norm_prod(P2)
        self.store.push(L.make_undo_entry("bulk", [self._change(p1, price=1), self._change(p2, price=2)]))
        c = FakeClient(fail={"z681wQ"})
        r = L.run_undo(c, "v", self.store)
        self.assertEqual(r["ok"], 1)
        self.assertEqual(r["bad"], [("z681wQ", "nope")])
        self.assertEqual([x["id"] for x in r["restored"]], ["vQk5oX"])
        left = self.store.last()
        self.assertEqual([x["id"] for x in left["items"]], ["z681wQ"])
        r2 = L.run_undo(FakeClient(), "v", self.store)                  # retry succeeds, journal empties
        self.assertEqual(r2["ok"], 1)
        self.assertIsNone(self.store.last())
        self.assertIsNone(L.run_undo(FakeClient(), "v", self.store))

    def test_patch_outcome_matching(self):
        items = [{"id": "a", "price": 1, "stock": 1}, {"sku": "S", "price": 1, "stock": 1}]
        self.assertEqual(L.patch_outcome(items, [{"id": "a", "status": True}, {"sku": "S", "status": False, "messages": ["m"]}]),
                         [(True, ""), (False, "m")])
        # API answers with ids we never sent -> positional
        self.assertEqual(L.patch_outcome(items, [{"id": "x1", "status": True}, {"id": "x2", "status": False, "messages": []}]),
                         [(True, ""), (False, "failed")])
        self.assertEqual(L.patch_outcome(items, []), [(True, ""), (True, "")])

    def test_describe(self):
        p = L.norm_prod(P1)
        e = L.make_undo_entry("x", [self._change(p, price=5000000, stock=3)])
        txt = L.describe_change(e["items"][0])
        self.assertIn("5,000,000 به 5,600,000", txt)
        self.assertIn("موجودی 3 به 8", txt)


class Filters2(unittest.TestCase):
    def test_combined_filters_and_url(self):
        ps = [L.norm_prod(P1), L.norm_prod(P2), L.norm_prod(dict(P2, id="z2", active=False))]
        t = "2026-10-15"
        both = [p.id for p in ps if L.match_all(p, {"bblose", "active"}, 3, t)]
        self.assertEqual(both, ["z681wQ"])                       # loses buy box AND is active (z2 is inactive)
        self.assertEqual(L.FILTER_EXCLUSIVE["bbwin"], "bblose")
        self.assertEqual(L.norm_prod(dict(P1, parent_product_number=758717427)).url(), "https://snappshop.ir/product/758717427")
        self.assertEqual(L.norm_prod(P1).url(), "")

    def test_plan_only(self):
        p2 = L.norm_prod(P2)
        rows, _ = L.plan_undercut([p2], 5000, 0, 15, "2026-10-15", False, only=[p2])
        self.assertEqual(rows[0]["np"], 6145000)
        self.assertEqual(rows[0]["item"], {"id": "z681wQ", "price": 6145000, "stock": 1})


if __name__ == "__main__":
    unittest.main()
