# -*- coding: utf-8 -*-
import datetime, json, logging, ntpath, os, shutil, site, sys, threading, time
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List

# ---- PyInstaller --windowed fixes for the Windows build (no console, no user site, DLL lookup)
_HERE0 = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
if os.name == "nt":
    if getattr(site, "USER_BASE", None) is None:
        site.USER_BASE = _HERE0
    if getattr(site, "USER_SITE", None) is None:
        site.USER_SITE = _HERE0
    _orig_join = ntpath.join
    def _safe_join(a, *p):
        return _orig_join(a if a is not None else _HERE0, *[x for x in p if x is not None])
    ntpath.join = os.path.join = _safe_join
    if hasattr(os, "add_dll_directory"):
        for _d in ("", "share\\sdl2\\bin", "share\\glew\\bin", "share\\angle\\bin"):
            _p = _orig_join(_HERE0, _d) if _d else _HERE0
            if os.path.isdir(_p):
                try:
                    os.add_dll_directory(_p)
                except Exception:
                    pass

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

import core
import logic as L

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


class GuiLogHandler(logging.Handler):
    """Shows the bot's log lines inside the app's report tab."""
    def __init__(self, app):
        super().__init__(logging.INFO)
        self.app = app
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, r):
        try:
            msg = self.format(r)
            kind = "err" if r.levelno >= logging.WARNING else ("ok" if "NEW_ORDER" in msg else "info")
            self.app.log(msg, kind)
        except Exception:
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
        tap.add_widget(lab(o.key, MUT, 11))
        tap.bind(on_release=lambda *_: app.edit_product(o))
        top.add_widget(cb)
        top.add_widget(tap)
        self.add_widget(top)
        self.add_widget(lab(f"قیمت: {n(o.price)}     موجودی: {n(o.stock)}     انبار اسنپ: {n(o.wstock)}", size=13))
        today = datetime.date.today().isoformat()
        if o.has_discount(today):
            self.add_widget(lab(f"قیمت با تخفیف: {n(o.sp)}  تا {o.sp_end[:10]}", MUT, 12))
        if o.buy_box is not None:
            self.add_widget(lab(f"قیمت باکس‌باکس: {n(o.buy_box)}" + ("  (برنده)" if o.is_bb else f"  (اختلاف: {n((o.sp if o.has_discount(today) else o.price) - o.buy_box)})"), MUT, 12))
        bs = []
        if o.active is False: bs.append(badge("غیرفعال", "r"))
        if o.stock is not None and o.stock <= 0: bs.append(badge("ناموجود", "o"))
        elif o.stock is not None and o.stock <= app.low: bs.append(badge("کم‌موجودی", "o"))
        if o.has_discount(today): bs.append(badge("تخفیف فعال", "g"))
        if o.buy_box is not None and not o.is_bb: bs.append(badge("باخته در باکس‌باکس", "o"))
        if bs:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            row.add_widget(BoxLayout())
            for b in bs:
                row.add_widget(b)
            self.add_widget(row)

    def _sel(self, _i, val):
        self.o.sel = val
        self.app.upd_sel()


# ---------------- app ----------------
class SnappShopApp(App):
    title = "SnappShop"

    def build(self):
        self.client = None
        self.vendor_id = ""
        self.P: List[Any] = []
        self.PF, self.Q, self.shown = "all", "", 100
        self.O: List[Any] = []
        self.OF = "all"
        self.watch_ev = threading.Event()
        self.watching = False
        self.data_dir = self.user_data_dir
        self.cfg_path = os.path.join(self.data_dir, "cfg.json")
        try:
            with open(self.cfg_path) as f:
                self.cfg = json.load(f)
        except Exception:
            self.cfg = {}
        self.low = int(self.cfg.get("low", 3))
        self.desktop = platform != "android"
        self.bot = self._bot_mod() if self.desktop else None
        self.bot_obj = None
        self._bot_log_ready = False

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
        self.ent_ua = inp("User-Agent", self.cfg.get("ua", ""))
        self.ent_token = inp("Bearer Token", self.cfg.get("token", ""), password=True)
        self.ent_vid = inp("Vendor ID", self.cfg.get("vid", ""))
        b = RBtn("تست اتصال و دریافت شناسه فروشگاه")
        b.bind(on_release=lambda *_: self.test_connection())
        b2 = RBtn("دریافت نمونه داده‌ها", ACC2)
        b2.bind(on_release=lambda *_: self.dump_samples())
        self._add("conn", page(
            card("احراز هویت", lab("کد یکتا (User-Agent)", MUT, 12), self.ent_ua,
                 lab("توکن", MUT, 12), self.ent_token, lab("شناسه فروشگاه", MUT, 12), self.ent_vid, b),
            card("نمونه داده‌ها",
                 lab("یک نمونه از کالا، سفارش و رویداد را می‌گیرد (نام و تلفن و آدرس مشتری پنهان می‌شود) و کپی می‌کند.", MUT, 11), b2)))

        # --- products
        self.pcount = lab("", MUT, 12, halign="center")
        self.pchips_sv, self.pchips = chip_row()
        self.ent_q = inp("جستجو در نام یا کد")
        self.ent_q.bind(text=self._on_q)
        self.ent_low = inp("3", str(self.low), input_filter="int")
        self.ent_low.bind(text=self._on_low)
        p1 = RBtn("بروزرسانی لیست")
        p1.bind(on_release=lambda *_: self.get_products())
        p2 = RBtn("انتخاب همه", ACC2)
        p2.bind(on_release=lambda *_: self.sel_all(True))
        p3 = RBtn("لغو انتخاب", ACC2)
        p3.bind(on_release=lambda *_: self.sel_all(False))
        brow = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50), spacing=dp(8))
        brow.add_widget(p2)
        brow.add_widget(p3)
        p4 = RBtn("ویرایش گروهی (قیمت و موجودی)", (0.20, 0.45, 0.85, 1))
        p4.bind(on_release=lambda *_: self.bulk_edit())
        p5 = RBtn("تخفیف گروهی با تاریخ شروع و پایان", (0.20, 0.55, 0.45, 1))
        p5.bind(on_release=lambda *_: self.discount_campaign())
        self.pl = vbox()
        self.pl.spacing = dp(10)
        self._add("prod", page(
            card("", p1, brow, p4, p5, self.pcount, self.ent_q,
                 lab("حد «کم‌موجودی» (تعداد)", MUT, 12), self.ent_low, self.pchips_sv),
            self.pl))

        # --- orders
        self.ent_sd = inp("YYYY-MM-DD")
        self.ent_ed = inp("YYYY-MM-DD")
        self.ent_ord = inp("Order Number", input_filter="int")
        o1 = RBtn("نمایش لیست سفارشات")
        o1.bind(on_release=lambda *_: self.load_orders())
        o2 = RBtn("گزارش فروش (Excel)", (0.20, 0.65, 0.35, 1))
        o2.bind(on_release=lambda *_: self.export_sales())
        o4 = RBtn("جزئیات سفارش")
        o4.bind(on_release=lambda *_: self.get_order())
        self.ochips_sv, self.ochips = chip_row()
        self.ol = vbox()
        self.ol.spacing = dp(10)
        self._add("ord", page(
            card("سفارشات و گزارش فروش",
                 lab("از تاریخ (میلادی؛ خالی = ۱۴ روز اخیر)", MUT, 12), self.ent_sd,
                 lab("تا تاریخ (میلادی)", MUT, 12), self.ent_ed, o1, o2),
            self.ochips_sv, self.ol,
            card("جزئیات یک سفارش", lab("شماره سفارش", MUT, 12), self.ent_ord, o4)))

        # --- automation page
        if not self.desktop:
            self.ent_wi = inp("Seconds", str(self.cfg.get("watch_sec", 60)), input_filter="int")
            self.watch_lbl = lab("وضعیت: خاموش", MUT, 14, bold=True)
            self.watch_last = lab("", MUT, 12)
            w1 = RBtn("روشن کردن هشدار سفارش جدید", (0.30, 0.85, 0.50, 1))
            w1.color = (0.04, 0.12, 0.07, 1)
            w1.bind(on_release=lambda *_: self.start_watch())
            w2 = RBtn("خاموش کردن", (0.80, 0.26, 0.26, 1))
            w2.bind(on_release=lambda *_: self.stop_watch())
            self._add("auto", page(card(
                "هشدار سفارش جدید", lab("هر چند ثانیه بررسی شود", MUT, 12), self.ent_wi,
                self.watch_lbl, self.watch_last, w1, w2,
                lab("هشدار فقط وقتی کار می‌کند که برنامه باز باشد. برای اجرای بی‌وقفه از برنامه‌ی ویندوز استفاده کنید.", MUT, 11))))
        else:
            self.ent_wi = inp("Seconds", "60")
            self.bot_lbl = lab("وضعیت ربات: خاموش", MUT, 14, bold=True)
            bb1 = RBtn("روشن کردن ربات", (0.30, 0.85, 0.50, 1))
            bb1.color = (0.04, 0.12, 0.07, 1)
            bb1.bind(on_release=lambda *_: self.start_bot())
            bb2 = RBtn("خاموش کردن ربات", (0.80, 0.26, 0.26, 1))
            bb2.bind(on_release=lambda *_: self.stop_bot())
            self.dry_btn = RBtn("", ACC2)
            self._dry_text()
            self.dry_btn.bind(on_release=lambda *_: self.toggle_dry())
            self.rp_btn = RBtn("", ACC2)
            self._rp_text()
            self.rp_btn.bind(on_release=lambda *_: self.toggle_reprice())
            bb3 = RBtn("ساخت فایل قیمت‌ها (prices_export.csv)", ACC2)
            bb3.bind(on_release=lambda *_: self.bot_export())
            bb4 = RBtn("گزارش فروش همین حالا", ACC2)
            bb4.bind(on_release=lambda *_: self.bot_report())
            bb5 = RBtn("باز کردن پوشه‌ی فایل‌ها", ACC2)
            bb5.bind(on_release=lambda *_: self.open_folder())
            cards_auto = [
                card("ربات پس‌زمینه", self.bot_lbl, bb1, bb2,
                     lab("تا وقتی ربات روشن است: سفارش جدید و لغو را با صدا اعلام می‌کند، تغییرات فایل prices.csv را (قیمت، موجودی، تخفیف) روی اسنپ‌شاپ اعمال می‌کند و هر شب گزارش Excel می‌سازد. برنامه را Minimize کنید، نه Close.", MUT, 11)),
                card("تعدیل خودکار قیمت (باکس‌باکس)", self.rp_btn,
                     lab("برای کالاهایی که باکس‌باکس را باخته‌اند، قیمت تخفیفی را ۵٬۰۰۰ تومان زیر قیمت باکس‌باکس می‌گذارد؛ هر ۱۰ دقیقه. کف قیمت: بیشترین مقدار از «ستون min_price در prices.csv»، حد پایین قیمت مرجع اسنپ‌شاپ و ۴۵٪ زیر قیمت پایه. حالت آزمایشی فقط در گزارش می‌نویسد؛ سوابق در reprice_log.csv.", MUT, 11)),
                card("قیمت از روی فایل (Excel)", self.dry_btn, bb3,
                     lab("۱) «ساخت فایل قیمت‌ها» را بزنید. ۲) فایل prices_export.csv را با نام prices.csv کپی کنید. ۳) ستون‌های price و stock و special_price را در Excel ویرایش و ذخیره کنید. ۴) اول در حالت آزمایشی نتیجه را در گزارش ببینید، بعد حالت آزمایشی را خاموش کنید. تغییر قیمت بیش از ۵۰٪ برای جلوگیری از اشتباه تایپی رد می‌شود.", MUT, 11)),
                card("فایل‌ها", bb4, bb5)]
            if os.name == "nt":
                self.win_btn = RBtn("", ACC2)
                self._win_text()
                self.win_btn.bind(on_release=lambda *_: self.toggle_winstart())
                cards_auto.append(card("ویندوز", self.win_btn,
                                       lab("با روشن شدن ویندوز، برنامه Minimize باز می‌شود و ربات (اگر روشن بوده) خودش ادامه می‌دهد. تا ربات روشن است ویندوز به حالت خواب نمی‌رود.", MUT, 11)))
            self._add("auto", page(*cards_auto))

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
        for text, name in (("اتصال", "conn"), ("محصولات", "prod"), ("سفارشات", "ord"), ("هشدار" if not self.desktop else "ربات", "auto"), ("گزارش", "log")):
            nb = NavBtn(text, name, self)
            self.navs.append(nb)
            nav.add_widget(nb)
        root.add_widget(nav)
        self.navs[0].state = "down"
        self.render_products()
        self.render_orders()
        self.log("آماده است.")
        if self.desktop and self.cfg.get("bot_on") and self.cfg.get("ua") and self.cfg.get("token") and self.cfg.get("vid"):
            Clock.schedule_once(lambda dt: self.start_bot(), 2)
        if os.name == "nt" and "--minimized" in sys.argv:
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

    # ---- helpers
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
            except core.AuthError:
                self.log("توکن یا کد یکتا پذیرفته نشد (۴۰۱). اطلاعات را در صفحه‌ی اتصال بررسی کنید.", "err")
            except Exception as e:
                self.log(f"خطا: {e}", "err")
        threading.Thread(target=w, daemon=True).start()

    def log(self, text, kind="info"):
        def _do(_dt):
            self.log_box.add_widget(LogRow(time.strftime("%H:%M"), text, kind))
            if len(self.log_box.children) > 150:
                self.log_box.remove_widget(self.log_box.children[-1])
            self.status.text = fa(text.split("\n")[0][:90])
            self.status.color = {"ok": GRN, "err": RED}.get(kind, MUT)
            Clock.schedule_once(lambda _: setattr(self.log_sv, "scroll_y", 0), 0.1)
        Clock.schedule_once(_do, 0)

    def progress(self, text):
        self.ui(lambda: setattr(self.status, "text", fa(text)))

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

    @staticmethod
    def _fnum(text):
        try:
            return float(text.strip().replace(",", ""))
        except Exception:
            return None

    # ---- credentials
    def _save(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            self.cfg.update({"ua": self.ent_ua.text.strip(), "token": self.ent_token.text.strip(),
                             "vid": self.ent_vid.text.strip(), "low": self.low,
                             "watch_sec": self._fnum(self.ent_wi.text) or 60})
            with open(self.cfg_path, "w") as f:
                json.dump(self.cfg, f)
        except Exception:
            pass

    def _setup(self):
        ua, tok = self.ent_ua.text.strip(), self.ent_token.text.strip()
        if not ua or not tok:
            self.log("User-Agent و توکن الزامی است.", "err")
            self.go("conn")
            return False
        self.client = core.Client(ua, tok)
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
            vs = self.client.vendors()
            if vs:
                v = vs[0]["id"]
                def done():
                    self.vendor_id = v
                    self.ent_vid.text = v
                    self._save()
                    self.log(f"اتصال موفق. فروشگاه: {vs[0].get('title', '')} ({v})", "ok")
                self.ui(done)
            else:
                self.log("فروشگاهی برای این توکن پیدا نشد.", "err")
        self.log("در حال اتصال...")
        self._run(f)

    # ---- products
    def vis(self):
        today = datetime.date.today().isoformat()
        q = self.Q
        return [o for o in self.P if L.match(o, self.PF, self.low, today) and (not q or q in (o.name + " " + o.key).lower())]

    def _on_q(self, _i, val):
        self.Q = val.strip().lower()
        Clock.unschedule(self._q_apply)
        Clock.schedule_once(self._q_apply, 0.35)

    def _q_apply(self, _dt):
        self.shown = 100
        self.render_products()

    def _on_low(self, _i, val):
        v = self._fnum(val)
        if v is not None and v >= 0:
            self.low = int(v)
            Clock.unschedule(self._q_apply)
            Clock.schedule_once(self._q_apply, 0.5)

    def set_pf(self, key):
        self.PF, self.shown = key, 100
        self.render_products()

    def render_pchips(self):
        self.pchips.clear_widgets()
        today = datetime.date.today().isoformat()
        for key, label in L.FILTERS:
            cnt = sum(1 for o in self.P if L.match(o, key, self.low, today))
            ch = Chip(f"{label}  {n(cnt)}", key, active=(self.PF == key))
            ch.bind(on_release=lambda c: self.set_pf(c.key))
            self.pchips.add_widget(ch)

    def render_products(self):
        self.render_pchips()
        self.pl.clear_widgets()
        Lst = self.vis()
        for o in Lst[:self.shown]:
            self.pl.add_widget(ProdCard(o, self))
        if len(Lst) > self.shown:
            more = RBtn(f"نمایش بیشتر ({n(len(Lst) - self.shown)})", ACC2)
            more.bind(on_release=lambda *_: self._more())
            self.pl.add_widget(more)
        if not Lst:
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
            raw = self.client.products(self.vendor_id, lambda p, t: self.progress(f"دریافت محصولات: صفحه {p} از {t}"))
            def done():
                self.P = [L.norm_prod(p, i) for i, p in enumerate(raw)]
                self.PF, self.shown = "all", 100
                self.render_products()
                self.log(f"تعداد محصولات: {len(raw)}", "ok")
            self.ui(done)
        self.log("در حال دریافت محصولات...")
        self._run(f)

    def patch(self, items, then):
        """Send items; log failures; call then(bad_keys) on the UI thread."""
        def f():
            res = self.client.patch_products(self.vendor_id, items)
            ok, bad = L.summarize_patch(res)
            def done():
                if bad:
                    self.log(f"{ok} مورد انجام شد، {len(bad)} مورد ناموفق:\n" + "\n".join(f"{k}: {m}" for k, m in bad[:8]), "err")
                else:
                    self.log(f"{ok} مورد با موفقیت به‌روزرسانی شد.", "ok")
                then({k for k, _ in bad})
            self.ui(done)
        self._run(f)

    def edit_product(self, o):
        ep = inp("Price", "" if o.price is None else str(int(o.price)), input_filter="int")
        es = inp("Stock", "" if o.stock is None else str(int(o.stock)), input_filter="int")
        body = vbox()
        for w in (lab("قیمت پایه (تومان)", MUT, 12), ep, lab("موجودی", MUT, 12), es):
            body.add_widget(w)
        def save():
            if not self._need_vid():
                return False
            try:
                pr = int(ep.text) if ep.text.strip() else o.price
                st = int(es.text) if es.text.strip() else o.stock
                item = o.item(price=pr, stock=st)
            except Exception:
                self.log("قیمت و موجودی باید عدد باشند.", "err")
                return False
            def then(bad):
                if o.key not in bad:
                    o.price, o.stock = item["price"], item["stock"]
                self.render_products()
            self.patch([item], then)
        self.modal(o.name, o.key, body, [("انصراف", ACC2, None), ("ذخیره", ACC, save)], h=0.6)

    def bulk_edit(self):
        sel = [o for o in self.P if o.sel]
        if not sel:
            self.log("ابتدا کالاهای مورد نظر را انتخاب کنید (تیک بزنید).", "err")
            return
        if not self._need_vid():
            return
        e_pct, e_amt, e_stk = inp("مثلاً -5 یا 3"), inp("مثلاً -5000"), inp("مثلاً 10")
        body = vbox()
        for w in (lab("تغییر قیمت پایه: درصد (منفی = کاهش)", MUT, 12), e_pct,
                  lab("تغییر قیمت پایه: مبلغ تومان (منفی = کاهش)", MUT, 12), e_amt,
                  lab("تنظیم موجودی روی عدد", MUT, 12), e_stk):
            body.add_widget(w)
        def apply():
            pct, amt, stk = self._fnum(e_pct.text), self._fnum(e_amt.text), self._fnum(e_stk.text)
            if pct is None and amt is None and stk is None:
                self.log("هیچ تغییری وارد نشده است.", "err")
                return False
            if pct is not None and abs(pct) > 50:
                self.log("تغییر قیمت بیش از ۵۰٪ مجاز نیست.", "err")
                return False
            if stk is not None and stk < 0:
                self.log("موجودی نمی‌تواند منفی باشد.", "err")
                return False
            changes, skipped = L.plan_bulk(sel, pct, amt, stk)
            if not changes:
                self.log("تغییری لازم نبود." + (f" ({skipped} کالا بدون قیمت/موجودی معتبر)" if skipped else ""), "err")
                return
            self.go("log")
            self.log(f"در حال اعمال ویرایش گروهی روی {len(changes)} کالا...")
            items = [o.item(price=p, stock=s) for o, p, s in changes]
            def then(bad):
                for o, p, s in changes:
                    if o.key not in bad:
                        o.price, o.stock = p, s
                for o in sel:
                    o.sel = False
                self.render_products()
            self.patch(items, then)
        self.modal("ویرایش گروهی", f"{n(len(sel))} کالا انتخاب شده است. فقط فیلدهای پرشده اعمال می‌شود.", body,
                   [("انصراف", ACC2, None), ("اعمال", ACC, apply)], h=0.7)

    def discount_campaign(self):
        sel = [o for o in self.P if o.sel]
        if not sel:
            self.log("ابتدا کالاهای مورد نظر را انتخاب کنید (تیک بزنید).", "err")
            return
        if not self._need_vid():
            return
        today = datetime.date.today()
        e_pct = inp("مثلاً 10", "", input_filter="int")
        e_st = inp("YYYY-MM-DD", today.isoformat())
        e_en = inp("YYYY-MM-DD", (today + datetime.timedelta(days=7)).isoformat())
        e_ds = inp("خالی = موجودی کالا", "", input_filter="int")
        body = vbox()
        for w in (lab("درصد تخفیف", MUT, 12), e_pct, lab("تاریخ شروع (میلادی)", MUT, 12), e_st,
                  lab("تاریخ پایان (میلادی)", MUT, 12), e_en, lab("موجودی مخصوص تخفیف (اختیاری)", MUT, 12), e_ds):
            body.add_widget(w)
        def apply():
            pct = self._fnum(e_pct.text)
            try:
                st = datetime.date.fromisoformat(e_st.text.strip())
                en = datetime.date.fromisoformat(e_en.text.strip())
            except Exception:
                self.log("تاریخ‌ها باید به شکل YYYY-MM-DD باشند.", "err")
                return False
            if pct is None or not (1 <= pct <= 90):
                self.log("درصد تخفیف باید بین ۱ و ۹۰ باشد.", "err")
                return False
            if en < st:
                self.log("تاریخ پایان قبل از شروع است.", "err")
                return False
            ds = self._fnum(e_ds.text)
            plan, skipped = L.plan_discount(sel, pct, st.isoformat(), en.isoformat(), ds)
            if not plan:
                self.log("کالایی برای تخفیف پیدا نشد.", "err")
                return
            self.go("log")
            self.log(f"در حال ثبت تخفیف {pct:g}٪ روی {len(plan)} کالا...")
            def then(bad):
                for o, it in plan:
                    if o.key not in bad:
                        o.sp, o.sp_start, o.sp_end = it["special_price"], st.isoformat(), en.isoformat()
                for o in sel:
                    o.sel = False
                self.render_products()
            self.patch([it for _o, it in plan], then)
        self.modal("تخفیف گروهی", f"{n(len(sel))} کالا انتخاب شده است. قیمت پس از تخفیف از روی قیمت پایه محاسبه می‌شود.", body,
                   [("انصراف", ACC2, None), ("ثبت تخفیف", ACC, apply)], h=0.8)

    # ---- orders
    def _orders_list(self):
        return self.client.orders(self.vendor_id, self.ent_sd.text.strip() or None, self.ent_ed.text.strip() or None,
                                  progress=lambda p, c: self.progress(f"دریافت سفارشات: {c} سفارش..."))

    def render_orders(self):
        self.ochips.clear_widgets()
        self.ol.clear_widgets()
        if self.O:
            cnt = {}
            for o in self.O:
                cnt[o.status] = cnt.get(o.status, 0) + 1
            def addc(label, key, c):
                ch = Chip(f"{label}  {n(c)}", key, active=(self.OF == key))
                ch.bind(on_release=lambda x: self.set_of(x.key))
                self.ochips.add_widget(ch)
            addc("همه", "all", len(self.O))
            addc("نیازمند آماده‌سازی", "prep", sum(1 for o in self.O if o.prep))
            for s, c in cnt.items():
                addc(L.status_fa(s) or "—", "st:" + s, c)
        sel = [o for o in self.O if self.OF == "all" or (self.OF == "prep" and o.prep) or self.OF == "st:" + o.status]
        sel = sorted(sel, key=lambda o: o.pickup_end or "9") if self.OF == "prep" else list(reversed(sel))
        nowt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for o in sel[:150]:
            c = TapBg(color=CARD, radius=12, orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(4))
            c.bind(minimum_height=c.setter("height"))
            c.add_widget(lab(f"سفارش {o.num}", bold=True, size=14))
            c.add_widget(lab(f"{L.jdate(o.created)}  {o.created[11:16]}", MUT, 11))
            if o.prep and o.pickup_end:
                late = o.pickup_end < nowt
                c.add_widget(lab(("مهلت تحویل به پیک گذشته: " if late else "مهلت تحویل به پیک: ") + f"{L.jdate(o.pickup_end)} {o.pickup_end[11:16]}", RED if late else AMB, 12))
            meta = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            meta.add_widget(BoxLayout())
            tl = lab(f"جمع: {n(o.total)}", TXT, 13)
            tl.size_hint_x = None
            tl.width = dp(140)
            meta.add_widget(tl)
            if o.status:
                meta.add_widget(badge(L.status_fa(o.status), "r" if o.canceled else "g" if o.prep else "n"))
            c.add_widget(meta)
            c.bind(on_release=lambda w, num=o.num: self.open_order(num))
            self.ol.add_widget(c)
        if len(sel) > 150:
            self.ol.add_widget(lab("فقط ۱۵۰ مورد اول نمایش داده شد.", MUT, 11, halign="center"))
        if not sel:
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
                self.O = [L.norm_order(o, i) for i, o in enumerate(d)]
                self.OF = "all"
                self.render_orders()
                self.log(f"تعداد سفارشات: {len(self.O)} · نیازمند آماده‌سازی: {sum(1 for o in self.O if o.prep)}", "ok")
            self.ui(done)
        self.log("در حال دریافت سفارشات...")
        self._run(f)

    def open_order(self, num):
        if not self._need_vid():
            return
        def f():
            d = self.client.order(self.vendor_id, num)
            o = L.norm_order(d if isinstance(d, dict) else {})
            by_pn = {p.pnum: p for p in self.P if p.pnum}
            def done():
                body = vbox()
                body.spacing = dp(2)
                def kv(k, v):
                    row = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
                    row.bind(minimum_height=row.setter("height"))
                    kl = lab(k, MUT, 12, halign="right")
                    kl.size_hint_x = 0.38
                    row.add_widget(kl)
                    row.add_widget(lab(str(v), TXT, 13, halign="right"))
                    body.add_widget(row)
                kv("وضعیت", L.status_fa(o.status))
                kv("ثبت", f"{L.jdate(o.created)} {o.created[11:16]}")
                kv("نوع ارسال", o.delivery)
                if o.pickup_end:
                    kv("تحویل به پیک", f"{o.pickup_start[11:16]} تا {o.pickup_end[11:16]} ({L.jdate(o.pickup_end)})")
                cu = (d.get("customer") or {}) if isinstance(d, dict) else {}
                nm = f"{cu.get('first_name') or ''} {cu.get('last_name') or ''}".strip()
                if nm:
                    kv("خریدار", nm)
                for it in o.items:
                    p = by_pn.get(str(it.get("product_number") or ""))
                    kv("کالا", (p.name if p else "") or it.get("sku") or it.get("product_number"))
                    q, cq = it.get("quantity"), it.get("canceled_quantity")
                    kv("تعداد", f"{q} (لغو: {cq})")
                    kv("قیمت نهایی", n(L.to_num(it.get("final_price"))))
                self.modal(f"سفارش {num}", f"جمع: {n(o.total)}", body, [("بستن", ACC2, None)])
            self.ui(done)
        self._run(f)

    def get_order(self):
        num = self.ent_ord.text.strip()
        if not num:
            self.log("شماره سفارش را وارد کنید.", "err")
            return
        self.open_order(num)

    # ---- Excel sales report
    def out_dir(self):
        if platform == "android":
            return self.data_dir
        d = os.path.join(os.path.expanduser("~"), "Documents", "SnappShop")
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            return self.data_dir

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
            data = L.build_sales_workbook(d, self.P or None, self.low)
            shown = self.write_report("sales-" + time.strftime("%Y-%m-%d") + ".xlsx", data)
            hint = "" if self.P else "\n(برای نمایش نام کالا و شیت کم‌موجودی، قبل از گزارش «بروزرسانی لیست» محصولات را بزنید.)"
            self.log(f"گزارش آماده شد (ریز فروش، خلاصه کالا، خلاصه روزانه): {len(d)} سفارش.\n{shown}{hint}", "ok")
        self.go("log")
        self.log("در حال دریافت سفارشات برای گزارش...")
        self._run(f)

    # ---- sample data (redacted)
    def dump_samples(self):
        if not self._need_vid():
            return
        def f():
            S: Dict[str, Any] = {}
            v = self.vendor_id
            for key, ep, prm in (("products", f"vendors/{v}/products", {"page": 1}),
                                 ("events", f"vendors/{v}/orders/events", None),
                                 ("orders", f"vendors/{v}/orders", None)):
                try:
                    r = self.client.request("GET", ep, prm)
                    S[key + "_sample"] = (r.get("data") or [])[:2]
                except Exception as e:
                    S[key + "_error"] = str(e)
            txt = json.dumps(L.redact(S), ensure_ascii=False, indent=1)
            def done():
                try:
                    Clipboard.copy(txt)
                    copied = True
                except Exception:
                    copied = False
                self.log(txt[:5000] + ("\n..." if len(txt) > 5000 else ""))
                self.log("نمونه‌ها " + ("کپی شد؛ در چت Paste کنید." if copied else "آماده شد."), "ok")
            self.ui(done)
        self.go("log")
        self.log("در حال دریافت نمونه‌ها...")
        self._run(f)

    # ---- new-order alerts (only while the app is open)
    def start_watch(self):
        if self.watching:
            return
        if not self._need_vid():
            return
        iv = max(15, int(self._fnum(self.ent_wi.text) or 60))
        ev = threading.Event()
        self.watch_ev = ev
        self.watching = True
        self._save()
        self.watch_lbl.text = fa("وضعیت: روشن")
        self.watch_lbl.color = GRN
        self.log(f"هشدار سفارش جدید روشن شد (هر {iv} ثانیه).", "ok")
        def loop():
            while not ev.is_set():
                try:
                    first = not self.cfg.get("ev_init")
                    evs, last = self.client.events(self.vendor_id, self.cfg.get("ev_cursor"))
                    if last:
                        self.cfg["ev_cursor"] = last
                    self.cfg["ev_init"] = True
                    self._save()
                    if first:
                        self.log(f"رویدادهای قبلی ({len(evs)}) نادیده گرفته شد؛ از این به بعد هشدار می‌دهم.")
                    else:
                        for e in evs:
                            t = e.get("event_type")
                            if t == "NEW_ORDER":
                                items = e.get("items") or []
                                tot = sum(L.to_num(i.get("final_price")) or 0 for i in items if isinstance(i, dict))
                                self.log(f"سفارش جدید {e.get('order_number')} — {len(items)} قلم — {n(tot)}", "ok")
                            elif t == "CANCELLATION":
                                self.log(f"لغو کالا در سفارش {e.get('order_number')}", "err")
                            elif t == "CHANGE_STATUS":
                                self.log(f"سفارش {e.get('order_number')}: وضعیت → {L.status_fa(e.get('new_status'))}")
                    stamp = fa("آخرین بررسی: " + time.strftime("%H:%M:%S"))
                    self.ui(lambda: setattr(self.watch_last, "text", stamp))
                except core.AuthError:
                    self.log("توکن پذیرفته نشد؛ هشدار متوقف شد.", "err")
                    break
                except Exception as e:
                    self.log(f"خطا در هشدار: {e}", "err")
                ev.wait(iv)
            self.watching = False
        threading.Thread(target=loop, daemon=True).start()

    def stop_watch(self):
        self.watch_ev.set()
        self.watching = False
        self.watch_lbl.text = fa("وضعیت: خاموش")
        self.watch_lbl.color = MUT
        self.log("هشدار سفارش جدید خاموش شد.")

    # ---- desktop bot (runs bot.Bot in a background thread)
    def _bot_mod(self):
        os.environ.setdefault("SNAPP_BOT_DIR", self.out_dir())
        import bot
        return bot

    def _bot_cfg(self):
        cfg = dict(self.bot.DEFAULT)
        cfg.update(self.bot.jload(self.bot.CFG, {}))
        cfg.update({"user_agent": self.ent_ua.text.strip(), "token": self.ent_token.text.strip(),
                    "vendor_id": self.ent_vid.text.strip()})
        return cfg

    def _attach_bot_log(self):
        if self._bot_log_ready:
            return
        lg = logging.getLogger("bot")
        lg.setLevel(logging.INFO)
        lg.addHandler(GuiLogHandler(self))
        try:
            fh = RotatingFileHandler(os.path.join(self.out_dir(), "bot.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            lg.addHandler(fh)
        except Exception:
            pass
        self._bot_log_ready = True

    def _bot_label(self, on):
        self.bot_lbl.text = fa("وضعیت ربات: روشن" if on else "وضعیت ربات: خاموش")
        self.bot_lbl.color = GRN if on else MUT

    def start_bot(self):
        if self.bot_obj is not None:
            return
        if not self._need_vid():
            return
        self._attach_bot_log()
        b = self.bot.Bot(self._bot_cfg())
        self.bot_obj = b
        self.cfg["bot_on"] = True
        self._save()
        self._bot_label(True)
        def run():
            rc = None
            try:
                rc = b.run()
            except Exception as e:
                self.log(f"خطا در ربات: {e}", "err")
            def done():
                if self.bot_obj is b:
                    self.bot_obj = None
                    self._bot_label(False)
                if rc == 2:
                    self.log("توکن پذیرفته نشد؛ ربات متوقف شد.", "err")
            self.ui(done)
        threading.Thread(target=run, daemon=True).start()

    def stop_bot(self):
        if self.bot_obj is not None:
            self.bot_obj.stop()
            self.bot_obj = None
        self.cfg["bot_on"] = False
        self._save()
        self._bot_label(False)
        self.log("ربات خاموش شد.")

    def _dry_text(self):
        dry = bool(self.bot.jload(self.bot.CFG, {}).get("prices_dry_run", True))
        self.dry_btn.set_text("اعمال prices.csv: " + ("فقط آزمایشی (چیزی تغییر نمی‌کند)" if dry else "واقعی (تغییرات ارسال می‌شود)"))

    def toggle_dry(self):
        c = self.bot.jload(self.bot.CFG, {})
        c["prices_dry_run"] = not c.get("prices_dry_run", True)
        self.bot.jsave(self.bot.CFG, c)
        self._dry_text()
        self.log("prices.csv حالا " + ("آزمایشی است." if c["prices_dry_run"] else "واقعی است؛ تغییرات روی اسنپ‌شاپ اعمال می‌شود."), "ok" if c["prices_dry_run"] else "err")

    RP_FA = {"off": "خاموش", "dry": "آزمایشی (فقط گزارش)", "live": "واقعی (قیمت تغییر می‌کند)"}

    def _rp_text(self):
        md = self.bot.jload(self.bot.CFG, {}).get("reprice_mode", "off")
        self.rp_btn.set_text("تعدیل خودکار قیمت: " + self.RP_FA.get(md, "خاموش"))

    def toggle_reprice(self):
        c = self.bot.jload(self.bot.CFG, {})
        order = ["off", "dry", "live"]
        c["reprice_mode"] = order[(order.index(c.get("reprice_mode", "off")) + 1) % 3 if c.get("reprice_mode", "off") in order else 1]
        self.bot.jsave(self.bot.CFG, c)
        self._rp_text()
        self.log("تعدیل قیمت: " + self.RP_FA[c["reprice_mode"]], "err" if c["reprice_mode"] == "live" else "ok")

    def _win_text(self):
        self.win_btn.set_text("اجرا با روشن شدن ویندوز: " + ("بله" if self.cfg.get("winstart") else "خیر"))

    def toggle_winstart(self):
        on = not self.cfg.get("winstart")
        if on and not getattr(sys, "frozen", False):
            self.log("این گزینه فقط در نسخه‌ی EXE کار می‌کند.", "err")
            return
        try:
            self.bot.startup(on)
        except Exception as e:
            self.log(f"تنظیم اجرای خودکار ناموفق بود: {e}", "err")
            return
        self.cfg["winstart"] = on
        self._save()
        self._win_text()
        self.log("اجرا با روشن شدن ویندوز " + ("فعال شد." if on else "غیرفعال شد."), "ok")

    def bot_export(self):
        if not self._need_vid():
            return
        self._attach_bot_log()
        self.go("log")
        self._run(lambda: self.bot.Bot(self._bot_cfg()).export_products())

    def bot_report(self):
        if not self._need_vid():
            return
        self._attach_bot_log()
        self.go("log")
        self._run(lambda: self.bot.Bot(self._bot_cfg()).report(force=True))

    def open_folder(self):
        d = self.out_dir()
        try:
            if os.name == "nt":
                os.startfile(d)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", d])
        except Exception as e:
            self.log(f"پوشه: {d} ({e})", "info")

    def _minimize(self):
        try:
            Window.minimize()
        except Exception:
            pass

    def on_pause(self):
        return True


if __name__ == "__main__":
    SnappShopApp().run()
