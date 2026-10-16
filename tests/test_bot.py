# -*- coding: utf-8 -*-
"""Bot smoke test with a fake API client (stdlib only)."""
import os, sys, tempfile, unittest, logging

TMP = tempfile.mkdtemp()
os.environ["SNAPP_BOT_DIR"] = TMP
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bot  # noqa: E402
import logic as L  # noqa: E402

RAW = [{"id": "a1", "sku": None, "stock": 5, "price": 1000, "title": "A", "product_number": 1},
       {"id": "b1", "sku": "S2", "stock": 2, "price": 2000, "title": "B", "product_number": 2}]


class FC:
    def __init__(self):
        self.sent = []

    def products(self, v):
        return RAW

    def patch_products(self, v, items):
        self.sent.append(items)
        return [{"id": i.get("id"), "sku": i.get("sku"), "status": True, "messages": []} for i in items]

    def events(self, v, c):
        return ([{"event_type": "NEW_ORDER", "order_number": 5, "event_at": "2026-10-14 10:00:00",
                  "items": [{"final_price": 700}]}], "c1")

    def orders(self, v, start=None, end=None):
        return getattr(self, "_orders", [])

    def confirm_order(self, v, number):
        raise NotImplementedError("no order-confirm endpoint in SnappShop automation API v2.1.2")


class BotTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("bot").setLevel(logging.CRITICAL)
        cfg = dict(bot.DEFAULT)
        cfg.update({"user_agent": "u", "token": "t", "vendor_id": "v", "prices_dry_run": False})
        self.b = bot.Bot(cfg)
        self.b.client = FC()

    def test_prices_csv_applies_and_is_undoable(self):
        with open(bot.PRICES, "w", encoding="utf-8-sig") as f:
            f.write("sku,id,price,stock\n,a1,1100,4\nS2,,2000,2\n")
        self.b.sync_prices()
        self.assertEqual(self.b.client.sent[0], [{"id": "a1", "price": 1100, "stock": 4}])
        store = L.UndoStore(bot.P("undo.json"))
        e = store.last()
        self.assertEqual(e["n"], 1)
        items, _, _ = L.revert_items(e)
        self.assertEqual(items, [{"id": "a1", "price": 1000, "stock": 5}])

    def test_order_event_logged_in_persian(self):
        self.b.state["events_init"] = True
        self.b.poll_events()
        with open(bot.ORDERS_LOG, encoding="utf-8-sig") as f:
            txt = f.read()
        self.assertIn("سفارش جدید", txt)
        self.assertIn("1405/07/22", txt)

    def test_auto_confirm_off_by_default(self):
        self.b.client._orders = [{"order_number": 7, "order_status": "PENDING"}]
        self.b.auto_confirm()                       # flag off -> no-op, must not crash
        self.assertFalse(getattr(self.b, "_ac_unsupported", False))

    def test_auto_confirm_unsupported_api_warns_once(self):
        self.b.client._orders = [{"order_number": 7, "order_status": "PENDING"},
                                 {"order_number": 8, "order_status": "CONFIRMED"}]
        self.b.cfg["auto_confirm_orders"] = True
        self.b.auto_confirm()                       # confirm_order raises NotImplementedError
        self.assertTrue(self.b._ac_unsupported)
        self.b.auto_confirm()                       # second call is a silent no-op


if __name__ == "__main__":
    unittest.main()
