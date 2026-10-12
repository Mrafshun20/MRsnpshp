# -*- coding: utf-8 -*-
import csv, json, os, shutil, sys, threading, time

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
from kivy.graphics import Color, RoundedRectangle
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

from logic import (build_sales_workbook, first_array, flat, make_xlsx_multi, norm_order, norm_prod,
                   plan_auto, plan_undercut, read_mins_csv, redact, write_mins_csv)

# ---------------- theme ----------------
BG = (0.055, 0.07, 0.11, 1)
BAR = (0.09, 0.11, 0.17, 1)
CARD = (0.105, 0.13, 0.20, 1)
FIELD = (0.06, 0.08, 0.13, 1)
CHIP = (0.15, 0.19, 0.29, 1)
ACC = (0.23, 0.51, 0.96, 1)
ACC2 = (0.20, 0.25, 0.36, 1)
GRN = (0.30, 0.85, 0.50, 1)
RED = (0.97, 0.40, 0.40, 1)
AMB = (0.98, 0.75, 0.14, 1)
TXT = (0.90, 0.92, 0.96, 1)
MUT = (0.55, 0.60, 0.70, 1)

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LabelBase.register(name="fa",
                   fn_regular=os.path.join(HERE, "DejaVuSans.ttf"),
                   fn_bold=os.path.join(HERE, "DejaVuSans-Bold.ttf"))
FONT = FONT_B = "fa"
Window.clearcolor = BG
Window.softinput_mode = "below_target"


def fa(text) -> str:
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))


def n(x) -> str:
    return "—" if x is None else f"{int(round(x)):,}"


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
        r = self.session.request(method, f"{self.BASE_URL}/{endpoint.lstrip('/')}", timeout=20, **kw)
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
    def __init__(self, color=CARD, radius=0, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*color)
            self._r = RoundedRectangle(radius=[dp(radius)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size


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
    return TextInput(hint_text=hint, text=text, multiline=False, font_name=FONT, font_size=sp(16),
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

    def set_text(self, t):
        self.text = fa(t)

    def on_press(self):
        self._col.rgba = tuple(c * 0.7 for c in self._c[:3]) + (1,)

    def on_release(self):
        self._col.rgba = self._c


class Chip(ButtonBehavior, Label):
    def __init__(self, text, key, active=False, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(13),
                         color=(1, 1, 1, 1) if active else MUT, size_hint=(None, None), height=dp(36), **kw)
        self.key = key
        self.texture_update()
        self.width = self.texture_size[0] + dp(28)
        with self.canvas.before:
            Color(*(ACC if active else CHIP))
            self._r = RoundedRectangle(radius=[dp(18)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size


def chip_row():
    sv = ScrollView(size_hint_y=None, height=dp(44), do_scroll_y=False, bar_width=0)
    row = BoxLayout(orientation="horizontal", size_hint_x=None, spacing=dp(8))
    row.bind(minimum_width=row.setter("width"))
    sv.add_widget(row)
    return sv, row


def badge(text, kind):
    bg, fg = {"r": ((0.30, 0.11, 0.11, 1), RED), "g": ((0.07, 0.21, 0.12, 1), GRN),
              "o": ((0.29, 0.21, 0.07, 1), AMB), "n": (CHIP, (0.62, 0.71, 0.88, 1))}[kind]
    l = Label(text=fa(text), font_name=FONT_B, font_size=sp(11), color=fg)
    l.texture_update()
    b = Bg(color=bg, radius=8, size_hint=(None, None), size=(l.texture_size[0] + dp(16), dp(22)))
    b.add_widget(l)
    return b


def vbox():
    b = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
    b.bind(minimum_height=b.setter("height"))
    return b


def card(title, *widgets):
    c = Bg(color=CARD, radius=14, orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(10))
    c.bind(minimum_height=c.setter("height"))
    if title:
        c.add_widget(lab(title, size=15, bold=True))
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
        import re
        col = {"ok": GRN, "err": RED}.get(kind, TXT)
        rtl = bool(re.search("[\u0600-\u06FF]", text))
        t = Label(text=ts, font_name=FONT, font_size=sp(11), color=MUT, size_hint=(None, None),
                  size=(dp(54), dp(18)), halign="left", valign="top")
        t.bind(size=lambda i, s: setattr(i, "text_size", s))
        m = Label(text=fa(text[:6000]), font_name=FONT, font_size=sp(13), color=col,
                  halign="right" if rtl else "left", valign="top", size_hint_y=None)
        m.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        m.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
        m.bind(height=lambda i, h: setattr(self, "height", h + dp(6)))
        self.add_widget(t)
        self.add_widget(m)


class NavBtn(ToggleButtonBehavior, Label):
    def __init__(self, text, name, app, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(12), color=MUT,
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
        super().__init__(color=CARD, radius=12, orientation="vertical", size_hint_y=None,
                         padding=dp(10), spacing=dp(6), **kw)
        self.o, self.app = o, app
        self.bind(minimum_height=self.setter("height"))
        top = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(10))
        top.bind(minimum_height=top.setter("height"))
        cb = CheckBox(size_hint=(None, None), size=(dp(34), dp(34)), active=o.sel)
        cb.bind(active=self._sel)
        tap = Tap(orientation="vertical", size_hint_y=None)
        tap.bind(minimum_height=tap.setter("height"))
        tap.add_widget(lab(o.name, bold=True, size=14))
        tap.add_widget(lab(o.sku, MUT, 11))
        tap.bind(on_release=lambda *_: app.edit_product(o))
        top.add_widget(cb)
        top.add_widget(tap)
        self.add_widget(top)
        self.add_widget(lab(f"قیمت: {n(o.price)}      موجودی: {n(o.stock)}", size=13))
        bs = []
        if o.inactive: bs.append(badge("غیرفعال", "r"))
        if o.oos: bs.append(badge("ناموجود", "o"))
        if o.bb is True: bs.append(badge("بای‌باکس", "g"))
        if o.lose: bs.append(badge(f"نفر اول: {n(o.comp)}" if o.comp is not None else "بدون بای‌باکس", "n"))
        if app.mins.get(o.sku): bs.append(badge(f"حداقل ربات: {n(app.mins[o.sku])}", "n"))
        if bs:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
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
    title = "SnappShop"

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
            with open(self.cfg_path) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        self.auto_cfg = {"bot": False, "interval": 10, "delta": 5000, "maxdrop": 15, "reqmin": True, "winstart": False}
        self.auto_cfg.update(cfg.get("auto", {}))
        try:
            with open(self.mins_path) as f:
                self.mins = {k: float(v) for k, v in json.load(f).items()}
        except Exception:
            self.mins = {}

        root = BoxLayout(orientation="vertical")
        header = Bg(color=BAR, orientation="vertical", size_hint_y=None, height=dp(56))
        header.add_widget(lab("پنل اسنپ‌شاپ", size=18, bold=True, halign="center"))
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
        b2 = RBtn("دریافت نمونه داده‌ها", ACC2)
        b2.bind(on_release=lambda *_: self.dump_samples())
        self._add("conn", page(
            card("احراز هویت", lab("کد یکتا (User-Agent)", MUT, 12), self.ent_ua,
                 lab("توکن", MUT, 12), self.ent_token, lab("شناسه فروشگاه", MUT, 12), self.ent_vid, b),
            card("نمونه داده‌ها",
                 lab("یک نمونه از کالا، سفارش و رویداد را می‌گیرد (نام، تلفن و آدرس مشتری پنهان می‌شود) و کپی می‌کند تا برای تنظیم دقیق‌تر بفرستید.", MUT, 11), b2)))

        # --- products
        self.pcount = lab("", MUT, 12, halign="center")
        self.pchips_sv, self.pchips = chip_row()
        self.pdet = lab("", MUT, 11)
        self.ent_q = inp("جستجو در نام یا SKU")
        self.ent_q.bind(text=self._on_q)
        p1 = RBtn("بروزرسانی لیست")
        p1.bind(on_release=lambda *_: self.get_products())
        p2 = RBtn("انتخاب همه", ACC2)
        p2.bind(on_release=lambda *_: self.sel_all(True))
        p3 = RBtn("لغو انتخاب", ACC2)
        p3.bind(on_release=lambda *_: self.sel_all(False))
        brow = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50), spacing=dp(8))
        brow.add_widget(p2)
        brow.add_widget(p3)
        p4 = RBtn("ویرایش گروهی کالاهای انتخاب‌شده", (0.20, 0.45, 0.85, 1))
        p4.bind(on_release=lambda *_: self.bulk_edit())
        self.ent_delta = inp("5000", "5000", input_filter="int")
        self.ent_floor = inp("0", "", input_filter="int")
        u1 = RBtn("پیش‌نمایش و اعمال")
        u1.bind(on_release=lambda *_: self.undercut())
        self.ent_sku = inp("SKU")
        self.ent_stock = inp("Stock", "10", input_filter="int")
        self.ent_price = inp("Price", "150000", input_filter="int")
        m1 = RBtn("به‌روزرسانی کالا")
        m1.bind(on_release=lambda *_: self.update_product())
        self.pl = vbox()
        self.pl.spacing = dp(10)
        self._add("prod", page(
            card("", p1, brow, p4, self.pcount, self.ent_q, self.pchips_sv, self.pdet),
            card("قیمت‌گذاری زیر نفر اول",
                 lab("کاهش از نفر اول (تومان)", MUT, 12), self.ent_delta,
                 lab("حداقل قیمت مجاز (اختیاری)", MUT, 12), self.ent_floor, u1,
                 lab("روی کالاهای انتخاب‌شده اعمال می‌شود؛ اگر چیزی انتخاب نشده باشد، روی همه‌ی «بای‌باکس ندارم». قبل از ارسال، لیست تغییرات را می‌بینید و تأیید می‌کنید.", MUT, 11)),
            self.pl,
            card("ویرایش دستی با کد کالا", self.ent_sku, self.ent_stock, self.ent_price, m1)))

        # --- orders
        self.ent_sd = inp("YYYY-MM-DD")
        self.ent_ed = inp("YYYY-MM-DD")
        self.ent_ord = inp("Order Number", input_filter="int")
        o1 = RBtn("نمایش لیست سفارشات")
        o1.bind(on_release=lambda *_: self.load_orders())
        o2 = RBtn("گزارش فروش (Excel)", (0.20, 0.65, 0.35, 1))
        o2.bind(on_release=lambda *_: self.export_sales())
        o3 = RBtn("رویدادهای زنده سفارشات", ACC2)
        o3.bind(on_release=lambda *_: self.get_events())
        o4 = RBtn("جزئیات سفارش")
        o4.bind(on_release=lambda *_: self.get_order())
        self.ochips_sv, self.ochips = chip_row()
        self.ol = vbox()
        self.ol.spacing = dp(10)
        self._add("ord", page(
            card("سفارشات و گزارش فروش", lab("از تاریخ", MUT, 12), self.ent_sd,
                 lab("تا تاریخ", MUT, 12), self.ent_ed, o1, o2),
            self.ochips_sv, self.ol,
            card("ابزارها", o3, lab("شماره سفارش", MUT, 12), self.ent_ord, o4)))

        # --- bot (automation)
        c = self.auto_cfg
        self.ent_bi = inp("Minutes", str(c["interval"]), input_filter="int")
        self.ent_bd = inp("Toman", str(c["delta"]), input_filter="int")
        self.ent_bm = inp("%", str(c["maxdrop"]), input_filter="int")
        self.reqmin_btn = RBtn("", ACC2)
        self._reqmin_text()
        self.reqmin_btn.bind(on_release=lambda *_: self.toggle_reqmin())
        self.bot_lbl = lab("وضعیت ربات: خاموش", MUT, 14, bold=True)
        self.bot_last = lab("", MUT, 12)
        bs1 = RBtn("روشن کردن ربات", (0.30, 0.85, 0.50, 1))
        bs1.color = (0.04, 0.12, 0.07, 1)
        bs1.bind(on_release=lambda *_: self.start_bot())
        bs2 = RBtn("خاموش کردن ربات", (0.80, 0.26, 0.26, 1))
        bs2.bind(on_release=lambda *_: self.stop_bot())
        bs3 = RBtn("اجرای یک‌باره همین الان", ACC2)
        bs3.bind(on_release=lambda *_: self.bot_once(False))
        bs4 = RBtn("پیش‌نمایش بدون اعمال (پیشنهاد می‌شود اول این را بزنید)", (0.20, 0.45, 0.85, 1))
        bs4.bind(on_release=lambda *_: self.bot_once(True))
        bot_card = card("ربات قیمت‌گذاری خودکار (زیر نفر اول)",
                        lab("هر چند دقیقه یک بار بررسی کند", MUT, 12), self.ent_bi,
                        lab("چند تومان زیر نفر اول", MUT, 12), self.ent_bd,
                        lab("حداکثر افت قیمت در هر بار (درصد)", MUT, 12), self.ent_bm,
                        self.reqmin_btn, self.bot_lbl, self.bot_last, bs4, bs1, bs2, bs3,
                        lab("ربات فقط کالاهایی را که بای‌باکس ندارند، فعال و موجودند و قیمت نفر اول‌شان معلوم است تغییر می‌دهد، آن هم فقط اگر قیمت جدید از «حداقل قیمت» کمتر نشود. هر تغییر در تاریخچه ثبت می‌شود.", MUT, 11))
        self.mins_lbl = lab("", MUT, 12)
        mcards = [self.mins_lbl]
        if platform != "android":
            mb1 = RBtn("ساخت فایل حداقل قیمت (CSV برای Excel)", ACC2)
            mb1.bind(on_release=lambda *_: self.export_mins())
            mb2 = RBtn("بارگذاری حداقل قیمت‌ها از فایل", ACC2)
            mb2.bind(on_release=lambda *_: self.import_mins())
            mcards += [mb1, mb2]
        mb3 = RBtn("پاک کردن همه‌ی حداقل قیمت‌ها", (0.55, 0.22, 0.22, 1))
        mb3.bind(on_release=lambda *_: self.clear_mins())
        mcards.append(mb3)
        mins_card = card("حداقل قیمت هر کالا", *mcards)
        hb = RBtn("تاریخچه‌ی قیمت‌گذاری ربات (Excel)", ACC2)
        hb.bind(on_release=lambda *_: self.export_history())
        cards_bot = [bot_card, mins_card, card("گزارش", hb)]
        if platform == "win":
            self.winstart_btn = RBtn("", ACC2)
            self._winstart_text()
            self.winstart_btn.bind(on_release=lambda *_: self.toggle_winstart())
            cards_bot.append(card("ویندوز", self.winstart_btn,
                                  lab("وقتی ربات روشن است، ویندوز به حالت خواب نمی‌رود. برنامه را ببندید ربات هم متوقف می‌شود؛ می‌توانید آن را Minimize کنید.", MUT, 11)))
        self._add("auto", page(*cards_bot))
        self.upd_mins_lbl()

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
        for text, name in (("اتصال", "conn"), ("محصولات", "prod"), ("سفارشات", "ord"), ("ربات", "auto"), ("گزارش", "log")):
            nb = NavBtn(text, name, self)
            self.navs.append(nb)
            nav.add_widget(nb)
        root.add_widget(nav)
        self.navs[0].state = "down"

        self.render_products()
        self.render_orders()
        self.log("آماده است.")
        if self.auto_cfg.get("bot") and cfg.get("ua") and cfg.get("token") and cfg.get("vid"):
            Clock.schedule_once(lambda dt: self.start_bot(), 2)
            if platform == "win" and "--minimized" in sys.argv:
                Clock.schedule_once(lambda dt: self._minimize(), 3)
        return root

    def _add(self, name, widget):
        s = Screen(name=name)
        s.add_widget(widget)
        self.sm.add_widget(s)

    def go(self, name):
        for nb in self.navs:
            if nb.name == name:
                nb.state = "down"

    # ---- threading / ui helpers
    def ui(self, fn):
        def w(_dt):
            try:
                fn()
            except Exception as e:
                self.log(f"خطا: {e}", "err")
        Clock.schedule_once(w, 0)

    def _run(self, fn):
        def w():
            try:
                fn()
            except Exception as e:
                self.log(f"خطا: {e}", "err")
        threading.Thread(target=w, daemon=True).start()

    def _flog(self, text, kind):
        try:
            with self.log_lock:
                os.makedirs(self.data_dir, exist_ok=True)
                if os.path.exists(self.flog_path) and os.path.getsize(self.flog_path) > 1_000_000:
                    os.replace(self.flog_path, self.flog_path + ".1")
                with open(self.flog_path, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " [" + kind + "] " + text.replace("\n", " | ")[:600] + "\n")
        except Exception:
            pass

    def log(self, text, kind="info"):
        self._flog(text, kind)
        def _do(_dt):
            self.log_box.add_widget(LogRow(time.strftime("%H:%M"), text, kind))
            if len(self.log_box.children) > 150:
                self.log_box.remove_widget(self.log_box.children[-1])
            self.status.text = fa(text.split("\n")[0][:90])
            self.status.color = {"ok": GRN, "err": RED}.get(kind, MUT)
            Clock.schedule_once(lambda _: setattr(self.log_sv, "scroll_y", 0), 0.1)
        Clock.schedule_once(_do, 0)

    # ---- modal
    def modal(self, title, sub, body, buttons, h=0.86):
        mv = ModalView(size_hint=(0.94, h), auto_dismiss=True, background="", background_color=(0, 0, 0, 0),
                       overlay_color=(0, 0, 0, 0.65))
        box = Bg(color=CARD, radius=16, orientation="vertical", padding=dp(14), spacing=dp(10))
        box.add_widget(lab(title, size=16, bold=True))
        if sub:
            box.add_widget(lab(sub, MUT, 12))
        sv = ScrollView(do_scroll_x=False)
        sv.add_widget(body)
        box.add_widget(sv)
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50), spacing=dp(8))
        btns = []
        for text, color, cb in buttons:
            bt = RBtn(text, color)
            def _rel(_b, cb=cb):
                r = cb() if cb else None
                if r is not False:
                    mv.dismiss()
            bt.bind(on_release=_rel)
            row.add_widget(bt)
            btns.append(bt)
        box.add_widget(row)
        mv.add_widget(box)
        mv.open()
        return mv, btns

    # ---- credentials
    def _save(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.cfg_path, "w") as f:
                json.dump({"ua": self.ent_ua.text.strip(), "token": self.ent_token.text.strip(),
                           "vid": self.ent_vid.text.strip(), "auto": self.auto_cfg}, f)
        except Exception:
            pass

    def _setup(self):
        ua, tok = self.ent_ua.text.strip(), self.ent_token.text.strip()
        if not ua or not tok:
            self.log("User-Agent و توکن الزامی است.", "err")
            self.go("conn")
            return False
        self.api = SnappShopAutomationAPI(ua, tok)
        self.vendor_id = self.ent_vid.text.strip()
        self._save()
        return True

    def _need_vid(self):
        if not self._setup():
            return False
        if not self.vendor_id:
            self.log("شناسه فروشگاه خالی است. ابتدا تست اتصال بزنید.", "err")
            self.go("conn")
            return False
        return True

    def test_connection(self):
        if not self._setup():
            return
        def f():
            v = self.api.get_first_vendor_id()
            if v:
                def done():
                    self.vendor_id = v
                    self.ent_vid.text = v
                    self._save()
                    self.log(f"اتصال موفق. شناسه فروشگاه: {v}", "ok")
                self.ui(done)
            else:
                self.log("شناسه فروشگاهی یافت نشد.", "err")
        self.log("در حال اتصال...")
        self._run(f)

    # ---- products
    def passf(self, o):
        f = self.PF
        if f == "active": return o.active is True
        if f == "instock": return o.stock is not None and o.stock > 0
        if f == "inactive": return o.inactive
        if f == "oos": return o.oos
        if f == "bb": return o.bb is True
        if f == "lose": return o.lose
        return True

    def vis(self):
        q = self.Q
        return [o for o in self.P if self.passf(o) and (not q or q in (o.name + " " + o.sku).lower())]

    def _on_q(self, _i, val):
        self.Q = val.strip().lower()
        Clock.unschedule(self._q_apply)
        Clock.schedule_once(self._q_apply, 0.35)

    def _q_apply(self, _dt):
        self.shown = 100
        self.render_products()

    def set_pf(self, key):
        self.PF, self.shown = key, 100
        self.render_products()

    def _match(self, key, o):
        return (key == "all" or (key == "active" and o.active is True) or (key == "inactive" and o.inactive)
                or (key == "instock" and o.stock is not None and o.stock > 0) or (key == "oos" and o.oos)
                or (key == "bb" and o.bb is True) or (key == "lose" and o.lose))

    def render_pchips(self):
        self.pchips.clear_widgets()
        any_bb = any(o.bb is not None for o in self.P)
        any_act = any(o.active is not None for o in self.P)
        any_comp = any(o.comp is not None for o in self.P)
        for key, label in FILT:
            cnt = sum(1 for o in self.P if self._match(key, o))
            unk = (key in ("inactive", "active") and not any_act) or (key == "bb" and not any_bb) or (key == "lose" and not any_bb and not any_comp)
            ch = Chip(f"{label}  {'؟' if unk else cnt}", key, active=(self.PF == key))
            ch.bind(on_release=lambda c: self.set_pf(c.key))
            self.pchips.add_widget(ch)
        if self.P:
            d = self.P[0].det
            self.pdet.text = fa("فیلدها — " + " · ".join(f"{k}: {v if v else 'پیدا نشد'}" for k, v in d.items()))
        else:
            self.pdet.text = ""

    def render_products(self):
        self.render_pchips()
        self.pl.clear_widgets()
        L = self.vis()
        for o in L[:self.shown]:
            self.pl.add_widget(ProdCard(o, self))
        if len(L) > self.shown:
            more = RBtn(f"نمایش بیشتر ({n(len(L) - self.shown)})", ACC2)
            more.bind(on_release=lambda *_: self._more())
            self.pl.add_widget(more)
        if not L:
            self.pl.add_widget(lab("موردی پیدا نشد." if self.P else "برای نمایش، «بروزرسانی لیست» را بزنید.", MUT, 13, halign="center"))
        self.upd_sel()

    def _more(self):
        self.shown += 100
        self.render_products()

    def upd_sel(self):
        k = sum(1 for o in self.P if o.sel)
        self.pcount.text = fa((f"{n(len(self.vis()))} کالا" + (f" · {n(k)} انتخاب" if k else "")) if self.P else "")

    def sel_all(self, on):
        for o in self.vis():
            o.sel = on
        self.render_products()

    def get_products(self):
        if not self._need_vid():
            return
        def f():
            raw = self.api.get_all_products(self.vendor_id)
            def done():
                self.P = [norm_prod(p, i) for i, p in enumerate(raw)]
                self.PF, self.shown = "all", 100
                self.render_products()
                nb = sum(1 for o in self.P if o.lose)
                has = any(o.bb is not None or o.comp is not None for o in self.P)
                self.log(f"تعداد محصولات: {len(raw)}" + (f" · بدون بای‌باکس: {nb}" if has else ""), "ok")
            self.ui(done)
        self.log("در حال دریافت محصولات...")
        self._run(f)

    @staticmethod
    def _clean(item):
        out = {}
        for k, v in item.items():
            if v is None:
                continue
            out[k] = int(v) if k in ("price", "stock") else v
        return out

    def edit_product(self, o):
        ep = inp("Price", "" if o.price is None else str(int(o.price)), input_filter="int")
        es = inp("Stock", "" if o.stock is None else str(int(o.stock)), input_filter="int")
        em = inp("Min", str(int(self.mins[o.sku])) if o.sku in self.mins else "", input_filter="int")
        body = vbox()
        for w in (lab("قیمت (تومان)", MUT, 12), ep, lab("موجودی", MUT, 12), es,
                  lab("حداقل قیمت برای ربات (اختیاری)", MUT, 12), em):
            body.add_widget(w)
        def save():
            pr = int(ep.text) if ep.text.strip() else None
            st = int(es.text) if es.text.strip() else None
            mn = int(em.text) if em.text.strip() else None
            if o.sku:
                if mn:
                    self.mins[o.sku] = float(mn)
                else:
                    self.mins.pop(o.sku, None)
                self._save_mins()
                self.upd_mins_lbl()
            unchanged = (pr is None or pr == o.price) and (st is None or st == o.stock)
            if unchanged:
                self.render_products()
                self.log(f"ذخیره شد: {o.sku}", "ok")
                return
            if not self._need_vid():
                return False
            if not o.sku:
                self.log("کد کالا (SKU) پیدا نشد.", "err")
                return False
            item = self._clean({"sku": o.sku, "price": pr if pr is not None else o.price,
                                "stock": st if st is not None else o.stock})
            def f():
                self.api.update_products(self.vendor_id, [item])
                def done():
                    o.price, o.stock = item.get("price"), item.get("stock")
                    o.calc()
                    self.render_products()
                    self.log(f"ذخیره شد: {o.sku}", "ok")
                self.ui(done)
            self._run(f)
        self.modal(o.name, o.sku, body, [("انصراف", ACC2, None), ("ذخیره", ACC, save)], h=0.72)

    @staticmethod
    def _fnum(text):
        try:
            return float(text.strip().replace(",", ""))
        except Exception:
            return None

    def bulk_edit(self):
        sel = [o for o in self.P if o.sel]
        if not sel:
            self.log("ابتدا کالاهای مورد نظر را انتخاب کنید (تیک بزنید).", "err")
            return
        if not self._need_vid():
            return
        e_pct, e_amt = inp("مثلاً -5 یا 3"), inp("مثلاً -5000")
        e_stk, e_min = inp("مثلاً 10"), inp("مثلاً 10")
        body = vbox()
        for w in (lab("تغییر قیمت: درصد (منفی = کاهش)", MUT, 12), e_pct,
                  lab("تغییر قیمت: مبلغ تومان (منفی = کاهش)", MUT, 12), e_amt,
                  lab("تنظیم موجودی روی عدد", MUT, 12), e_stk,
                  lab("حداقل قیمت ربات = چند درصد پایین‌تر از قیمت (جدید) کالا", MUT, 12), e_min):
            body.add_widget(w)
        def apply():
            pct, amt = self._fnum(e_pct.text), self._fnum(e_amt.text)
            stk, mp = self._fnum(e_stk.text), self._fnum(e_min.text)
            if pct is None and amt is None and stk is None and mp is None:
                self.log("هیچ تغییری وارد نشده است.", "err")
                return False
            if pct is not None and abs(pct) > 50:
                self.log("تغییر قیمت بیش از ۵۰٪ مجاز نیست.", "err")
                return False
            if stk is not None and stk < 0:
                self.log("موجودی نمی‌تواند منفی باشد.", "err")
                return False
            if mp is not None and not (0 <= mp < 100):
                self.log("درصد حداقل قیمت باید بین ۰ و ۱۰۰ باشد.", "err")
                return False
            changes = []
            for o in sel:
                newp = o.price
                if o.price is not None and (pct is not None or amt is not None):
                    v = o.price
                    if pct is not None:
                        v = v * (1 + pct / 100)
                    if amt is not None:
                        v = v + amt
                    newp = int(round(v))
                    if newp <= 0:
                        continue
                news = int(stk) if stk is not None else o.stock
                if mp is not None and o.sku and newp is not None:
                    self.mins[o.sku] = float(int(round(newp * (1 - mp / 100))))
                if o.sku and (newp != o.price or news != o.stock):
                    changes.append((o, newp, news))
            self._save_mins()
            self.upd_mins_lbl()
            if not changes:
                for o in sel:
                    o.sel = False
                self.render_products()
                self.log("حداقل قیمت‌ها ثبت شد." if mp is not None else "تغییری لازم نبود.", "ok")
                return
            items = [self._clean({"sku": o.sku, "price": p, "stock": st}) for o, p, st in changes]
            self.go("log")
            self.log(f"در حال اعمال ویرایش گروهی روی {len(items)} کالا...")
            def f():
                self.api.update_products(self.vendor_id, items)
                def done():
                    for o, p, st in changes:
                        o.price, o.stock = p, st
                        o.calc()
                    for o in sel:
                        o.sel = False
                    self.render_products()
                    self.log(f"ویرایش گروهی روی {len(items)} کالا انجام شد.", "ok")
                self.ui(done)
            self._run(f)
        self.modal("ویرایش گروهی", f"{n(len(sel))} کالا انتخاب شده است. فقط فیلدهای پرشده اعمال می‌شود.", body,
                   [("انصراف", ACC2, None), ("اعمال", ACC, apply)], h=0.8)

    def update_product(self):
        if not self._need_vid():
            return
        sku, st, pr = self.ent_sku.text.strip(), self.ent_stock.text.strip(), self.ent_price.text.strip()
        if not (sku and st and pr):
            self.log("کد کالا، موجودی و قیمت الزامی است.", "err")
            return
        def f():
            r = self.api.update_products(self.vendor_id, [{"sku": sku, "stock": int(st), "price": int(pr)}])
            self.log("به‌روزرسانی انجام شد.\n" + json.dumps(r, ensure_ascii=False, indent=2), "ok")
        self._run(f)

    # ---- undercut
    @staticmethod
    def _int(text, default=0):
        try:
            return int(text.strip())
        except Exception:
            return default

    def undercut(self):
        if not self.P:
            self.log("ابتدا لیست محصولات را بروزرسانی کنید.", "err")
            return
        if not any(o.comp is not None for o in self.P):
            self.log("قیمت نفر اول در داده‌های API پیدا نشد. «دریافت نمونه داده‌ها» را بزنید و برای تنظیم بفرستید.", "err")
            return
        if not self._need_vid():
            return
        delta = self._int(self.ent_delta.text, 5000)
        floor = self._int(self.ent_floor.text, 0)
        rows, skipped = plan_undercut(self.P, delta, floor)
        if not rows:
            self.log("کالایی برای قیمت‌گذاری پیدا نشد." + (f" ({skipped} کالا بدون قیمت نفر اول)" if skipped else ""), "err")
            return
        rows = rows[:300]
        body = vbox()
        checks = []
        for r in rows:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
            row.bind(minimum_height=row.setter("height"))
            cb = CheckBox(size_hint=(None, None), size=(dp(30), dp(30)), active=not r["why"], disabled=bool(r["why"]))
            checks.append(cb)
            txt = r["o"].name + (("\n" + r["why"]) if r["why"] else "")
            t = lab(txt, MUT if r["why"] else TXT, 13)
            v = lab(f"{n(r['o'].price)} ← {n(r['np'])}", TXT, 12, halign="left")
            v.size_hint_x = None
            v.width = dp(150)
            row.add_widget(cb)
            row.add_widget(t)
            row.add_widget(v)
            body.add_widget(row)
        ok = sum(1 for r in rows if not r["why"])
        sub = f"هر قیمت {n(delta)} تومان زیر نفر اول" + (f" · {n(skipped)} کالا بدون قیمت نفر اول نادیده گرفته شد" if skipped else "")
        def apply():
            chosen = [r for r, cb in zip(rows, checks) if cb.active and not r["why"]]
            if not chosen:
                return
            self.go("log")
            self.log(f"در حال اعمال قیمت‌ها روی {len(chosen)} کالا...")
            items = [self._clean({"sku": r["o"].sku, "price": r["np"], "stock": r["o"].stock}) for r in chosen]
            def f():
                self.api.update_products(self.vendor_id, items)
                def done():
                    for r in chosen:
                        r["o"].price = r["np"]
                        r["o"].sel = False
                        r["o"].calc()
                    self.render_products()
                    self.log(f"قیمت {len(chosen)} کالا بروزرسانی شد. برای دیدن وضعیت بای‌باکس، لیست را بروزرسانی کنید.", "ok")
                self.ui(done)
            self._run(f)
        mv, btns = self.modal("پیش‌نمایش قیمت‌گذاری", sub, body,
                              [("انصراف", ACC2, None), (f"اعمال روی {n(ok)} کالا", ACC, apply)])
        def upd(*_):
            k = sum(1 for r, cb in zip(rows, checks) if cb.active and not r["why"])
            btns[1].set_text(f"اعمال روی {n(k)} کالا")
        for cb in checks:
            cb.bind(active=upd)

    # ---- orders
    def _orders_list(self):
        r = self.api.get_orders_history(self.vendor_id, self.ent_sd.text.strip() or None, self.ent_ed.text.strip() or None)
        d = r.get("data", r) if isinstance(r, dict) else r
        if not isinstance(d, list):
            d = first_array(d) if isinstance(d, dict) else None
        return d or []

    def render_orders(self):
        self.ochips.clear_widgets()
        self.ol.clear_widgets()
        if self.O:
            cnt, snd = {}, 0
            for o in self.O:
                cnt[o.status] = cnt.get(o.status, 0) + 1
                snd += 1 if o.snd else 0
            def addc(label, key, c):
                ch = Chip(f"{label}  {c}", key, active=(self.OF == key))
                ch.bind(on_release=lambda x: self.set_of(x.key))
                self.ochips.add_widget(ch)
            addc("همه", "all", len(self.O))
            addc("ارسال‌شده، تحویل‌نشده", "snd", snd)
            for s, c in cnt.items():
                addc(s or "—", "st:" + s, c)
        L = [o for o in self.O if self.OF == "all" or (self.OF == "snd" and o.snd) or self.OF == "st:" + o.status]
        for o in L[:150]:
            c = TapBg(color=CARD, radius=12, orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(4))
            c.bind(minimum_height=c.setter("height"))
            c.add_widget(lab(f"سفارش {o.num}", bold=True, size=14))
            c.add_widget(lab(o.date, MUT, 11))
            meta = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            meta.add_widget(BoxLayout())
            if o.total is not None:
                tl = lab(f"مبلغ: {n(o.total)}", TXT, 13)
                tl.size_hint_x = None
                tl.width = dp(150)
                meta.add_widget(tl)
            if o.status:
                meta.add_widget(badge(o.status, "g" if o.delivered else "o" if o.snd else "n"))
            c.add_widget(meta)
            c.bind(on_release=lambda w, num=o.num: self.open_order(num))
            self.ol.add_widget(c)
        if len(L) > 150:
            self.ol.add_widget(lab("فقط ۱۵۰ مورد اول نمایش داده شد.", MUT, 11, halign="center"))
        if not L:
            self.ol.add_widget(lab("موردی پیدا نشد." if self.O else "برای نمایش، «نمایش لیست سفارشات» را بزنید.", MUT, 13, halign="center"))

    def set_of(self, key):
        self.OF = key
        self.render_orders()

    def load_orders(self):
        if not self._need_vid():
            return
        def f():
            d = self._orders_list()
            def done():
                self.O = [norm_order(o, i) for i, o in enumerate(d)]
                self.OF = "all"
                self.render_orders()
                self.log(f"تعداد سفارشات: {len(self.O)} · ارسال‌شده و تحویل‌نشده: {sum(1 for o in self.O if o.snd)}", "ok")
            self.ui(done)
        self.log("در حال دریافت سفارشات...")
        self._run(f)

    def open_order(self, num):
        if not self._need_vid():
            return
        def f():
            r = self.api.get_order_details(self.vendor_id, num)
            d = r.get("data", r) if isinstance(r, dict) else r
            def done():
                body = vbox()
                body.spacing = dp(2)
                rows = [(k, v) for k, v in flat(d) if not isinstance(v, (dict, list))][:120]
                for k, v in rows:
                    row = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
                    row.bind(minimum_height=row.setter("height"))
                    kl = lab(k, MUT, 11, halign="left")
                    kl.size_hint_x = 0.42
                    vl = lab(str(v), TXT, 12, halign="right")
                    row.add_widget(kl)
                    row.add_widget(vl)
                    body.add_widget(row)
                arr = first_array(d) if isinstance(d, dict) else None
                sub = f"{len(arr)} ردیف کالا در سفارش" if arr else ""
                self.modal(f"سفارش {num}", sub, body, [("بستن", ACC2, None)])
            self.ui(done)
        self._run(f)

    def get_order(self):
        num = self.ent_ord.text.strip()
        if not num:
            self.log("شماره سفارش را وارد کنید.", "err")
            return
        self.open_order(num)

    def get_events(self):
        if not self._need_vid():
            return
        def f():
            e = self.api.get_all_latest_events(self.vendor_id)
            self.log(f"تعداد رویدادها: {len(e)}", "ok")
            if e:
                self.log(json.dumps(e, ensure_ascii=False, indent=2))
        self.go("log")
        self._run(f)

    # ---- Excel sales report
    def save_shared(self, path):
        try:
            from androidstorage4kivy import SharedStorage
            r = SharedStorage().copy_to_shared(path)
            if r:
                return str(r)
        except Exception as e:
            self.log(f"ذخیره‌ی مشترک ناموفق بود: {e}", "err")
        try:
            dst = "/storage/emulated/0/Download/" + os.path.basename(path)
            shutil.copy(path, dst)
            return dst
        except Exception:
            return path

    def write_report(self, name, data):
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.out_dir(), name)
        with open(path, "wb") as fh:
            fh.write(data)
        return self.save_shared(path) if platform == "android" else path

    def export_sales(self):
        if not self._need_vid():
            return
        def f():
            d = self._orders_list()
            if not d:
                self.log("سفارشی در این بازه پیدا نشد.", "err")
                return
            if not any(first_array(o) for o in d[:3]):
                ids = [norm_order(o, 0).num for o in d[:500]]
                self.log(f"ردیف کالاها در لیست نیست؛ دریافت جزئیات {len(ids)} سفارش...")
                def one(k):
                    try:
                        r = self.api.get_order_details(self.vendor_id, ids[k])
                        return r.get("data", r) if isinstance(r, dict) else r
                    except Exception:
                        return d[k]
                with ThreadPoolExecutor(4) as ex:
                    d = list(ex.map(one, range(len(ids))))
            data = build_sales_workbook(d)
            shown = self.write_report("sales-" + time.strftime("%Y-%m-%d") + ".xlsx", data)
            self.log(f"گزارش آماده شد (۳ شیت: ریز سفارشات، خلاصه کالا، خلاصه روزانه): {len(d)} سفارش.\n{shown}", "ok")
        self.go("log")
        self.log("در حال دریافت سفارشات برای گزارش...")
        self._run(f)

    # ---- sample data (redacted)
    def dump_samples(self):
        if not self._need_vid():
            return
        def f():
            S: Dict[str, Any] = {}
            try:
                p = self.api._request("GET", f"vendors/{self.vendor_id}/products", params={"page": 1})
                S["products_sample"] = (p.get("data") or [])[:2]
                S["products_meta"] = p.get("meta")
            except Exception as e:
                S["products_error"] = str(e)
            try:
                S["events_sample"] = (self.api._request("GET", f"vendors/{self.vendor_id}/orders/events").get("data") or [])[:2]
            except Exception as e:
                S["events_error"] = str(e)
            try:
                o = self.api.get_orders_history(self.vendor_id)
                od = o.get("data", o) if isinstance(o, dict) else o
                S["orders_sample"] = od[:2] if isinstance(od, list) else od
                if isinstance(od, list) and od:
                    num = norm_order(od[0], 0).num
                    if num:
                        S["order_detail_sample"] = self.api.get_order_details(self.vendor_id, num)
            except Exception as e:
                S["orders_error"] = str(e)
            txt = json.dumps(redact(S), ensure_ascii=False, indent=1)
            def done():
                try:
                    Clipboard.copy(txt)
                    copied = True
                except Exception:
                    copied = False
                self.log(txt[:5000] + ("\n..." if len(txt) > 5000 else ""))
                self.log("نمونه‌ها " + ("کپی شد؛ در چت Paste کنید." if copied else "آماده شد (کپی نشد؛ از گزارش انتخاب کنید)."), "ok")
            self.ui(done)
        self.go("log")
        self.log("در حال دریافت نمونه‌ها...")
        self._run(f)

    # ---- bot (unattended automation)
    def _reqmin_text(self):
        self.reqmin_btn.set_text("فقط کالاهای دارای حداقل قیمت: " + ("بله" if self.auto_cfg["reqmin"] else "خیر"))

    def toggle_reqmin(self):
        self.auto_cfg["reqmin"] = not self.auto_cfg["reqmin"]
        self._reqmin_text()
        self._save()
        if not self.auto_cfg["reqmin"]:
            self.log("هشدار: بدون حداقل قیمت، ربات فقط به سقف افت درصدی تکیه می‌کند.", "err")

    def _save_mins(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.mins_path, "w") as f:
                json.dump(self.mins, f)
        except Exception:
            pass

    def upd_mins_lbl(self):
        self.mins_lbl.text = fa(f"حداقل قیمت ثبت‌شده برای {n(len(self.mins))} کالا")

    def clear_mins(self):
        self.mins.clear()
        self._save_mins()
        self.upd_mins_lbl()
        self.render_products()
        self.log("همه‌ی حداقل قیمت‌ها پاک شد.", "ok")

    def out_dir(self):
        if platform == "android":
            return self.data_dir
        d = os.path.join(os.path.expanduser("~"), "Documents", "SnappShop")
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            return self.data_dir

    def export_mins(self):
        if not self.P:
            self.log("ابتدا در صفحه‌ی محصولات «بروزرسانی لیست» را بزنید.", "err")
            return
        path = os.path.join(self.out_dir(), "min_prices.csv")
        write_mins_csv(path, self.P, self.mins)
        self.log("فایل ساخته شد:\n" + path + "\nدر Excel ستون min_price را پر کنید، با همین فرمت CSV ذخیره کنید و «بارگذاری» بزنید.", "ok")

    def import_mins(self):
        path = os.path.join(self.out_dir(), "min_prices.csv")
        if not os.path.exists(path):
            self.log("فایل پیدا نشد: " + path, "err")
            return
        try:
            m = read_mins_csv(path)
        except Exception as e:
            self.log(f"خواندن فایل ناموفق بود: {e}", "err")
            return
        self.mins.update(m)
        self._save_mins()
        self.upd_mins_lbl()
        self.render_products()
        self.log(f"حداقل قیمت {len(m)} کالا از فایل بارگذاری شد.", "ok")

    def _read_bot_cfg(self):
        c = self.auto_cfg
        c["interval"] = max(2, self._int(self.ent_bi.text, 10))
        c["delta"] = max(0, self._int(self.ent_bd.text, 5000))
        c["maxdrop"] = min(90, max(1, self._int(self.ent_bm.text, 15)))

    def _set_bot_label(self, on):
        self.bot_lbl.text = fa("وضعیت ربات: روشن" if on else "وضعیت ربات: خاموش")
        self.bot_lbl.color = GRN if on else MUT

    def _keep_awake(self, on):
        if platform != "win":
            return
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
        except Exception:
            pass

    def _minimize(self):
        try:
            Window.minimize()
        except Exception:
            pass

    def _winstart_text(self):
        self.winstart_btn.set_text("اجرا با روشن شدن ویندوز: " + ("بله" if self.auto_cfg.get("winstart") else "خیر"))

    def toggle_winstart(self):
        on = not self.auto_cfg.get("winstart")
        if on and not getattr(sys, "frozen", False):
            self.log("این گزینه فقط در نسخه‌ی EXE کار می‌کند.", "err")
            return
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            if on:
                winreg.SetValueEx(k, "SnappShopAuto", 0, winreg.REG_SZ, '"' + sys.executable + '" --minimized')
            else:
                try:
                    winreg.DeleteValue(k, "SnappShopAuto")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(k)
        except Exception as e:
            self.log(f"تنظیم اجرای خودکار ناموفق بود: {e}", "err")
            return
        self.auto_cfg["winstart"] = on
        self._save()
        self._winstart_text()
        self.log("اجرا با روشن شدن ویندوز " + ("فعال شد." if on else "غیرفعال شد."), "ok")

    def _history(self, changes):
        new = not os.path.exists(self.hist_path)
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.hist_path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "sku", "name", "old_price", "new_price", "competitor_price"])
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            for c in changes:
                w.writerow([now, c["sku"], c["name"], c["old"], c["new"], c["comp"]])

    def reprice_cycle(self, dry=False):
        raw = self.api.get_all_products(self.vendor_id)
        P = [norm_prod(p, i) for i, p in enumerate(raw)]
        if not any(o.comp is not None for o in P):
            self.log("ربات: قیمت نفر اول در داده‌های API پیدا نشد. «دریافت نمونه داده‌ها» را بزنید و برای تنظیم بفرستید.", "err")
            return
        c = self.auto_cfg
        changes, skips = plan_auto(P, int(c["delta"]), self.mins, float(c["maxdrop"]), bool(c["reqmin"]))
        by = {o.sku: o for o in P}
        if dry:
            for ch in changes[:15]:
                self.log(f"{ch['sku']} {ch['name'][:30]}: {n(ch['old'])} ← {n(ch['new'])} (نفر اول {n(ch['comp'])})")
        elif changes:
            items = [self._clean({"sku": x["sku"], "price": x["new"], "stock": by[x["sku"]].stock}) for x in changes]
            self.api.update_products(self.vendor_id, items)
            self._history(changes)
        losing = sum(1 for o in P if o.lose)
        sk = " · ".join(f"{k}: {len(v)}" for k, v in skips.items())
        self.log(("پیش‌نمایش ربات" if dry else "ربات") + f": {len(P)} کالا · بدون بای‌باکس {losing} · "
                 + ("قابل تغییر " if dry else "تغییر ") + str(len(changes)) + (f" · نادیده — {sk}" if sk else ""),
                 "ok" if changes else "info")
        if not dry:
            stamp = fa(f"آخرین اجرا: {time.strftime('%H:%M')} — {len(changes)} تغییر قیمت")
            self.ui(lambda: setattr(self.bot_last, "text", stamp))

    def bot_once(self, dry=False):
        if not self._need_vid():
            return
        self._read_bot_cfg()
        self._save()
        self.go("log")
        self.log("در حال اجرای ربات (یک بار)...")
        self._run(lambda: self.reprice_cycle(dry=dry))

    def start_bot(self):
        if self.bot_on:
            return
        if not self._need_vid():
            return
        self._read_bot_cfg()
        if self.auto_cfg["reqmin"] and not self.mins:
            self.log("هیچ حداقل قیمتی ثبت نشده؛ تا آن موقع ربات هیچ کالایی را تغییر نمی‌دهد. (محصولات ← ویرایش گروهی ← حداقل قیمت)", "err")
        self.auto_cfg["bot"] = True
        self._save()
        ev = threading.Event()
        self.bot_ev = ev
        self.bot_on = True
        self._set_bot_label(True)
        self._keep_awake(True)
        iv = self.auto_cfg["interval"]
        self.log(f"ربات روشن شد؛ هر {iv} دقیقه بررسی می‌کند.", "ok")
        def loop():
            while not ev.is_set():
                try:
                    self.reprice_cycle()
                except Exception as e:
                    self.log(f"خطا در ربات: {e}", "err")
                ev.wait(iv * 60)
        threading.Thread(target=loop, daemon=True).start()

    def stop_bot(self):
        self.bot_ev.set()
        self.bot_on = False
        self.auto_cfg["bot"] = False
        self._save()
        self._set_bot_label(False)
        self._keep_awake(False)
        self.log("ربات خاموش شد.")

    def export_history(self):
        if not os.path.exists(self.hist_path):
            self.log("هنوز تغییری توسط ربات ثبت نشده است.", "err")
            return
        with open(self.hist_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        cols = ["time", "sku", "name", "old_price", "new_price", "competitor_price"]
        for r in rows:
            for k in ("old_price", "new_price", "competitor_price"):
                try:
                    r[k] = float(r[k])
                except Exception:
                    pass
        data = make_xlsx_multi([("تاریخچه ربات", cols, rows)])
        shown = self.write_report("reprice-history-" + time.strftime("%Y-%m-%d") + ".xlsx", data)
        self.log(f"تاریخچه‌ی {len(rows)} تغییر ذخیره شد:\n{shown}", "ok")

    def on_pause(self):
        return True


if __name__ == "__main__":
    SnappShopApp().run()
