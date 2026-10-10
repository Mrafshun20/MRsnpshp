# -*- coding: utf-8 -*-
import json, os, threading
from typing import Any, Dict, List, Optional

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput

import arabic_reshaper
try:
    from bidi.algorithm import get_display
except ImportError:
    from bidi import get_display

import time

# ---------- Persian font / shaping ----------
FONT = "Roboto"
for p in ("/system/fonts/NotoNaskhArabic-Regular.ttf",
          "/system/fonts/NotoSansArabic-Regular.ttf",
          "/system/fonts/DroidNaskh-Regular.ttf",
          os.path.join(os.path.dirname(__file__), "Vazirmatn.ttf")):
    if os.path.exists(p):
        LabelBase.register(name="fa", fn_regular=p)
        FONT = "fa"
        break


def fa(text: str) -> str:
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))


# ---------- API ----------
class SnappShopAutomationAPI:
    BASE_URL = "https://apix.snappshop.ir/automation/v1"

    def __init__(self, unique_id: str, bearer_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": unique_id.strip(),
            "Authorization": f"Bearer {bearer_token.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, endpoint: str, **kw) -> Dict[str, Any]:
        r = self.session.request(method, f"{self.BASE_URL}/{endpoint.lstrip('/')}", timeout=15, **kw)
        r.raise_for_status()
        return r.json()

    def get_first_vendor_id(self) -> Optional[str]:
        v = self._request("GET", "vendors").get("data", [])
        return v[0].get("id") if v else None

    def get_all_products(self, vid: str) -> List[Dict[str, Any]]:
        out, page = [], 1
        while True:
            res = self._request("GET", f"vendors/{vid}/products", params={"page": page})
            d = res.get("data", [])
            if not d:
                break
            out.extend(d)
            if page >= res.get("meta", {}).get("pagination", {}).get("total_pages", 1):
                break
            page += 1
        return out

    def update_products(self, vid: str, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for i in range(0, len(products), 50):
            res = self._request("PATCH", f"vendors/{vid}/products", json={"products": products[i:i + 50]})
            out.extend(res.get("data", []))
        return out

    def get_all_latest_events(self, vid: str) -> List[Dict[str, Any]]:
        ev, cursor = [], None
        while True:
            res = self._request("GET", f"vendors/{vid}/orders/events", params={"cursor": cursor} if cursor else {})
            b = res.get("data", [])
            if not b:
                break
            ev.extend(b)
            m = res.get("meta", {}).get("pagination", {})
            if not m.get("has_more") or not m.get("next_cursor"):
                break
            cursor = m["next_cursor"]
        return ev

    def get_order_details(self, vid: str, num: int):
        return self._request("GET", f"vendors/{vid}/orders/{num}")

    def get_orders_history(self, vid: str, s=None, e=None):
        p = {}
        if s: p["start_date"] = s
        if e: p["end_date"] = e
        return self._request("GET", f"vendors/{vid}/orders", params=p)


# ---------- UI ----------
def field(hint="", text="", **kw):
    return TextInput(hint_text=hint, text=text, multiline=False, size_hint_y=None,
                     height=dp(44), write_tab=False, **kw)


def btn(text, cb):
    b = Button(text=fa(text), font_name=FONT, size_hint_y=None, height=dp(46))
    b.bind(on_release=lambda *_: cb())
    return b


def lbl(text):
    return Label(text=fa(text), font_name=FONT, size_hint_y=None, height=dp(28), halign="right")


def tab(title, widgets):
    t = TabbedPanelItem(text=fa(title), font_name=FONT)
    sv = ScrollView()
    box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8), size_hint_y=None)
    box.bind(minimum_height=box.setter("height"))
    for w in widgets:
        box.add_widget(w)
    sv.add_widget(box)
    t.add_widget(sv)
    return t


class SnappShopApp(App):
    title = "SnappShop"

    def build(self):
        self.api = None
        self.vendor_id = ""
        self.auto_stop = threading.Event()
        self.cfg_path = os.path.join(self.user_data_dir, "cfg.json")
        cfg = {}
        try:
            cfg = json.load(open(self.cfg_path))
        except Exception:
            pass

        root = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))

        self.ent_ua = field("User-Agent (unique id)", cfg.get("ua", ""))
        self.ent_token = field("Bearer Token", cfg.get("token", ""), password=True)
        self.ent_vid = field("Vendor ID", cfg.get("vid", ""))
        top = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(44 * 4 + 6))
        for w in (self.ent_ua, self.ent_token, self.ent_vid, btn("🔍 تست اتصال و Vendor ID", self.test_connection)):
            top.add_widget(w)
        root.add_widget(top)

        tp = TabbedPanel(do_default_tab=False, tab_height=dp(40), size_hint_y=0.5)

        self.ent_sku = field("SKU / ID")
        self.ent_stock = field("Stock", "10", input_filter="int")
        self.ent_price = field("Price", "150000", input_filter="int")
        tp.add_widget(tab("📦 محصولات", [
            btn("📥 دریافت لیست محصولات", self.get_products),
            self.ent_sku, self.ent_stock, self.ent_price,
            btn("⚡ به‌روزرسانی کالا", self.update_product)]))

        self.ent_ord = field("Order Number", input_filter="int")
        self.ent_sd = field("Start YYYY-MM-DD")
        self.ent_ed = field("End YYYY-MM-DD")
        tp.add_widget(tab("🛒 سفارشات", [
            btn("⚡ رویدادهای زنده", self.get_events),
            self.ent_ord, btn("جزئیات سفارش", self.get_order_details),
            self.ent_sd, self.ent_ed, btn("جستجوی تاریخچه", self.get_history)]))

        self.ent_int = field("Interval (sec)", "60", input_filter="int")
        tp.add_widget(tab("🔄 رصد خودکار", [
            self.ent_int, btn("▶️ شروع", self.start_auto), btn("⏹️ توقف", self.stop_auto)]))
        tp.default_tab = tp.tab_list[-1]
        root.add_widget(tp)

        sv = ScrollView(size_hint_y=0.5)
        self.log_lbl = Label(text="", font_name=FONT, size_hint_y=None, halign="left", valign="top",
                             color=(0, 1, 0.79, 1), markup=False)
        self.log_lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
                          texture_size=lambda i, s: setattr(i, "height", s[1]))
        sv.add_widget(self.log_lbl)
        self.sv = sv
        self.lines: List[str] = []
        root.add_widget(sv)
        self.log("آماده است.")
        return root

    # logging (thread-safe)
    def log(self, text):
        def _do(_dt):
            self.lines.append(f"[{time.strftime('%H:%M:%S')}] {fa(text)}")
            self.lines = self.lines[-200:]
            self.log_lbl.text = "\n".join(self.lines)
            Clock.schedule_once(lambda _: setattr(self.sv, "scroll_y", 0), 0.05)
        Clock.schedule_once(_do, 0)

    def _setup(self):
        ua, tok = self.ent_ua.text.strip(), self.ent_token.text.strip()
        if not ua or not tok:
            self.log("❌ User-Agent و توکن الزامی است.")
            return False
        self.api = SnappShopAutomationAPI(ua, tok)
        self.vendor_id = self.ent_vid.text.strip()
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            json.dump({"ua": ua, "token": tok, "vid": self.vendor_id}, open(self.cfg_path, "w"))
        except Exception:
            pass
        return True

    def _need_vid(self):
        if not self._setup():
            return False
        if not self.vendor_id:
            self.log("❌ Vendor ID خالی است. ابتدا تست اتصال بزنید.")
            return False
        return True

    def _run(self, fn):
        def w():
            try:
                fn()
            except Exception as e:
                self.log(f"❌ خطا: {e}")
        threading.Thread(target=w, daemon=True).start()

    def _dump(self, o):
        self.log(json.dumps(o, ensure_ascii=False, indent=2))

    def test_connection(self):
        if not self._setup():
            return
        def f():
            v = self.api.get_first_vendor_id()
            if v:
                self.vendor_id = v
                Clock.schedule_once(lambda _: setattr(self.ent_vid, "text", v), 0)
                self.log(f"✅ اتصال موفق. Vendor ID: {v}")
            else:
                self.log("❌ شناسه فروشگاهی یافت نشد.")
        self._run(f)

    def get_products(self):
        if not self._need_vid(): return
        def f():
            p = self.api.get_all_products(self.vendor_id)
            self.log(f"✅ تعداد محصولات: {len(p)}")
            self._dump(p[:5])
        self._run(f)

    def update_product(self):
        if not self._need_vid(): return
        sku, st, pr = self.ent_sku.text.strip(), self.ent_stock.text.strip(), self.ent_price.text.strip()
        if not (sku and st and pr):
            self.log("❌ SKU، موجودی و قیمت الزامی است.")
            return
        def f():
            self._dump(self.api.update_products(self.vendor_id, [{"sku": sku, "stock": int(st), "price": int(pr)}]))
        self._run(f)

    def get_events(self):
        if not self._need_vid(): return
        def f():
            e = self.api.get_all_latest_events(self.vendor_id)
            self.log(f"✅ رویدادها: {len(e)}")
            self._dump(e)
        self._run(f)

    def get_order_details(self):
        if not self._need_vid(): return
        n = self.ent_ord.text.strip()
        if not n:
            self.log("❌ شماره سفارش را وارد کنید.")
            return
        self._run(lambda: self._dump(self.api.get_order_details(self.vendor_id, int(n))))

    def get_history(self):
        if not self._need_vid(): return
        s, e = self.ent_sd.text.strip() or None, self.ent_ed.text.strip() or None
        self._run(lambda: self._dump(self.api.get_orders_history(self.vendor_id, s, e)))

    def start_auto(self):
        if not self._need_vid(): return
        self.auto_stop.clear()
        iv = int(self.ent_int.text or 60)
        self.log(f"🔄 رصد خودکار هر {iv} ثانیه (فقط وقتی برنامه باز است)")
        def loop():
            while not self.auto_stop.is_set():
                try:
                    e = self.api.get_all_latest_events(self.vendor_id)
                    self.log(f"🔔 {len(e)} رویداد جدید" if e else "رویداد جدیدی نیست.")
                except Exception as ex:
                    self.log(f"خطا: {ex}")
                self.auto_stop.wait(iv)
        threading.Thread(target=loop, daemon=True).start()

    def stop_auto(self):
        self.auto_stop.set()
        self.log("⏹️ متوقف شد.")

    def on_pause(self):
        return True


if __name__ == "__main__":
    SnappShopApp().run()
