# -*- coding: utf-8 -*-
import datetime, json, logging, ntpath, os, re, shutil, site, sys, threading, time
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
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
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

# ---------------- theme (light seller panel) ----------------
BG = (0.953, 0.941, 0.945, 1)
BAR = (1, 0.988, 0.992, 1)
CARD = (1, 0.988, 0.992, 1)
FIELD = (0.969, 0.949, 0.957, 1)
CHIP = (0.992, 0.973, 0.980, 1)
ACC = (0.761, 0.094, 0.357, 1)
ACC2 = (1, 0.988, 0.992, 1)
GRN = (0.059, 0.478, 0.290, 1)
RED = (0.706, 0.137, 0.094, 1)
AMB = (0.545, 0.318, 0.078, 1)
TXT = (0.110, 0.078, 0.094, 1)
MUT = (0.435, 0.380, 0.408, 1)
EDGE = (0.878, 0.835, 0.851, 1)
LINE2 = (0.918, 0.875, 0.890, 1)

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LabelBase.register(name="fa",
                   fn_regular=os.path.join(HERE, "DejaVuSans.ttf"),
                   fn_bold=os.path.join(HERE, "DejaVuSans-Bold.ttf"))
FONT = FONT_B = "fa"
Window.clearcolor = BG
Window.softinput_mode = "below_target"


def fa(text) -> str:
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))


def par(text, width=34) -> str:
    """Shape a (possibly long) Persian paragraph for Kivy: first break it into short
    lines (L.break_lines), then apply fa() per line.

    Why: Kivy wraps text LTR, but fa() puts a whole paragraph in visual (RTL) order.
    When Kivy then wraps that string, the top line shows the END of the sentence, so
    long descriptions read bottom-to-top. Pre-breaking keeps every line correct."""
    return "\n".join(fa(l) for l in L.break_lines(text, width))


def n(x) -> str:
    return "—" if x is None else f"{int(round(x)):,}"


# ---------------- widgets ----------------
class Bg(BoxLayout):
    def __init__(self, color=CARD, radius=0, border=None, shadow=False, **kw):
        super().__init__(**kw)
        self._rad = dp(radius)
        with self.canvas.before:
            if shadow:
                Color(0.12, 0.07, 0.09, 0.07)
                self._sh = RoundedRectangle(radius=[self._rad])
            else:
                self._sh = None
            Color(*color)
            self._r = RoundedRectangle(radius=[self._rad])
            self._bc = Color(*(border or (0, 0, 0, 0)))
            self._ln = Line(rounded_rectangle=(0, 0, 10, 10, self._rad), width=1.05)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        if self._sh is not None:
            self._sh.pos = (self.x, self.y - dp(3))
            self._sh.size = (self.width, self.height)
        self._r.pos, self._r.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, self._rad)


class Tap(ButtonBehavior, BoxLayout):
    pass


class TapBg(ButtonBehavior, Bg):
    pass


def lab(text, color=TXT, size=14, bold=False, halign="right"):
    l = Label(text=par(text), font_name=FONT_B if bold else FONT, font_size=sp(size),
              color=color, halign=halign, valign="middle", size_hint_y=None)
    l.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    l.bind(texture_size=lambda i, s: setattr(i, "height", max(s[1], dp(18)) + dp(4)))
    return l


_FA_RE = re.compile("[\u0600-\u06FF]")


class FaInput(TextInput):
    """Text box that types Persian correctly: keeps the logical text in .raw and shows the shaped RTL form."""
    def __init__(self, **kw):
        self.raw = ""
        self.on_raw = None
        super().__init__(**kw)

    def _show(self):
        self.text = fa(self.raw) if self.raw else ""
        self.cursor = self.get_cursor_from_index(len(self.text))
        if self.on_raw:
            self.on_raw(self.raw)

    def insert_text(self, substring, from_undo=False):
        self.raw += substring.replace("\n", " ")
        self._show()

    def do_backspace(self, from_undo=False, mode="bkspc"):
        self.raw = self.raw[:-1]
        self._show()

    def delete_selection(self, from_undo=False):
        self.raw = ""
        self._show()


def inp(hint, text="", persian=False, **kw):
    has_fa = bool(_FA_RE.search(str(hint)))
    cls = FaInput if persian else TextInput
    return cls(hint_text=fa(hint) if has_fa else str(hint), text=text, multiline=False, font_name=FONT, font_size=sp(16),
               halign="right" if (has_fa or persian) else "left",
               size_hint_y=None, height=dp(50), padding=[dp(14), dp(14), dp(14), dp(10)],
               background_normal="", background_active="", background_color=FIELD,
               foreground_color=TXT, hint_text_color=MUT, cursor_color=ACC,
               write_tab=False, **kw)


def _luma(color) -> float:
    r, g, b = color[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class RBtn(ButtonBehavior, Label):
    def __init__(self, text, color=ACC, **kw):
        self._c = color
        light = _luma(color) > 0.72
        fg = TXT if light else (1, 1, 1, 1)
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(14), color=fg,
                         size_hint_y=None, height=dp(48), halign="center", valign="middle", **kw)
        self.bind(size=lambda i, s: setattr(i, "text_size", s))
        with self.canvas.before:
            self._col = Color(*color)
            self._r = RoundedRectangle(radius=[dp(14)])
            Color(*(EDGE if light else (0, 0, 0, 0)))
            self._ln = Line(rounded_rectangle=(0, 0, 10, 10, dp(14)), width=1.1)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(14))

    def set_text(self, t):
        self.text = fa(t)

    def on_press(self):
        self._col.rgba = tuple(max(0, c * 0.86) for c in self._c[:3]) + (1,)

    def on_release(self):
        self._col.rgba = self._c


class Chip(ButtonBehavior, Label):
    def __init__(self, text, key, active=False, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(12.5),
                         color=(1, 1, 1, 1) if active else TXT, size_hint=(None, None), height=dp(36), **kw)
        self.key = key
        self.texture_update()
        self.width = self.texture_size[0] + dp(26)
        with self.canvas.before:
            Color(*(ACC if active else CARD))
            self._r = RoundedRectangle(radius=[dp(18)])
            Color(*(ACC if active else EDGE))
            self._ln = Line(width=1.05)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(18))


class MenuBtn(ButtonBehavior, BoxLayout):
    """Filter pill like the seller panel: caption on the right, chevron on the left."""
    def __init__(self, title, **kw):
        super().__init__(orientation="horizontal", size_hint=(None, None), height=dp(40),
                         padding=[dp(12), 0, dp(12), 0], spacing=dp(6), **kw)
        self.chev = Label(text="▾", font_name=FONT, font_size=sp(13), color=MUT,
                          size_hint=(None, 1), width=dp(16), halign="center", valign="middle")
        self.lbl = Label(text=fa(title), font_name=FONT_B, font_size=sp(12.5), color=TXT,
                         size_hint=(None, 1), halign="right", valign="middle")
        self.add_widget(self.chev)
        self.add_widget(self.lbl)
        self.set_caption(title, False)
        with self.canvas.before:
            self._bg = Color(1, 1, 1, 1)
            self._r = RoundedRectangle(radius=[dp(20)])
            self._bc = Color(*EDGE)
            self._ln = Line(width=1.05)
        self.bind(pos=self._u, size=self._u)

    def _fit(self):
        self.lbl.texture_update()
        self.lbl.width = self.lbl.texture_size[0] + dp(2)
        self.width = self.lbl.width + self.chev.width + dp(30)

    def set_caption(self, text, on):
        self.lbl.text = fa(text)
        self.lbl.color = (1, 1, 1, 1) if on else TXT
        self.chev.color = (1, 1, 1, 1) if on else MUT
        if hasattr(self, "_bg"):
            self._bg.rgba = ACC if on else (1, 1, 1, 1)
            self._bc.rgba = ACC if on else EDGE
        self._fit()

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(20))
        self.chev.text_size = (self.chev.width, self.height)
        self.lbl.text_size = (self.lbl.width, self.height)


def chip_row():
    sv = ScrollView(size_hint_y=None, height=dp(44), do_scroll_y=False, bar_width=0)
    row = BoxLayout(orientation="horizontal", size_hint_x=None, spacing=dp(8))
    row.bind(minimum_width=row.setter("width"))
    sv.add_widget(row)
    row.bind(width=lambda *_: setattr(sv, "scroll_x", 1))   # RTL: start from the right edge
    return sv, row


def badge(text, kind):
    bg, fg = {"r": ((0.992, 0.910, 0.902, 1), RED), "g": ((0.906, 0.965, 0.933, 1), GRN),
              "o": ((0.992, 0.953, 0.902, 1), AMB), "n": (FIELD, MUT)}[kind]
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
    c = Bg(color=CARD, radius=18, border=EDGE, shadow=True, orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(10))
    c.bind(minimum_height=c.setter("height"))
    if title:
        hd = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26), spacing=dp(8))
        hd.add_widget(lab(title, size=15, bold=True))
        bar = Bg(color=ACC, radius=2, size_hint=(None, None), size=(dp(4), dp(18)), pos_hint={"center_y": 0.5})
        hd.add_widget(bar)
        c.add_widget(hd)
    for w in widgets:
        c.add_widget(w)
    return c


def shell(w, h=54):
    """Rounded field around a text input. The input widget itself is unchanged for callers."""
    box = Bg(color=CARD, radius=16, border=EDGE, size_hint_y=None, height=dp(h), padding=[dp(8), dp(2), dp(8), dp(2)])
    w.background_color = (0, 0, 0, 0)
    w.size_hint_y = None
    w.height = dp(h - 8)
    box.add_widget(w)
    return box


def page(*widgets):
    sv = ScrollView(do_scroll_x=False)
    box = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12), size_hint_y=None)
    box.bind(minimum_height=box.setter("height"))
    for w in widgets:
        box.add_widget(w)
    sv.add_widget(box)
    return sv


class SelText(TextInput):
    # read-only selectable text; copying gives back normal (unshaped) Persian
    def copy(self, data=""):
        txt = self.selection_text or data or ""
        if txt:
            Clipboard.copy("\n".join(L.unshape_line(x, get_display) for x in txt.split("\n")))


class LogRow(Bg):
    # one report line; long-press the text to select and copy
    def __init__(self, ts, text, kind, **kw):
        super().__init__(color=FIELD, radius=12, border=EDGE, orientation="horizontal", size_hint_y=None,
                         spacing=dp(6), padding=[dp(8), dp(4), dp(8), dp(4)], **kw)
        col = {"ok": GRN, "err": RED}.get(kind, TXT)
        rtl = bool(_FA_RE.search(text))
        t = Label(text=ts, font_name=FONT, font_size=sp(11), color=MUT, size_hint=(None, None),
                  size=(dp(44), dp(18)), halign="left", valign="top")
        t.bind(size=lambda i, s: setattr(i, "text_size", s))
        m = SelText(text=par(text[:6000]), readonly=True, multiline=True, font_name=FONT, font_size=sp(13),
                    foreground_color=col, background_normal="", background_active="", background_color=(0, 0, 0, 0),
                    cursor_color=(0, 0, 0, 0), halign="right" if rtl else "left", size_hint_y=None, height=dp(30),
                    padding=[0, dp(2), 0, dp(2)], use_bubble=True, use_handles=True)
        m.bind(minimum_height=lambda i, h: setattr(i, "height", h))
        m.bind(height=lambda i, h: setattr(self, "height", h + dp(10)))
        self.add_widget(t)
        self.add_widget(m)


class NavBtn(ToggleButtonBehavior, Label):
    def __init__(self, text, name, app, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(12), color=MUT,
                         group="nav", allow_no_selection=False, **kw)
        self.name, self.app = name, app
        with self.canvas.before:
            self._ic = Color(*ACC[:3], 0)
            self._ind = RoundedRectangle(radius=[dp(2)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._ind.pos = (self.center_x - dp(16), self.top - dp(3))
        self._ind.size = (dp(32), dp(3))

    def on_state(self, _w, st):
        on = st == "down"
        self.color = ACC if on else MUT
        self._ic.a = 1 if on else 0
        if on:
            self.app.sm.current = self.name

    def on_release(self):
        # tapping a tab (even the active one) scrolls its list back to the top
        self.app.scroll_top(self.name)


class StatusBar(ButtonBehavior, Label):
    pass


def friendly(e) -> str:
    t = str(e)
    if "HTTP 422" in t:
        return "اسنپ‌شاپ اطلاعات ارسالی را نپذیرفت (۴۲۲). مقادیر را بررسی کنید."
    if "HTTP 429" in t:
        return "تعداد درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره تلاش کنید."
    if "HTTP 5" in t:
        return "سرور اسنپ‌شاپ موقتاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید."
    if "network error" in t:
        return "ارتباط با سرور اسنپ‌شاپ برقرار نشد؛ اینترنت را بررسی کنید."
    return f"خطا: {t[:300]}"


class GuiLogHandler(logging.Handler):
    """Shows the bot's log lines inside the app's report tab."""
    def __init__(self, app):
        super().__init__(logging.INFO)
        self.app = app
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, r):
        try:
            msg = self.format(r).strip()
            if msg.startswith("EVENT "):
                msg = msg[6:]
            kind = "err" if r.levelno >= logging.WARNING else ("ok" if ("NEW_ORDER" in msg or "سفارش جدید" in msg) else "info")
            self.app.log(msg, kind)
        except Exception:
            pass


def kv_row(label, value, vcolor=TXT, bold=False):
    row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26))
    val = Label(text=fa(str(value)), font_name=FONT_B if bold else FONT, font_size=sp(14 if bold else 13),
                color=vcolor, halign="left", valign="middle")
    key = Label(text=fa(label), font_name=FONT, font_size=sp(12), color=MUT, halign="right", valign="middle")
    for w in (val, key):
        w.bind(size=lambda i, s: setattr(i, "text_size", s))
    row.add_widget(val)
    row.add_widget(key)
    return row


def stock_pill(label, value, tint):
    box = Bg(color=tint, radius=12, orientation="vertical", padding=[dp(8), dp(4), dp(8), dp(4)])
    cap = Label(text=fa(label), font_name=FONT, font_size=sp(10), color=MUT, halign="right", valign="middle")
    num = Label(text=n(value), font_name=FONT_B, font_size=sp(16), color=TXT, halign="right", valign="middle")
    for w in (cap, num):
        w.bind(size=lambda i, s: setattr(i, "text_size", s))
    box.add_widget(num)
    box.add_widget(cap)
    return box


class ProdCard(Bg):
    def __init__(self, o, app, **kw):
        today = datetime.date.today().isoformat()
        lose = o.lose_bb(today)
        super().__init__(color=CARD, radius=18, border=ACC if o.sel else EDGE, shadow=True,
                         orientation="vertical", size_hint_y=None, padding=[dp(12), dp(10), dp(12), dp(12)],
                         spacing=dp(6), **kw)
        self.o, self.app = o, app
        self.bind(minimum_height=self.setter("height"))
        stripe = ACC if o.is_bb else (RED if lose else EDGE)
        self.add_widget(Bg(color=stripe, radius=2, size_hint_y=None, height=dp(3)))

        head = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
        head.bind(minimum_height=head.setter("height"))
        side = BoxLayout(orientation="vertical", size_hint=(None, None), width=dp(46), spacing=dp(2))
        side.bind(minimum_height=side.setter("height"))
        cb = CheckBox(size_hint=(None, None), size=(dp(36), dp(36)), active=o.sel, color=ACC)
        cb.bind(active=self._sel)
        side.add_widget(cb)
        head.add_widget(side)

        text = Tap(orientation="vertical", size_hint_y=None, spacing=dp(2))
        text.bind(minimum_height=text.setter("height"))
        code = o.pnum or o.key or "—"
        text.add_widget(lab(f"کد محصول  {code}", MUT, 11))
        text.add_widget(lab(o.name, TXT, 15, bold=True))
        bits = []
        if o.variant:
            bits.append(o.variant)
        if o.sku:
            bits.append(f"کد فروشنده {o.sku}")
        if bits:
            text.add_widget(lab("  ·  ".join(bits), MUT, 12))
        cap = "ندارد" if o.capacity in (None, "") else (n(o.capacity) if isinstance(o.capacity, (int, float)) else str(o.capacity))
        meta = f"سقف سفارش: {cap}"
        if getattr(o, "warranty", ""):
            meta += f"   ·   گارانتی: {o.warranty}"
        text.add_widget(lab(meta, MUT, 11))
        text.bind(on_release=lambda *_: app.open_url(o.url()) if o.url() else app.edit_product(o))
        head.add_widget(text)
        self.add_widget(head)

        self.add_widget(kv_row("قیمت (تومان)", n(o.price), TXT, bold=not o.has_discount(today)))
        if o.sp:
            special_on = o.has_discount(today)
            self.add_widget(kv_row("قیمت با تخفیف (تومان)", n(o.sp), ACC if special_on else MUT, bold=special_on))
            if o.sp_start or o.sp_end:
                self.add_widget(kv_row("بازه تخفیف", f"از {L.jdate(o.sp_start)} تا {L.jdate(o.sp_end)}", MUT))
        if o.buy_box is not None:
            eff = o.eff_price(today)
            if o.is_bb:
                bb = f"{n(o.buy_box)} تومان  ·  برنده"
                col = GRN
            else:
                gap = "" if eff is None else f"  ·  اختلاف {n(eff - o.buy_box)}"
                bb = f"{n(o.buy_box)} تومان{gap}"
                col = RED
            self.add_widget(kv_row("بای‌باکس", bb, col, bold=True))

        stocks = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(58), spacing=dp(8))
        stocks.add_widget(stock_pill("موجودی انبار اسنپ", o.wstock, FIELD))
        stocks.add_widget(stock_pill("موجودی مغازه", o.stock, (0.992, 0.910, 0.941, 1)))
        self.add_widget(stocks)

        bs = []
        if o.active is False:
            bs.append(badge("غیرفعال", "r"))
        if o.stock is not None and o.stock <= 0:
            bs.append(badge("ناموجود", "o"))
        elif o.stock is not None and o.stock <= app.low:
            bs.append(badge("کم‌موجودی", "o"))
        if o.has_discount(today):
            bs.append(badge("تخفیف فعال", "g"))
        elif o.discount_state(today) == "scheduled":
            bs.append(badge("تخفیف آینده", "n"))
        if o.is_bb:
            bs.append(badge("برنده بای‌باکس", "g"))
        elif o.buy_box is not None:
            bs.append(badge("بدون بای‌باکس", "r"))
        if bs:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26), spacing=dp(6))
            row.add_widget(BoxLayout())
            for b in bs:
                row.add_widget(b)
            self.add_widget(row)

        brow_ = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42), spacing=dp(8))
        eb = RBtn("ویرایش", ACC2)
        eb.height = dp(42)
        eb.size_hint_x = None
        eb.width = dp(96)
        eb.bind(on_release=lambda *_: app.edit_product(o))
        star_in = bool(o.key) and o.key in app.mylist
        sb = RBtn("در لیست من" if star_in else "افزودن به لیست", ACC if star_in else ACC2)
        sb.height = dp(42)
        sb.size_hint_x = None
        sb.width = dp(132)
        sb.bind(on_release=lambda *_: app.toggle_mylist(o))
        brow_.add_widget(eb)
        brow_.add_widget(sb)
        brow_.add_widget(BoxLayout())
        if lose:
            wb = RBtn("بردن بای‌باکس", ACC)
            wb.height = dp(42)
            wb.size_hint_x = None
            wb.width = dp(132)
            wb.bind(on_release=lambda *_: app.undercut_one(o))
            brow_.add_widget(wb)
        self.add_widget(brow_)

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
        self.uc_params = (5000, 0, 15)
        self.PF, self.Q, self.shown = set(), "", 100
        self.mylist = set()
        self.O: List[Any] = []
        self.OF = "all"
        self.log_lines = []
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
        self.bot = self._bot_mod()
        self.bot_obj = None
        self._bot_log_ready = False
        self.mylist = set(self.bot.jload(os.path.join(self.out_dir(), "mylist.json"), []) or [])

        root = BoxLayout(orientation="vertical")
        header = Bg(color=BAR, orientation="horizontal", size_hint_y=None, height=dp(58),
                    padding=[dp(14), dp(6), dp(16), dp(6)])
        vid = str(self.cfg.get("vid") or "").strip()
        self.head_sub = Label(text=fa("پنل فروشنده" + (f"  ·  {vid}" if vid else "")),
                              font_name=FONT, font_size=sp(12), color=MUT, halign="left", valign="middle")
        self.head_sub.bind(size=lambda i, s: setattr(i, "text_size", s))
        brand = Label(text=fa("اسنپ‌شاپ"), font_name=FONT_B, font_size=sp(20), color=ACC,
                      halign="right", valign="middle", size_hint_x=None, width=dp(120))
        brand.bind(size=lambda i, s: setattr(i, "text_size", s))
        header.add_widget(self.head_sub)
        header.add_widget(brand)
        root.add_widget(header)
        root.add_widget(Bg(color=ACC, size_hint_y=None, height=dp(3)))
        self.status = StatusBar(text="", font_name=FONT, font_size=sp(12), color=MUT,
                                size_hint_y=None, height=dp(26), halign="center", shorten=True, shorten_from="right")
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
            card("احراز هویت",
                 lab("کد یکتا در هدر User-Agent فرستاده می‌شود.", MUT, 12), shell(self.ent_ua),
                 lab("توکن Bearer", MUT, 12), shell(self.ent_token),
                 lab("شناسه فروشگاه", MUT, 12), shell(self.ent_vid), b),
            card("نمونه داده‌ها",
                 lab("یک نمونه از کالا، سفارش و رویداد را می‌گیرد (نام و تلفن و آدرس مشتری پنهان می‌شود) و کپی می‌کند.", MUT, 11), b2)))

        # --- products
        self.pcount = lab("", MUT, 13, halign="right")
        self._fgroups = {
            "status": ("وضعیت کالا", [("active", "فعال"), ("inactive", "غیرفعال")], True),
            "stock": ("وضعیت موجودی", [("instock", "موجود"), ("low", "کم‌موجودی"), ("oos", "ناموجود")], True),
            "bb": ("بای‌باکس", [("bbwin", "برنده بای‌باکس"), ("bblose", "بدون بای‌باکس")], True),
            "more": ("سایر", [("disc", "دارای تخفیف"), ("mylist", "لیست من")], False),
        }
        self.fmenus = {}
        self.fscroll, self.frow = chip_row()
        for gid in ("more", "bb", "stock", "status"):
            mb = MenuBtn(self._fgroups[gid][0])
            mb.bind(on_release=lambda _w, g=gid: self.open_fmenu(g))
            self.fmenus[gid] = mb
            self.frow.add_widget(mb)
        self.pchips_sv, self.pchips = chip_row()
        self.ent_q = inp("جستجو در نام محصول، کد محصول و کد فروشنده", persian=True)
        self.ent_q.on_raw = self._on_q_raw
        self.ent_low = inp("3", str(self.low), input_filter="int")
        self.ent_low.bind(text=self._on_low)
        p1 = RBtn("بروزرسانی", ACC2)
        p1.bind(on_release=lambda *_: self.get_products())
        p2 = RBtn("انتخاب همه", ACC2)
        p2.bind(on_release=lambda *_: self.sel_all(True))
        p3 = RBtn("لغو انتخاب", ACC2)
        p3.bind(on_release=lambda *_: self.sel_all(False))
        p4 = RBtn("ویرایش گروهی", ACC)
        p4.bind(on_release=lambda *_: self.bulk_edit())
        p5 = RBtn("تخفیف گروهی", ACC2)
        p5.bind(on_release=lambda *_: self.discount_campaign())
        p6 = RBtn("بای‌باکس گروهی", ACC2)
        p6.bind(on_release=lambda *_: self.undercut())
        p7 = RBtn("خروجی Excel", ACC2)
        p7.bind(on_release=lambda *_: self.export_products_xlsx())
        p8 = RBtn("بازگردانی", ACC2)
        p8.bind(on_release=lambda *_: self.open_undo())
        primary = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        primary.add_widget(p4)
        primary.add_widget(p1)
        sec_sv, sec_row = chip_row()
        sec_sv.height = dp(50)
        for btn in (p3, p2, p8, p7, p6, p5):
            btn.height = dp(42)
            btn.size_hint_x = None
            btn.texture_update()
            btn.width = max(dp(108), btn.texture_size[0] + dp(28))
            sec_row.add_widget(btn)
        low_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54), spacing=dp(8))
        low_box = shell(self.ent_low)
        low_box.size_hint_x = None
        low_box.width = dp(92)
        low_row.add_widget(low_box)
        low_row.add_widget(lab("حد هشدار کم‌موجودی", MUT, 12))
        self.ptiles = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(72), spacing=dp(8))
        self.pl = vbox()
        self.pl.spacing = dp(10)
        self.psv = page(
            lab("لیست محصولات", TXT, 18, bold=True),
            shell(self.ent_q),
            self.fscroll,
            primary,
            sec_sv,
            low_row,
            self.ptiles,
            self.pcount,
            self.pl)
        self._add("prod", self.psv)

        # --- orders
        self.ent_sd = inp("YYYY-MM-DD")
        self.ent_ed = inp("YYYY-MM-DD")
        self.ent_ord = inp("Order Number", input_filter="int")
        o1 = RBtn("نمایش لیست سفارشات")
        o1.bind(on_release=lambda *_: self.load_orders())
        o2 = RBtn("گزارش فروش (Excel)", ACC)
        o2.bind(on_release=lambda *_: self.export_sales())
        o4 = RBtn("جزئیات سفارش", ACC2)
        o4.bind(on_release=lambda *_: self.get_order())
        self.ochips_sv, self.ochips = chip_row()
        self.ol = vbox()
        self.ol.spacing = dp(10)
        self.osv = page(
            card("سفارشات و گزارش فروش",
                 lab("از تاریخ (میلادی؛ خالی = ۱۴ روز اخیر)", MUT, 12), shell(self.ent_sd),
                 lab("تا تاریخ (میلادی)", MUT, 12), shell(self.ent_ed), o1, o2),
            lab("تأیید سفارش در API اسنپ‌شاپ وجود ندارد؛ سفارشِ تأییدنشده را در وب‌سایت پنل فروشندگان تأیید کنید و بعد «نمایش لیست سفارشات» را بزنید.", AMB, 11, halign="center"),
            self.ochips_sv, self.ol,
            card("جزئیات یک سفارش", lab("شماره سفارش", MUT, 12), shell(self.ent_ord), o4))
        self._add("ord", self.osv)

        # --- automation page
        if False:   # old Android-only watcher; the full bot now runs on every platform
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
            bb6 = RBtn("خروجی Excel همه محصولات", ACC2)
            bb6.bind(on_release=lambda *_: self.export_products_xlsx())
            c_bot = card("ربات پس‌زمینه", self.bot_lbl, bb1, bb2,
                         lab("تا وقتی ربات روشن است: سفارش جدید و لغو را اعلام می‌کند، هر شب گزارش Excel می‌سازد، تعدیل خودکار بای‌باکس (در صورت روشن بودن) را انجام می‌دهد" + (" و تغییرات فایل prices.csv را روی اسنپ‌شاپ اعمال می‌کند. برنامه را Minimize کنید، نه Close." if self.desktop else ". هشدار: ربات فقط وقتی کار می‌کند که برنامه باز باشد."), MUT, 11))
            c_rp = card("تعدیل خودکار قیمت (بای‌باکس)", self.rp_btn,
                        lab("قیمت را همیشه ۵٬۰۰۰ تومان زیر قیمت نفر دوم نگه می‌دارد؛ هر ۱۰ دقیقه. اگر بای‌باکس را باخته باشی قیمت پایین می‌آید، و اگر با اختلاف زیاد برنده باشی (نفر دوم گران کرده) قیمت بالا می‌رود تا فاصله حفظ شود. وقتی بای‌باکس دست توست، قیمت هرگز پایین آورده نمی‌شود. کف قیمت: بیشترین مقدار از «ستون min_price در prices.csv»، حد پایین قیمت مرجع اسنپ‌شاپ و ۴۵٪ زیر قیمت پایه. هر حرکت نزولی حداکثر ۱۵٪ و هر حرکت صعودی حداکثر ۱۵٪ در هر دور. حالت آزمایشی فقط در گزارش می‌نویسد. هر تغییر در «بازگردانی تغییرات» (تب محصولات) ثبت می‌شود.", MUT, 11))
            c_file = card("قیمت از روی فایل (Excel)", self.dry_btn, bb3,
                          lab("۱) «ساخت فایل قیمت‌ها» را بزنید. ۲) فایل prices_export.csv را با نام prices.csv کپی کنید. ۳) ستون‌های price و stock و special_price را در Excel ویرایش و ذخیره کنید. ۴) اول در حالت آزمایشی نتیجه را در گزارش ببینید، بعد حالت آزمایشی را خاموش کنید. تغییر قیمت بیش از ۵۰٪ برای جلوگیری از اشتباه تایپی رد می‌شود.", MUT, 11))
            cards_auto = [c_bot, c_rp] + ([c_file] if self.desktop else []) + [card("فایل‌ها", bb4, bb6, *([bb5] if self.desktop else []))]
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
        clr = RBtn("پاک کردن", ACC2)
        clr.height = dp(42)
        clr.bind(on_release=lambda *_: (self.log_box.clear_widgets(), self.log_lines.clear()))
        cpa = RBtn("کپی همه", ACC)
        cpa.height = dp(42)
        cpa.bind(on_release=lambda *_: self.copy_text(self.all_log_text()))
        svf = RBtn("ذخیره فایل", ACC2)
        svf.height = dp(42)
        svf.bind(on_release=lambda *_: self.save_log_file())
        bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42), spacing=dp(8))
        for w in (clr, svf, cpa):                  # RTL: «کپی همه» at the right
            bar.add_widget(w)
        lp = BoxLayout(orientation="vertical", padding=[dp(12), dp(8), dp(12), 0], spacing=dp(6))
        lp.add_widget(bar)
        lp.add_widget(lab("برای کپی بخشی از متن، آن را نگه دارید و انتخاب کنید؛ «کپی همه» کل گزارش را کپی می‌کند.", MUT, 11, halign="center"))
        lp.add_widget(self.log_sv)
        self._add("log", lp)

        root.add_widget(self.sm)
        nav = Bg(color=BAR, border=LINE2, size_hint_y=None, height=dp(58))
        self.navs = []
        for text, name in (("اتصال", "conn"), ("محصولات", "prod"), ("سفارشات", "ord"), ("ربات", "auto"), ("گزارش", "log")):
            nb = NavBtn(text, name, self)
            self.navs.append(nb)
        for nb in reversed(self.navs):          # RTL: first tab (اتصال) on the right, گزارش on the far left
            nav.add_widget(nb)
        root.add_widget(nav)
        self.navs[0].state = "down"
        self.render_products()
        self.render_orders()
        self.log("آماده است.")
        if self.cfg.get("bot_on") and self.cfg.get("ua") and self.cfg.get("token") and self.cfg.get("vid"):
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

    def scroll_top(self, name):
        """Scroll a tab's list back to the top (used after refreshes and tab taps)."""
        sv = {"prod": getattr(self, "psv", None), "ord": getattr(self, "osv", None),
              "log": getattr(self, "log_sv", None)}.get(name)
        if sv is not None:
            sv.scroll_y = 1

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
                self.log(friendly(e), "err")
        threading.Thread(target=w, daemon=True).start()

    def open_url(self, url):
        if not url:
            self.log("شماره‌ی محصول اسنپ‌شاپ برای این کالا پیدا نشد.", "err")
            return
        try:
            if platform == "android":
                from jnius import autoclass
                Intent, Uri = autoclass("android.content.Intent"), autoclass("android.net.Uri")
                autoclass("org.kivy.android.PythonActivity").mActivity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            else:
                import webbrowser
                webbrowser.open(url)
        except Exception as e:
            self.log(f"باز کردن لینک ممکن نشد: {e}\n{url}", "err")
            self.copy_text(url)

    def copy_text(self, text):
        try:
            Clipboard.copy(str(text))
            self.status.text = fa("کپی شد ✓")
            self.status.color = GRN
        except Exception as e:
            self.log(f"کپی ناموفق بود: {e}", "err")

    def all_log_text(self):
        return "\n".join(f"[{ts}] {t}" for ts, t, _k in self.log_lines)

    def save_log_file(self):
        shown = self.write_report("report-log-" + time.strftime("%Y-%m-%d-%H%M") + ".txt", self.all_log_text().encode("utf-8-sig"))
        self.log(f"گزارش در فایل ذخیره شد:\n{shown}", "ok")

    def log(self, text, kind="info"):
        self.log_lines.append((time.strftime("%H:%M"), str(text), kind))
        del self.log_lines[:-1000]
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
        box = Bg(color=CARD, radius=18, border=EDGE, orientation="vertical", padding=dp(14), spacing=dp(10))
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
            btns.append(bt)
        for bt in reversed(btns):
            row.add_widget(bt)
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
                    title = vs[0].get("title") or "متصل"
                    self.head_sub.text = fa(f"{title}  ·  {v}")
                    self.log(f"اتصال موفق. فروشگاه: {title} ({v})", "ok")
                self.ui(done)
            else:
                self.log("فروشگاهی برای این توکن پیدا نشد.", "err")
        self.log("در حال اتصال...")
        self._run(f)

    # ---- products
    def vis(self):
        today = datetime.date.today().isoformat()
        q = self.Q
        ml = self.mylist if "mylist" in self.PF else None
        keys = [k for k in self.PF if k != "mylist"]
        return [o for o in self.P
                if (ml is None or o.key in ml)
                and L.match_all(o, keys, self.low, today) and L.match_query(o, q)]

    def _on_q_raw(self, val):
        self.Q = val.strip()
        Clock.unschedule(self._q_apply)
        Clock.schedule_once(self._q_apply, 0.35)

    def _q_apply(self, _dt):
        self.shown = 100
        self.render_products()
        self.scroll_top("prod")

    def _on_low(self, _i, val):
        v = self._fnum(val)
        if v is not None and v >= 0:
            self.low = int(v)
            Clock.unschedule(self._q_apply)
            Clock.schedule_once(self._q_apply, 0.5)

    def set_pf(self, key):
        # several filters can be active together (e.g. بای‌باکس ندارم + فعال); «همه» clears them
        if key == "all":
            self.PF = set()
        elif key in self.PF:
            self.PF.discard(key)
        else:
            self.PF.add(key)
            self.PF.discard(L.FILTER_EXCLUSIVE.get(key, ""))
        self.shown = 100
        self.render_products()
        self.scroll_top("prod")

    def open_fmenu(self, gid):
        title, opts, single = self._fgroups[gid]
        keys = [k for k, _ in opts]
        body = vbox()
        holder = {}

        def pick(key):
            def cb(*_a):
                self.apply_fmenu(keys, key, single)
                mv = holder.get("mv")
                if mv:
                    mv.dismiss()
            return cb

        for key, label in opts:
            on = key in self.PF
            bt = RBtn(("✓  " if on else "") + label, ACC if on else ACC2)
            bt.bind(on_release=pick(key))
            body.add_widget(bt)
        mv, _btns = self.modal(title, "انتخاب کنید. «پاک کردن» فقط همین فیلتر را برمی‌دارد.", body,
                               [("پاک کردن", ACC2, lambda: self.apply_fmenu(keys, None, single)),
                                ("بستن", ACC2, None)], h=0.62)
        holder["mv"] = mv

    def apply_fmenu(self, keys, key, single):
        if key is None:
            for k in keys:
                self.PF.discard(k)
        elif single:
            for k in keys:
                self.PF.discard(k)
            self.PF.add(key)
        elif key in self.PF:
            self.PF.discard(key)
        else:
            self.PF.add(key)
        self.shown = 100
        self.render_products()
        self.scroll_top("prod")

    def render_pchips(self):
        if not getattr(self, "fmenus", None):
            return
        st = "فعال" if "active" in self.PF else "غیرفعال" if "inactive" in self.PF else "وضعیت کالا"
        sk = ("موجود" if "instock" in self.PF else "کم‌موجودی" if "low" in self.PF
              else "ناموجود" if "oos" in self.PF else "وضعیت موجودی")
        bb = "برنده بای‌باکس" if "bbwin" in self.PF else "بدون بای‌باکس" if "bblose" in self.PF else "بای‌باکس"
        bits = []
        if "disc" in self.PF:
            bits.append("تخفیف")
        if "mylist" in self.PF:
            bits.append("لیست من")
        more = " · ".join(bits) if bits else "سایر"
        self.fmenus["status"].set_caption(st, st != "وضعیت کالا")
        self.fmenus["stock"].set_caption(sk, sk != "وضعیت موجودی")
        self.fmenus["bb"].set_caption(bb, bb != "بای‌باکس")
        self.fmenus["more"].set_caption(more, more != "سایر")

    def render_tiles(self):
        self.ptiles.clear_widgets()
        today = datetime.date.today().isoformat()
        P = self.P
        data = [("کل کالاها", len(P), ACC), ("ناموجود", sum(1 for o in P if L.match(o, "oos", self.low, today)), AMB),
                ("کم‌موجودی", sum(1 for o in P if L.match(o, "low", self.low, today)), AMB),
                ("بدون بای‌باکس", sum(1 for o in P if L.match(o, "bblose", self.low, today)), RED)]
        for label, v, col in reversed(data):
            t = Bg(color=CARD, radius=14, border=EDGE, shadow=True, orientation="vertical", padding=dp(4))
            t.add_widget(Label(text=n(v), font_name=FONT_B, font_size=sp(20), color=col))
            t.add_widget(Label(text=fa(label), font_name=FONT, font_size=sp(10), color=MUT))
            self.ptiles.add_widget(t)

    def render_products(self):
        self.render_tiles()
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
            if self.P and "mylist" in self.PF and not self.mylist:
                msg = "«لیست من» هنوز خالی است — روی ☆ هر محصول بزنید تا به لیست اضافه شود."
            else:
                msg = "موردی با این فیلتر پیدا نشد." if self.P else "برای نمایش، «بروزرسانی» را بزنید."
            self.pl.add_widget(lab(msg, MUT, 13, halign="center"))
        self.upd_sel()

    def _more(self):
        self.shown += 100
        self.render_products()

    def upd_sel(self):
        k = sum(1 for o in self.P if o.sel)
        self.pcount.text = fa((f"{n(len(self.vis()))} کالا یافت شد" + (f"  ·  {n(k)} انتخاب" if k else "")) if self.P else "")

    def sel_all(self, on):
        for o in self.vis():
            o.sel = on
        self.render_products()

    def toggle_mylist(self, o):
        """Add/remove a product to the user's own custom list («لیست من»). Saved to disk."""
        k = o.key
        if not k:
            return
        if k in self.mylist:
            self.mylist.discard(k)
            self.log(f"از «لیست من» حذف شد: {o.name}")
        else:
            self.mylist.add(k)
            self.log(f"به «لیست من» اضافه شد: {o.name}")
        self.bot.jsave(os.path.join(self.out_dir(), "mylist.json"), sorted(self.mylist))
        self.render_products()

    def get_products(self):
        if not self._need_vid():
            return
        def f():
            raw = self.client.products(self.vendor_id, lambda p, t: self.progress(f"دریافت محصولات: صفحه {p} از {t}"))
            def done():
                old_sel = {o.key for o in self.P if o.sel and o.key}
                self.P = [L.norm_prod(p, i) for i, p in enumerate(raw)]
                for o in self.P:
                    if o.key in old_sel:
                        o.sel = True
                self.shown = 100
                self.render_products()
                self.scroll_top("prod")
                self.log(f"تعداد محصولات: {len(raw)}", "ok")
            self.ui(done)
        self.log("در حال دریافت محصولات...")
        self._run(f)

    @property
    def undo_store(self):
        return L.UndoStore(os.path.join(self.out_dir(), "undo.json"))

    def patch(self, items, then, label="", objs=None):
        """Send items; log failures; journal the previous values (Undo); then(bad_keys) on the UI thread."""
        today = datetime.date.today().isoformat()
        before = [L.snap(o, today) for o in objs] if objs else []
        def f():
            res = self.client.patch_products(self.vendor_id, items)
            out = L.patch_outcome(items, res)
            bad = [(it.get("sku") or it.get("id"), m) for it, (g, m) in zip(items, out) if not g]
            ok = len(items) - len(bad)
            bad_keys = {k for k, _ in bad}
            if before:
                try:
                    good = [(b_, it) for b_, it in zip(before, items) if (it.get("sku") or it.get("id")) not in bad_keys]
                    self.undo_store.push(L.make_undo_entry(label or "تغییر", good))
                except Exception:
                    pass
            def done():
                if bad:
                    self.log(f"{ok} مورد انجام شد، {len(bad)} مورد ناموفق:\n" + "\n".join(f"{k}: {m}" for k, m in bad[:8]), "err")
                else:
                    self.log(f"{ok} مورد با موفقیت به‌روزرسانی شد." + (" (با دکمه‌ی «بازگردانی» می‌توانید برگردانید)" if before else ""), "ok")
                then(bad_keys)
            self.ui(done)
        self._run(f)

    # ---- undo
    def open_undo(self):
        data = list(reversed(self.undo_store.history()))
        body = vbox()
        if not data:
            body.add_widget(lab("هنوز تغییری ثبت نشده است. هر تغییر قیمت، موجودی یا تخفیف که با این برنامه یا ربات انجام شود اینجا نگهداری می‌شود.", MUT, 13))
        for e in data[:15]:
            row = Bg(color=FIELD, radius=14, border=EDGE, orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(6))
            row.bind(minimum_height=row.setter("height"))
            row.add_widget(lab(f"{e['label']}  ·  {n(e['n'])} کالا", bold=True, size=13))
            row.add_widget(lab(f"{L.jdate(e['t'])}  {e['t'][11:16]}", MUT, 11))
            for x in e["items"][:3]:
                row.add_widget(lab(L.describe_change(x), MUT, 11))
            if e["n"] > 3:
                row.add_widget(lab(f"و {n(e['n'] - 3)} کالای دیگر ...", MUT, 11))
            bt = RBtn("بازگردانی این تغییر", (0.80, 0.50, 0.15, 1))
            bt.height = dp(42)
            bt.bind(on_release=lambda _w, eid=e["id"]: self.restore_entry(eid))
            row.add_widget(bt)
            body.add_widget(row)
        self.modal("بازگردانی تغییرات", "قیمت، موجودی و تخفیف قبلی کالاها دوباره ارسال می‌شود. تخفیف‌هایی که تازه ثبت شده‌اند با پایان‌دادن به تاریخ دیروز غیرفعال می‌شوند.",
                   body, [("بستن", ACC2, None)], h=0.88)

    def restore_entry(self, eid):
        if not self._need_vid():
            return
        self.go("log")
        self.log("در حال بازگردانی...")
        def f():
            r = L.run_undo(self.client, self.vendor_id, self.undo_store, eid)
            if r is None:
                self.log("این تغییر دیگر در تاریخچه نیست.", "err")
                return
            if r["bad"]:
                self.log(f"{r['ok']} کالا بازگردانی شد، {len(r['bad'])} مورد ناموفق (برای تلاش دوباره، دوباره «بازگردانی» بزنید):\n" +
                         "\n".join(f"{k}: {m}" for k, m in r["bad"][:8]), "err")
            else:
                self.log(f"{r['ok']} کالا به حالت قبل برگشت." + (f" ({r['removed']} تخفیف جدید با تاریخ دیروز پایان یافت)" if r["removed"] else ""), "ok")
            if self.P:
                self.ui(self.get_products)
        self._run(f)

    def edit_product(self, o):
        today = datetime.date.today()
        ep = inp("Price", "" if o.price is None else str(int(o.price)), input_filter="int")
        es = inp("Stock", "" if o.stock is None else str(int(o.stock)), input_filter="int")
        ed = inp("قیمت با تخفیف", "" if not o.sp else str(int(o.sp)), input_filter="int")
        e_st = inp("YYYY-MM-DD", o.sp_start[:10] if o.sp_start else today.isoformat())
        e_en = inp("YYYY-MM-DD", o.sp_end[:10] if o.sp_end else (today + datetime.timedelta(days=30)).isoformat())
        body = vbox()
        widgets = [lab("قیمت پایه (تومان)", MUT, 12), ep, lab("موجودی", MUT, 12), es]
        if o.buy_box is not None:
            widgets.append(lab(f"قیمت نفر دوم (بای‌باکس): {n(o.buy_box)} تومان", AMB, 12, bold=True))
        widgets += [lab("قیمت با تخفیف (تومان) — خالی = بدون تغییر", MUT, 12), ed,
                    lab("شروع تخفیف (میلادی)", MUT, 12), e_st,
                    lab("پایان تخفیف (میلادی)", MUT, 12), e_en]
        for w in widgets:
            body.add_widget(w)
        def save():
            if not self._need_vid():
                return False
            try:
                pr = int(ep.text) if ep.text.strip() else o.price
                st = int(es.text) if es.text.strip() else o.stock
                kw, dsp_info = {}, None
                if ed.text.strip():
                    dsp = int(ed.text.strip())
                    if pr and dsp >= pr:
                        self.log("قیمت تخفیف باید از قیمت پایه کمتر باشد.", "err")
                        return False
                    stt = datetime.date.fromisoformat(e_st.text.strip())
                    en = datetime.date.fromisoformat(e_en.text.strip())
                    if en < stt:
                        self.log("تاریخ پایان تخفیف قبل از شروع است.", "err")
                        return False
                    kw = dict(special_price=dsp, special_price_start_at=stt.isoformat(),
                              special_price_end_at=en.isoformat(), special_price_stock=int(st))
                    dsp_info = (dsp, stt.isoformat(), en.isoformat())
                item = o.item(price=pr, stock=st, **kw)
            except Exception:
                self.log("قیمت و موجودی باید عدد باشند.", "err")
                return False
            def then(bad):
                if o.key not in bad:
                    o.price, o.stock = item["price"], item["stock"]
                    if dsp_info:
                        o.sp, o.sp_start, o.sp_end = dsp_info
                self.render_products()
            self.patch([item], then, "ویرایش یک کالا", [o])
        self.modal(o.name, o.key, body, [("انصراف", ACC2, None), ("ذخیره", ACC, save)], h=0.85)

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
            self.log(f"در حال اعمال ویرایش گروهی روی {len(changes)} کالا...")
            items = [o.item(price=p, stock=s) for o, p, s in changes]
            def then(bad):
                for o, p, s in changes:
                    if o.key not in bad:
                        o.price, o.stock = p, s
                self.render_products()
            self.patch(items, then, "ویرایش گروهی", [o for o, _p, _s in changes])
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
            self.log(f"در حال ثبت تخفیف {pct:g}٪ روی {len(plan)} کالا...")
            def then(bad):
                for o, it in plan:
                    if o.key not in bad:
                        o.sp, o.sp_start, o.sp_end = it["special_price"], st.isoformat(), en.isoformat()
                self.render_products()
            self.patch([it for _o, it in plan], then, "تخفیف گروهی", [o for o, _it in plan])
        self.modal("تخفیف گروهی", f"{n(len(sel))} کالا انتخاب شده است. قیمت پس از تخفیف از روی قیمت پایه محاسبه می‌شود.", body,
                   [("انصراف", ACC2, None), ("ثبت تخفیف", ACC, apply)], h=0.8)

    def undercut_one(self, o):
        """One product: apply the buy-box price immediately with the last used settings
        (no preview, stays on the products tab; can be undone afterwards)."""
        if not self._need_vid():
            return
        d, f_, m_ = self.uc_params
        today = datetime.date.today().isoformat()
        rows, skipped = L.plan_undercut(self.P, d, f_, m_, today, True, only=[o])
        if not rows:
            self.log("کالایی برای قیمت‌گذاری پیدا نشد." + (f" ({skipped} کالا بدون قیمت بای‌باکس)" if skipped else ""), "err")
            return
        r = rows[0]
        if r["why"]:
            self.log(f"{o.name}: رد شد ({r['why']})", "err")
            return
        arrow = "↑" if r["up"] else "↓"
        self.log(f"{o.name}: {arrow} {n(r['old'])} ← {n(r['np'])} تومان   (بای‌باکس: {n(o.buy_box)} تومان)", "ok")
        def then(bad):
            if r["o"].key in bad:
                self.log("اعمال قیمت ناموفق بود.", "err")
                return
            if r["kind"] == "special":
                r["o"].sp = r["np"]
            else:
                r["o"].price = r["np"]
            self.render_products()
        self.patch([r["item"]], then, "قیمت‌گذاری زیر بای‌باکس", [r["o"]])

    def undercut(self):
        if not self.P:
            self.log("ابتدا «بروزرسانی لیست» را بزنید.", "err")
            return
        if not any(o.buy_box is not None for o in self.P):
            self.log("قیمت بای‌باکس در داده‌های اسنپ‌شاپ پیدا نشد.", "err")
            return
        if not self._need_vid():
            return
        e_d = inp("5000", "5000", input_filter="int")
        e_f = inp("اختیاری", "", input_filter="int")
        e_m = inp("15", "15", input_filter="int")
        body = vbox()
        for w in (lab("چند تومان زیر قیمت بای‌باکس", MUT, 12), e_d, lab("حداقل قیمت مجاز (اختیاری)", MUT, 12), e_f,
                  lab("حداکثر افت قیمت نسبت به قیمت فعلی (درصد)", MUT, 12), e_m,
                  lab("روی کالاهای تیک‌خورده اعمال می‌شود؛ اگر چیزی تیک نخورده باشد، روی همه‌ی کالاهای لیست فعلی (با فیلترهایی که زده‌اید). منطق: قیمت همیشه ۵٬۰۰۰ تومان زیر قیمت نفر دوم نگه داشته می‌شود — برای کالاهایی که بای‌باکس را باخته‌اند کاهش می‌یابد، و برای کالاهایی که با اختلاف زیاد برنده‌اند (نفر دوم گران کرده) افزایش می‌یابد. وقتی بای‌باکس دست شماست قیمت هرگز پایین آورده نمی‌شود. برای کالاهای دارای تخفیف، قیمت تخفیف تغییر می‌کند. قبل از ارسال، لیست را می‌بینید و بعداً می‌توانید بازگردانی کنید.", MUT, 11)):
            body.add_widget(w)
        def go_preview():
            delta, floor, mx = int(self._fnum(e_d.text) or 0), int(self._fnum(e_f.text) or 0), float(self._fnum(e_m.text) or 15)
            self.uc_params = (delta, floor, mx)
            sel = [o for o in self.P if o.sel]
            self._undercut_preview(sel if sel else self.vis(), delta, floor, mx)
        self.modal("قیمت‌گذاری زیر بای‌باکس", "", body, [("انصراف", ACC2, None), ("پیش‌نمایش", ACC, go_preview)], h=0.8)


    def _undercut_preview(self, base, delta, floor, mx):
        today = datetime.date.today().isoformat()
        rows, skipped = L.plan_undercut(self.P, delta, floor, mx, today, True, only=base)
        if not rows:
            self.log("کالایی برای قیمت‌گذاری پیدا نشد." + (f" ({skipped} کالا بدون قیمت بای‌باکس)" if skipped else ""), "err")
            return
        steady = max(0, len(base) - len(rows) - skipped)
        rows = rows[:300]
        pb = vbox()
        pb.spacing = dp(10)
        checks = []
        for r in rows:
            o = r["o"]
            bad = bool(r["why"])
            up = (not bad) and r["up"]
            edge = RED if bad else (GRN if up else AMB)
            c = Bg(color=(0.992, 0.941, 0.937, 1) if bad else CARD, radius=14, border=EDGE, shadow=True,
                   orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(4))
            c.bind(minimum_height=c.setter("height"))
            c.add_widget(Bg(color=edge, radius=2, size_hint_y=None, height=dp(3)))
            hd = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
            hd.bind(minimum_height=hd.setter("height"))
            cb = CheckBox(size_hint=(None, None), size=(dp(30), dp(30)), active=not bad, disabled=bad)
            checks.append(cb)
            tx = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
            tx.bind(minimum_height=tx.setter("height"))
            tx.add_widget(lab(o.name, TXT if not bad else MUT, 14, bold=True))
            tx.add_widget(lab(o.key + (f"  ·  {o.variant}" if o.variant else ""), MUT, 11))
            hd.add_widget(tx)
            hd.add_widget(cb)
            c.add_widget(hd)
            if bad:
                c.add_widget(lab("رد شد: " + r["why"], RED, 12))
            else:
                arrow = "↑" if up else "↓"
                c.add_widget(lab(f"{arrow}  {n(r['old'])}  ←  {n(r['np'])} تومان", GRN if up else AMB, 15, bold=True))
                c.add_widget(lab(f"قیمت نفر دوم (بای‌باکس): {n(o.buy_box)} تومان", MUT, 11))
            pb.add_widget(c)
        ok = sum(1 for r in rows if not r["why"])
        n_up = sum(1 for r in rows if not r["why"] and r["up"])
        n_dn = ok - n_up
        n_bad = len(rows) - ok
        def apply():
            chosen = [r for r, cb in zip(rows, checks) if cb.active and not r["why"]]
            if not chosen:
                return
            self.log(f"در حال اعمال قیمت‌ها روی {len(chosen)} کالا...")
            def then(bad):
                for r in chosen:
                    if r["o"].key in bad:
                        continue
                    if r["kind"] == "special":
                        r["o"].sp = r["np"]
                    else:
                        r["o"].price = r["np"]
                self.render_products()
                self.log("برای دیدن وضعیت بای‌باکس، چند دقیقه بعد «بروزرسانی لیست» را بزنید.")
            self.patch([r["item"] for r in chosen], then, "قیمت‌گذاری زیر بای‌باکس", [r["o"] for r in chosen])
        sub = f"هدف: همیشه {n(delta)} تومان زیر قیمت نفر دوم"
        bits = []
        if n_dn:
            bits.append(f"{n_dn} کاهش قیمت")
        if n_up:
            bits.append(f"{n_up} افزایش قیمت")
        if n_bad:
            bits.append(f"{n_bad} رد شده")
        if steady:
            bits.append(f"{steady} بدون تغییر")
        if skipped:
            bits.append(f"{skipped} بدون داده بای‌باکس")
        if bits:
            sub += "  ·  " + "، ".join(bits)
        mv, btns = self.modal("پیش‌نمایش قیمت‌گذاری", sub, pb,
                              [("انصراف", ACC2, None), (f"اعمال روی {n(ok)} کالا", ACC, apply)])
        def upd(*_):
            k = sum(1 for r, cb in zip(rows, checks) if cb.active and not r["why"])
            btns[1].set_text(f"اعمال روی {n(k)} کالا")
        for cb in checks:
            cb.bind(active=upd)

    def export_products_xlsx(self):
        if not self.P:
            self.log("ابتدا «بروزرسانی لیست» را بزنید.", "err")
            return
        cols, rows = L.products_export_rows(self.P)
        shown = self.write_report("products-" + time.strftime("%Y-%m-%d") + ".xlsx", L.make_xlsx_multi([("محصولات", cols, rows)]))
        self.go("log")
        self.log(f"فایل Excel {len(rows)} محصول ساخته شد:\n{shown}", "ok")

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
            for s_, c_ in reversed(list(cnt.items())):
                addc(L.status_fa(s_) or "—", "st:" + s_, c_)
            addc("نیازمند آماده‌سازی", "prep", sum(1 for o in self.O if o.prep))
            addc("⏳ در انتظار اقدام", "pending", sum(1 for o in self.O if o.need_action))
            addc("همه", "all", len(self.O))
        sel = [o for o in self.O if self.OF == "all" or (self.OF == "prep" and o.prep)
               or (self.OF == "pending" and o.need_action) or self.OF == "st:" + o.status]
        sel = sorted(sel, key=lambda o: o.pickup_end or "9") if self.OF == "prep" else list(reversed(sel))
        nowt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for o in sel[:150]:
            c = TapBg(color=CARD, radius=16, border=EDGE, shadow=True, orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(4))
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
        self.scroll_top("ord")

    def load_orders(self):
        if not self._need_vid():
            return
        def f():
            d = self._orders_list()
            def done():
                self.O = [L.norm_order(o, i) for i, o in enumerate(d)]
                self.OF = "all"
                self.render_orders()
                self.scroll_top("ord")
                n_prep = sum(1 for o in self.O if o.prep)
                n_pend = sum(1 for o in self.O if o.need_action)
                self.log(f"تعداد سفارشات: {len(self.O)} · نیازمند آماده‌سازی: {n_prep} · در انتظار اقدام: {n_pend}", "ok")
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

    def _mkbot(self):
        b = self.bot.Bot(self._bot_cfg())
        if not self.desktop:                       # Android: files made by the bot must land in Downloads
            b.publish = lambda path: self.save_shared(path)
        return b

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
        b = self._mkbot()
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
        self._run(lambda: self._mkbot().export_products())

    def bot_report(self):
        if not self._need_vid():
            return
        self._attach_bot_log()
        self.go("log")
        self._run(lambda: self._mkbot().report(force=True))

    def open_folder(self):
        d = self.out_dir()
        try:
            if os.name == "nt":
                os.startfile(d)
            elif not self.desktop:
                self.log("فایل‌ها در پوشه‌ی Download گوشی ذخیره می‌شوند.", "info")
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
