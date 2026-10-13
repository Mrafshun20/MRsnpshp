# -*- coding: utf-8 -*-
import csv, datetime, json, ntpath, os, re, shutil, site, sys, threading, time

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
if getattr(site, "USER_BASE", None) is None:
    site.USER_BASE = HERE
if getattr(site, "USER_SITE", None) is None:
    site.USER_SITE = HERE

_orig_join = ntpath.join
def _safe_join(a, *p):
    return _orig_join(a if a is not None else HERE, *[x for x in p if x is not None])
ntpath.join = os.path.join = _safe_join

if hasattr(os, "add_dll_directory"):
    for _d in ("", "share\\sdl2\\bin", "share\\glew\\bin", "share\\angle\\bin"):
        _p = _orig_join(HERE, _d) if _d else HERE
        if os.path.isdir(_p):
            try:
                os.add_dll_directory(_p)
            except Exception:
                pass

# PyInstaller --windowed has no stdout/stderr; Kivy would crash writing to None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior, ToggleButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import arabic_reshaper
try:
    from bidi.algorithm import get_display
except ImportError:
    from bidi import get_display

from logic import (build_sales_workbook, event_line, first_array, flat, make_xlsx_multi, norm_order,
                   norm_prod, plan_auto, plan_undercut, read_mins_csv, redact, write_mins_csv)

# ---------------- theme ----------------
BG = (0.045, 0.06, 0.095, 1)
BAR = (0.075, 0.10, 0.155, 1)
CARD = (0.095, 0.125, 0.19, 1)
FIELD = (0.055, 0.075, 0.12, 1)
CHIP = (0.14, 0.18, 0.27, 1)
ACC = (0.22, 0.52, 0.98, 1)
ACC2 = (0.18, 0.23, 0.34, 1)
GRN = (0.24, 0.84, 0.52, 1)
RED = (0.96, 0.38, 0.38, 1)
AMB = (0.98, 0.74, 0.16, 1)
TXT = (0.93, 0.95, 0.98, 1)
MUT = (0.56, 0.62, 0.73, 1)

LabelBase.register(name="fa",
                   fn_regular=os.path.join(HERE, "DejaVuSans.ttf"),
                   fn_bold=os.path.join(HERE, "DejaVuSans-Bold.ttf"))
FONT = FONT_B = "fa"
Window.clearcolor = BG
Window.softinput_mode = "below_target"


def fa(text) -> str:
    if text is None or text == "":
        return ""
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))


def n(x) -> str:
    return "—" if x is None else f"{int(round(x)):,}"


def to_num_safe(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


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

    def _request(self, method: str, endpoint: str, **kw) -> Any:
        r = self.session.request(method, f"{self.BASE_URL}/{endpoint.lstrip('/')}", timeout=25, **kw)
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

    def get_order_details(self, vid: str, num) -> Any:
        return self._request("GET", f"vendors/{vid}/orders/{num}")

    def get_orders_history(self, vid: str, s=None, e=None) -> Any:
        p = {}
        if s: p["start_date"] = s
        if e: p["end_date"] = e
        return self._request("GET", f"vendors/{vid}/orders", params=p)


# ---------------- widgets ----------------
class Bg(BoxLayout):
    def __init__(self, color=CARD, radius=0, border_color=None, **kw):
        super().__init__(**kw)
        self._bcol = border_color
        with self.canvas.before:
            Color(*color)
            self._r = RoundedRectangle(radius=[dp(radius)])
            if border_color:
                Color(*border_color)
                self._ln = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(radius)), width=1.1)
            else:
                self._ln = None
        self._rad = dp(radius)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        if self._ln:
            self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, self._rad)


class Tap(ButtonBehavior, BoxLayout):
    pass


class TapBg(ButtonBehavior, Bg):
    pass


def lab(text, color=TXT, size=14, bold=False, halign="right"):
    l = Label(text=fa(text), font_name=FONT_B if bold else FONT, font_size=sp(size),
              color=color, halign=halign, valign="middle", size_hint_y=None)
    l.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    l.bind(texture_size=lambda i, s: setattr(i, "height", max(s[1], dp(18)) + dp(4)))
    return l


def inp(hint, text="", **kw):
    has_fa = bool(re.search("[\u0600-\u06FF]", str(hint)))
    h_txt = fa(hint) if has_fa else str(hint)
    return TextInput(hint_text=h_txt, text=str(text), multiline=False, font_name=FONT, font_size=sp(15),
                     halign="right" if has_fa else "left",
                     size_hint_y=None, height=dp(48), padding=[dp(14), dp(12), dp(14), dp(10)],
                     background_normal="", background_active="", background_color=FIELD,
                     foreground_color=TXT, hint_text_color=MUT, cursor_color=ACC,
                     write_tab=False, **kw)


class RBtn(ButtonBehavior, Label):
    def __init__(self, text, color=ACC, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(15), color=(1, 1, 1, 1),
                         size_hint_y=None, height=dp(48), **kw)
        self._c = color
        with self.canvas.before:
            self._col = Color(*color)
            self._r = RoundedRectangle(radius=[dp(12)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size

    def set_text(self, t):
        self.text = fa(t)

    def on_press(self):
        self._col.rgba = tuple(c * 0.72 for c in self._c[:3]) + (1,)

    def on_release(self):
        self._col.rgba = self._c


class Chip(ButtonBehavior, Label):
    def __init__(self, text, key, active=False, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(12.5),
                         color=(1, 1, 1, 1) if active else MUT, size_hint=(None, None), height=dp(36), **kw)
        self.key = key
        self.texture_update()
        self.width = self.texture_size[0] + dp(26)
        with self.canvas.before:
            Color(*(ACC if active else CHIP))
            self._r = RoundedRectangle(radius=[dp(18)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size


def chip_row():
    sv = ScrollView(size_hint_y=None, height=dp(42), do_scroll_y=False, bar_width=0)
    row = BoxLayout(orientation="horizontal", size_hint_x=None, spacing=dp(8))
    row.bind(minimum_width=row.setter("width"))
    sv.add_widget(row)
    return sv, row


def badge(text, kind):
    bg, fg = {
        "r": ((0.32, 0.11, 0.12, 1), RED),
        "g": ((0.07, 0.24, 0.14, 1), GRN),
        "o": ((0.30, 0.22, 0.07, 1), AMB),
        "n": (CHIP, (0.68, 0.76, 0.92, 1)),
    }[kind]
    l = Label(text=fa(text), font_name=FONT_B, font_size=sp(11), color=fg)
    l.texture_update()
    b = Bg(color=bg, radius=8, size_hint=(None, None), size=(l.texture_size[0] + dp(16), dp(24)))
    b.add_widget(l)
    return b


def stat_box(title, val, col=TXT):
    b = Bg(color=FIELD, radius=10, orientation="vertical", padding=[dp(8), dp(6)], spacing=dp(2))
    b.add_widget(lab(val, col, 15, bold=True, halign="center"))
    b.add_widget(lab(title, MUT, 11, halign="center"))
    return b


def vbox():
    b = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
    b.bind(minimum_height=b.setter("height"))
    return b


def card(title, *widgets):
    c = Bg(color=CARD, radius=14, border_color=(0.16, 0.21, 0.31, 1),
           orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(10))
    c.bind(minimum_height=c.setter("height"))
    if title:
        c.add_widget(lab(title, ACC, size=15, bold=True))
    for w in widgets:
        c.add_widget(w)
    return c


def page(*widgets):
    sv = ScrollView(do_scroll_x=False)
    box = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12), size_hint_y=None)
    box.bind(minimum_height=box.setter("height"))
    for w in widgets:
        box.add_widget(w)
    sv.add_widget(box)
    return sv


class LogRow(BoxLayout):
    def __init__(self, ts, text, kind, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, spacing=dp(8), **kw)
        col = {"ok": GRN, "err": RED}.get(kind, TXT)
        rtl = bool(re.search("[\u0600-\u06FF]", str(text)))
        t = Label(text=ts, font_name=FONT, font_size=sp(11), color=MUT, size_hint=(None, None),
                  size=(dp(54), dp(18)), halign="left", valign="top")
        t.bind(size=lambda i, s: setattr(i, "text_size", s))
        m = Label(text=fa(str(text)[:6000]), font_name=FONT, font_size=sp(13), color=col,
                  halign="right" if rtl else "left", valign="top", size_hint_y=None)
        m.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        m.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
        m.bind(height=lambda i, h: setattr(self, "height", h + dp(6)))
        self.add_widget(t)
        self.add_widget(m)


class NavBtn(ToggleButtonBehavior, Label):
    def __init__(self, text, name, app, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(13), color=MUT,
                         group="nav", allow_no_selection=False, **kw)
        self.name, self.app = name, app

    def on_state(self, _w, st):
        self.color = ACC if st == "down" else MUT
        if st == "down":
            self.app.sm.current = self.name


class StatusBar(ButtonBehavior, Label):
    pass


class ProdCard(Bg):
    def __init__(self, o, app, **kw):
        bcol = (0.18, 0.45, 0.30, 1) if o.bb is True else ((0.45, 0.22, 0.22, 1) if o.lose else (0.16, 0.20, 0.30, 1))
        super().__init__(color=CARD, radius=12, border_color=bcol, orientation="vertical",
                         size_hint_y=None, padding=dp(12), spacing=dp(6), **kw)
        self.o, self.app = o, app
        self.bind(minimum_height=self.setter("height"))
        top = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(10))
        top.bind(minimum_height=top.setter("height"))
        cb = CheckBox(size_hint=(None, None), size=(dp(34), dp(34)), active=o.sel)
        cb.bind(active=self._sel)
        tap = Tap(orientation="vertical", size_hint_y=None, spacing=dp(2))
        tap.bind(minimum_height=tap.setter("height"))
        title_txt = o.name + (f"  [{o.variation}]" if o.variation else "")
        tap.add_widget(lab(title_txt, bold=True, size=14))
        id_line = f"ID: {o.id}" + (f"  |  SKU: {o.real_sku}" if o.real_sku else "") + (f"  |  کد: {o.product_number}" if o.product_number else "")
        tap.add_widget(lab(id_line, MUT, 11))
        tap.bind(on_release=lambda *_: app.edit_product(o))
        top.add_widget(cb)
        top.add_widget(tap)
        self.add_widget(top)

        price_line = f"قیمت پایه: {n(o.price)}"
        if o.has_sp:
            price_line += f"   |   تخفیف‌دار: {n(o.sp)}"
        price_line += f"   |   موجودی: {n(o.stock)}"
        self.add_widget(lab(price_line, AMB if o.has_sp else TXT, size=13))

        bs = []
        if o.inactive:
            bs.append(badge("غیرفعال", "r"))
        if o.oos:
            bs.append(badge("ناموجود", "o"))
        if o.has_sp:
            bs.append(badge("تخفیف فعال", "o"))
        if o.bb is True:
            bs.append(badge(f"برنده بای‌باکس ({n(o.comp)})" if o.comp else "برنده بای‌باکس", "g"))
        elif o.lose:
            diff = int((o.eff_price or 0) - (o.comp or 0)) if (o.eff_price and o.comp) else 0
            diff_txt = f" (+{n(diff)})" if diff > 0 else ""
            bs.append(badge(f"نفر اول: {n(o.comp)}{diff_txt}" if o.comp is not None else "بدون بای‌باکس", "r"))
        min_v = app.mins.get(o.sku) or app.mins.get(o.id)
        if min_v:
            bs.append(badge(f"کف ربات: {n(min_v)}", "n"))
        if bs:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26), spacing=dp(6))
            row.add_widget(BoxLayout())
            for b in bs:
                row.add_widget(b)
            self.add_widget(row)

    def _sel(self, _i, val):
        self.o.sel = val
        self.app.upd_sel()


FILT = [("all", "همه"), ("active", "فعال"), ("inactive", "غیرفعال"), ("instock", "موجود"), ("oos", "ناموجود"),
        ("bb", "بای‌باکس دارم"), ("lose", "بای‌باکس ندارم")]


# ---------------- app ----------------
class SnappShopApp(App):
    title = "SnappShop Automation"

    def build(self):
        self.api = None
        self.vendor_id = ""
        self.bot_ev = threading.Event()
        self.bot_on = False
        self.log_lock = threading.Lock()
        self.P: List[Any] = []
        self.PF, self.Q, self.shown = "all", "", 100
        self.O: List[Any] = []
        self.OF = "all"
        self.cfg_path = os.path.join(self.user_data_dir, "cfg.json")
        self.data_dir = self.user_data_dir
        self.mins_path = os.path.join(self.data_dir, "mins.json")
        self.hist_path = os.path.join(self.data_dir, "reprice_history.csv")
        self.flog_path = os.path.join(self.data_dir, "automation.log")
        try:
            with open(self.cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        self.auto_cfg = {"bot": False, "interval": 10, "delta": 5000, "maxdrop": 15, "reqmin": True, "winstart": False}
        self.auto_cfg.update(cfg.get("auto", {}))
        try:
            with open(self.mins_path, encoding="utf-8") as f:
                self.mins = {k: float(v) for k, v in json.load(f).items()}
        except Exception:
            self.mins = {}

        root = BoxLayout(orientation="vertical")
        header = Bg(color=BAR, orientation="vertical", size_hint_y=None, height=dp(54))
        header.add_widget(lab("پنل مدیریت و اتوماسیون اسنپ‌شاپ", size=17, bold=True, halign="center"))
        root.add_widget(header)

        self.status = StatusBar(text="", font_name=FONT, font_size=sp(12), color=MUT,
                                size_hint_y=None, height=dp(28), halign="center", shorten=True, shorten_from="right")
        self.status.bind(size=lambda i, s: setattr(i, "text_size", (s[0] - dp(16), None)))
        self.status.bind(on_release=lambda *_: self.go("log"))
        root.add_widget(self.status)

        self.sm = ScreenManager(transition=NoTransition())

        # --- connection
        self.ent_ua = inp("User-Agent", cfg.get("ua", ""))
        self.ent_token = inp("Bearer Token", cfg.get("token", ""), password=True)
        self.ent_vid = inp("Vendor ID", cfg.get("vid", ""))
        b = RBtn("تست اتصال و دریافت شناسه فروشگاه")
        b.bind(on_release=lambda *_: self.test_connection())
        b2 = RBtn("دریافت نمونه داده‌ها (JSON)", ACC2)
        b2.bind(on_release=lambda *_: self.dump_samples())
        self._add("conn", page(
            card("احراز هویت API",
                 lab("کد یکتا (User-Agent)", MUT, 12), self.ent_ua,
                 lab("توکن (Bearer Token)", MUT, 12), self.ent_token,
                 lab("شناسه فروشگاه (Vendor ID)", MUT, 12), self.ent_vid, b),
            card("عیب‌یابی و استخراج ساختار",
                 lab("یک نمونه از کالا، سفارش و رویداد را دریافت و در کلیپ‌بورد کپی می‌کند.", MUT, 11), b2)))

        # --- products
        self.pstats = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(58), spacing=dp(8))
        self.pcount = lab("", MUT, 12, halign="center")
        self.pchips_sv, self.pchips = chip_row()
        self.pdet = lab("", MUT, 11)
        self.ent_q = inp("جستجو در نام، رنگ یا کد کالا", "")
        self.ent_q.bind(text=self._on_q)
        p1 = RBtn("دریافت و بروزرسانی لیست کالاها")
        p1.bind(on_release=lambda *_: self.get_products())
        p2 = RBtn("انتخاب همه", ACC2)
        p2.bind(on_release=lambda *_: self.sel_all(True))
        p3 = RBtn("لغو انتخاب", ACC2)
        p3.bind(on_release=lambda *_: self.sel_all(False))
        brow = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        brow.add_widget(p2)
        brow.add_widget(p3)
        p4 = RBtn("ویرایش گروهی کالاهای انتخاب‌شده", (0.20, 0.45, 0.85, 1))
        p4.bind(on_release=lambda *_: self.bulk_edit())
        self.ent_delta = inp("5000", "5000", input_filter="int")
        self.ent_floor = inp("0", "", input_filter="int")
        u1 = RBtn("پیش‌نمایش و اعمال قیمت زیر نفر اول")
        u1.bind(on_release=lambda *_: self.undercut())
        self.ent_sku = inp("z681wQ")
        self.ent_stock = inp("10", "10", input_filter="int")
        self.ent_price = inp("150000", "150000", input_filter="int")
        m1 = RBtn("به‌روزرسانی سریع کالا")
        m1.bind(on_release=lambda *_: self.update_product())
        self.pl = vbox()
        self.pl.spacing = dp(10)
        self._add("prod", page(
            card("مدیریت کالاها", p1, self.pstats, brow, p4, self.pcount, self.ent_q, self.pchips_sv, self.pdet),
            card("قیمت‌گذاری رقابتی (اولویت با قیمت تخفیف‌دار)",
                 lab("مبلغ کاهش نسبت به قیمت بای‌باکس (ریال)", MUT, 12), self.ent_delta,
                 lab("کف قیمت مجاز (اختیاری)", MUT, 12), self.ent_floor, u1,
                 lab("اگر کالا تخفیف داشته باشد یا قیمت جدید زیر قیمت پایه باشد، به‌عنوان قیمت تخفیف‌دار (special
