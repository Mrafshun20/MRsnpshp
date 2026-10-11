# -*- coding: utf-8 -*-
import json, os, re, threading, time
from typing import Any, Dict, List, Optional

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior, ToggleButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox

import arabic_reshaper
try:
    from bidi.algorithm import get_display
except ImportError:
    from bidi import get_display

import logic

# ---------------- theme ----------------
BG = (0.055, 0.07, 0.11, 1)
BAR = (0.09, 0.11, 0.17, 1)
CARD = (0.105, 0.13, 0.20, 1)
FIELD = (0.06, 0.08, 0.13, 1)
ACC = (0.23, 0.51, 0.96, 1)
ACC2 = (0.20, 0.25, 0.36, 1)
GRN = (0.30, 0.85, 0.50, 1)
RED = (0.97, 0.40, 0.40, 1)
TXT = (0.90, 0.92, 0.96, 1)
MUT = (0.55, 0.60, 0.70, 1)

HERE = os.path.dirname(os.path.abspath(__file__))
LabelBase.register(name="fa",
                   fn_regular=os.path.join(HERE, "DejaVuSans.ttf"),
                   fn_bold=os.path.join(HERE, "DejaVuSans-Bold.ttf"))
FONT = FONT_B = "fa"
Window.clearcolor = BG
Window.softinput_mode = "below_target"

_RTL = re.compile("[\u0600-\u06FF]")

def fa(text: str) -> str:
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))

# ---------------- API ----------------
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
            if not d: break
            out.extend(d)
            if page >= res.get("meta", {}).get("pagination", {}).get("total_pages", 1): break
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
            if not b: break
            ev.extend(b)
            m = res.get("meta", {}).get("pagination", {})
            if not m.get("has_more") or not m.get("next_cursor"): break
            cursor = m["next_cursor"]
        return ev

    def get_order_details(self, vid: str, num: int):
        return self._request("GET", f"vendors/{vid}/orders/{num}")

    def get_orders_history(self, vid: str, s=None, e=None):
        p = {}
        if s: p["start_date"] = s
        if e: p["end_date"] = e
        return self._request("GET", f"vendors/{vid}/orders", params=p)

# ---------------- widgets ----------------
class Bg(BoxLayout):
    def __init__(self, color=CARD, radius=0, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*color)
            self._r = RoundedRectangle(radius=[dp(radius)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size

def lab(text, color=TXT, size=14, bold=False, halign="right"):
    l = Label(text=fa(text), font_name=FONT_B if bold else FONT, font_size=sp(size),
              color=color, halign=halign, valign="middle", size_hint_y=None)
    l.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    l.bind(texture_size=lambda i, s: setattr(i, "height", max(s[1], dp(18)) + dp(4)))
    return l

def inp(hint, text="", **kw):
    return TextInput(hint_text=fa(hint), text=text, multiline=False, font_name=FONT, font_size=sp(16),
                     size_hint_y=None, height=dp(50), padding=[dp(14), dp(14), dp(14), dp(10)],
                     background_normal="", background_active="", background_color=FIELD,
                     foreground_color=TXT, hint_text_color=MUT, cursor_color=ACC,
                     write_tab=False, **kw)

class RBtn(ButtonBehavior, Label):
    def __init__(self, text, color=ACC, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(16), color=(1, 1, 1, 1),
                         size_hint_y=None, height=dp(50), **kw)
        self._c = color
        with self.canvas.before:
            self._col = Color(*color)
            self._r = RoundedRectangle(radius=[dp(12)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size

    def on_press(self):
        self._col.rgba = tuple(c * 0.7 for c in self._c[:3]) + (1,)

    def on_release(self):
        self._col.rgba = self._c

def card(title, *widgets):
    c = Bg(color=CARD, radius=14, orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(10))
    c.bind(minimum_height=c.setter("height"))
    if title: c.add_widget(lab(title, size=15, bold=True))
    for w in widgets: c.add_widget(w)
    return c

class ProductRow(Bg):
    def __init__(self, prod, **kw):
        super().__init__(color=CARD, radius=10, orientation="vertical", size_hint_y=None, height=dp(95), padding=dp(10))
        self.prod = prod
        
        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30))
        self.chk = CheckBox(size_hint_x=None, width=dp(40), color=ACC, active=prod.sel)
        self.chk.bind(active=self.on_chk)
        top.add_widget(self.chk)
        top.add_widget(lab(f"{prod.name}", bold=True, halign="right"))
        
        mid = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(25))
        mid.add_widget(lab(f"SKU: {prod.sku}", color=MUT, halign="left"))
        
        bot = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(25))
        bot.add_widget(lab(f"قیمت: {prod.price}", color=TXT, halign="right"))
        bot.add_widget(lab(f"موجودی: {prod.stock}", color=TXT, halign="right"))
        
        if prod.lose:
            bot.add_widget(lab(f"نفر اول: {prod.comp}", color=RED, halign="left"))
        elif prod.bb:
            bot.add_widget(lab("بای‌باکس", color=GRN, halign="left"))
            
        self.add_widget(top)
        self.add_widget(mid)
        self.add_widget(bot)
        
    def on_chk(self, instance, value):
        self.prod.sel = value

class OrderRow(Bg):
    def __init__(self, order, **kw):
        super().__init__(color=CARD, radius=10, orientation="vertical", size_hint_y=None, height=dp(70), padding=dp(10))
        top = BoxLayout(orientation="horizontal")
        top.add_widget(lab(order.date, color=MUT, halign="left"))
        top.add_widget(lab(f"سفارش: {order.num}", bold=True, halign="right"))
        
        bot = BoxLayout(orientation="horizontal")
        bot.add_widget(lab(f"مبلغ: {order.total}", color=TXT, halign="left"))
        status_col = GRN if order.delivered else (ACC if order.snd else TXT)
        bot.add_widget(lab(f"وضعیت: {order.status}", color=status_col, halign="right"))
        
        self.add_widget(top)
        self.add_widget(bot)

class LogRow(BoxLayout):
    def __init__(self, ts, text, kind, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, spacing=dp(8), **kw)
        col = {"ok": GRN, "err": RED}.get(kind, TXT)
        rtl = bool(_RTL.search(text))
        t = Label(text=ts, font_name=FONT, font_size=sp(11), color=MUT, size_hint=(None, None), size=(dp(54), dp(18)), halign="left", valign="top")
        t.bind(size=lambda i, s: setattr(i, "text_size", s))
        m = Label(text=fa(text[:6000]), font_name=FONT, font_size=sp(13), color=col, halign="right" if rtl else "left", valign="top", size_hint_y=None)
        m.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        m.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
        m.bind(height=lambda i, h: setattr(self, "height", h + dp(6)))
        self.add_widget(t)
        self.add_widget(m)

class NavBtn(ToggleButtonBehavior, Label):
    def __init__(self, text, name, app, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(12), color=MUT, group="nav", allow_no_selection=False, **kw)
        self.name, self.app = name, app

    def on_state(self, _w, st):
        self.color = ACC if st == "down" else MUT
        if st == "down":
            self.app.sm.current = self.name

class StatusBar(ButtonBehavior, Label):
    pass

# ---------------- app ----------------
class SnappShopApp(App):
    title = "SnappShop"

    def build(self):
        self.api = None
        self.vendor_id = ""
        self.auto_stop = threading.Event()
        self.auto_on = False
        self.prods = []
        self.ords = []
        self.cfg_path = os.path.join(self.user_data_dir, "cfg.json")
        try: cfg = json.load(open(self.cfg_path))
        except Exception: cfg = {}

        root = BoxLayout(orientation="vertical")

        header = Bg(color=BAR, orientation="vertical", size_hint_y=None, height=dp(56))
        header.add_widget(lab("پنل اسنپ‌شاپ", size=18, bold=True, halign="center"))
        header.children[0].valign = "middle"
        root.add_widget(header)

        self.status = StatusBar(text="", font_name=FONT, font_size=sp(12), color=MUT, size_hint_y=None, height=dp(28), halign="center", shorten=True, shorten_from="right")
        self.status.bind(size=lambda i, s: setattr(i, "text_size", (s[0] - dp(16), None)))
        self.status.bind(on_release=lambda *_: setattr(self.sm, "current", "log"))
        root.add_widget(self.status)

        self.sm = ScreenManager(transition=NoTransition())

        # --- connection
        self.ent_ua = inp("کد یکتا (User-Agent)", cfg.get("ua", ""))
        self.ent_token = inp("Bearer Token", cfg.get("token", ""), password=True)
        self.ent_vid = inp("شناسه فروشگاه", cfg.get("vid", ""))
        b = RBtn("تست اتصال و دریافت شناسه فروشگاه")
        b.bind(on_release=lambda *_: self.test_connection())
        self._add("conn", self._wrap_page(card("احراز هویت", lab("کد یکتا (User-Agent)", MUT, 12), self.ent_ua, lab("توکن", MUT, 12), self.ent_token, lab("شناسه فروشگاه", MUT, 12), self.ent_vid, b)))

        # --- products
        self.ent_sku = inp("SKU / ID")
        self.ent_stock = inp("Stock", "10", input_filter="int")
        self.ent_price = inp("Price", "150000", input_filter="int")
        self.ent_delta = inp("کاهش از نفر اول (تومان)", "5000", input_filter="int")
        self.ent_floor = inp("حداقل قیمت مجاز", "0", input_filter="int")

        b1 = RBtn("دریافت لیست محصولات", ACC2)
        b1.bind(on_release=lambda *_: self.get_products())
        b2 = RBtn("به‌روزرسانی دستی کالا")
        b2.bind(on_release=lambda *_: self.update_product())
        b3 = RBtn("پیش‌نمایش و اعمال رقابت")
        b3.bind(on_release=lambda *_: self.do_undercut())

        self.prod_list = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        self.prod_list.bind(minimum_height=self.prod_list.setter('height'))

        self._add("prod", self._wrap_page(
            card("", b1),
            card("قیمت‌گذاری زیر نفر اول", lab("کاهش از نفر اول (تومان)", MUT, 12), self.ent_delta, lab("حداقل قیمت مجاز (اختیاری)", MUT, 12), self.ent_floor, b3),
            self.prod_list,
            card("ویرایش دستی با کد کالا", lab("کد کالا", MUT, 12), self.ent_sku, lab("موجودی جدید", MUT, 12), self.ent_stock, lab("قیمت جدید (تومان)", MUT, 12), self.ent_price, b2)
        ))

        # --- orders
        self.ent_ord = inp("شماره سفارش", input_filter="int")
        self.ent_sd = inp("از تاریخ: YYYY-MM-DD")
        self.ent_ed = inp("تا تاریخ: YYYY-MM-DD")
        
        o1 = RBtn("دریافت لیست سفارشات", ACC2)
        o1.bind(on_release=lambda *_: self.load_orders())
        o2 = RBtn("مشاهده جزئیات سفارش")
        o2.bind(on_release=lambda *_: self.get_order_details())
        o4 = RBtn("صدور گزارش فروش (Excel)", GRN[:3] + (1,))
        o4.color = (0.04, 0.12, 0.07, 1)
        o4.bind(on_release=lambda *_: self.export_excel())

        self.ord_list = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        self.ord_list.bind(minimum_height=self.ord_list.setter('height'))

        self._add("ord", self._wrap_page(
            card("تاریخچه سفارشات و گزارش", self.ent_sd, self.ent_ed, o1, o4),
            self.ord_list,
            card("جزئیات یک سفارش", lab("شماره سفارش", MUT, 12), self.ent_ord, o2)
        ))

        # --- auto
        self.ent_int = inp("Seconds", "60", input_filter="int")
        self.auto_lbl = lab("وضعیت: غیرفعال", MUT, 14, bold=True)
        a1 = RBtn("شروع رصد", GRN[:3] + (1,))
        a1.color = (0.04, 0.12, 0.07, 1)
        a1.bind(on_release=lambda *_: self.start_auto())
        a2 = RBtn("توقف رصد", (0.80, 0.26, 0.26, 1))
        a2.bind(on_release=lambda *_: self.stop_auto())
        self._add("auto", self._wrap_page(card("رصد خودکار رویدادها", lab("فاصله بررسی (ثانیه)", MUT, 12), self.ent_int, self.auto_lbl, a1, a2)))

        # --- log
        self.log_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4), padding=dp(12))
        self.log_box.bind(minimum_height=self.log_box.setter("height"))
        self.log_sv = ScrollView(do_scroll_x=False)
        self.log_sv.add_widget(self.log_box)
        clr = RBtn("پاک کردن گزارش", ACC2)
        clr.height = dp(42)
        clr.bind(on_release=lambda *_: self.log_box.clear_widgets())
        lp = BoxLayout(orientation="vertical", padding=[dp(12), dp(8), dp(12), 0], spacing=dp(6))
        lp.add_widget(clr)
        lp.add_widget(self.log_sv)
        self._add("log", lp)

        root.add_widget(self.sm)

        nav = Bg(color=BAR, size_hint_y=None, height=dp(56))
        self.navs = []
        for text, name in (("اتصال", "conn"), ("محصولات", "prod"), ("سفارشات", "ord"), ("رصد", "auto"), ("گزارش", "log")):
            n = NavBtn(text, name, self)
            self.navs.append(n)
            nav.add_widget(n)
        root.add_widget(nav)
        self.navs[0].state = "down"

        self.log("آماده است.")
        return root

    def _wrap_page(self, *widgets):
        sv = ScrollView(do_scroll_x=False)
        box = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for w in widgets: box.add_widget(w)
        sv.add_widget(box)
        return sv

    def _add(self, name, widget):
        s = Screen(name=name)
        s.add_widget(widget)
        self.sm.add_widget(s)

    def log(self, text, kind="info"):
        def _do(_dt):
            self.log_box.add_widget(LogRow(time.strftime("%H:%M"), text, kind))
            if len(self.log_box.children) > 150: self.log_box.remove_widget(self.log_box.children[-1])
            self.status.text = fa(text.split("\n")[0][:90])
            self.status.color = {"ok": GRN, "err": RED}.get(kind, MUT)
            Clock.schedule_once(lambda _: setattr(self.log_sv, "scroll_y", 0), 0.1)
        Clock.schedule_once(_do, 0)

    def _save(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            json.dump({"ua": self.ent_ua.text.strip(), "token": self.ent_token.text.strip(), "vid": self.ent_vid.text.strip()}, open(self.cfg_path, "w"))
        except Exception: pass

    def _setup(self):
        ua, tok = self.ent_ua.text.strip(), self.ent_token.text.strip()
        if not ua or not tok:
            self.log("User-Agent و توکن الزامی است.", "err")
            self.sm.current = "conn"
            return False
        self.api = SnappShopAutomationAPI(ua, tok)
        self.vendor_id = self.ent_vid.text.strip()
        self._save()
        return True

    def _need_vid(self):
        if not self._setup(): return False
        if not self.vendor_id:
            self.log("شناسه فروشگاه خالی است. ابتدا تست اتصال بزنید.", "err")
            self.sm.current = "conn"
            return False
        return True

    def _run(self, fn):
        def w():
            try: fn()
            except Exception as e: self.log(f"خطا: {e}", "err")
        threading.Thread(target=w, daemon=True).start()

    def _dump(self, o):
        self.log(json.dumps(o, ensure_ascii=False, indent=2))

    def test_connection(self):
        if not self._setup(): return
        def f():
            v = self.api.get_first_vendor_id()
            if v:
                self.vendor_id = v
                Clock.schedule_once(lambda _: (setattr(self.ent_vid, "text", v), self._save()), 0)
                self.log(f"اتصال موفق. شناسه فروشگاه: {v}", "ok")
            else: self.log("شناسه فروشگاهی یافت نشد.", "err")
        self.log("در حال اتصال...")
        self._run(f)

    def get_products(self):
        if not self._need_vid(): return
        def f():
            raw_prods = self.api.get_all_products(self.vendor_id)
            self.prods = [logic.norm_prod(p, i) for i, p in enumerate(raw_prods)]
            Clock.schedule_once(lambda _: self._render_products(), 0)
        self.log("در حال دریافت محصولات...")
        self._run(f)

    def _render_products(self):
        self.prod_list.clear_widgets()
        for p in self.prods:
            self.prod_list.add_widget(ProductRow(p))
        self.log(f"تعداد {len(self.prods)} محصول بارگذاری شد.", "ok")

    def update_product(self):
        if not self._need_vid(): return
        sku, st, pr = self.ent_sku.text.strip(), self.ent_stock.text.strip(), self.ent_price.text.strip()
        if not (sku and st and pr):
            self.log("کد کالا، موجودی و قیمت الزامی است.", "err")
            return
        def f():
            r = self.api.update_products(self.vendor_id, [{"sku": sku, "stock": int(st), "price": int(pr)}])
            self.log("به‌روزرسانی انجام شد.", "ok")
            self._dump(r)
        self.sm.current = "log"
        self._run(f)

    def do_undercut(self):
        if not self._need_vid(): return
        delta = int(self.ent_delta.text or 5000)
        floor = int(self.ent_floor.text or 0)

        # اگر هیچ محصولی تیک نخورده بود، اونایی که بای‌باکس رو باختن انتخاب میشن
        has_sel = any(p.sel for p in self.prods)
        if not has_sel:
            for p in self.prods:
                if p.lose: p.sel = True

        rows, skipped = logic.plan_undercut(self.prods, delta, floor)
        valid_rows = [r for r in rows if not r['why']]

        if not valid_rows:
            self.log(f"کالایی برای قیمت‌گذاری یافت نشد. ({skipped} کالا نادیده گرفته شد)", "err")
            self.sm.current = "log"
            return

        def f():
            updates = [{"sku": r['o'].sku, "price": r['np'], "stock": r['o'].stock} for r in valid_rows]
            res = self.api.update_products(self.vendor_id, updates)
            for r in valid_rows:
           
