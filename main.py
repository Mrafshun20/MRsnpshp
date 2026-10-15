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

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import Label as CoreLabel, LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior, ToggleButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

import arabic_reshaper
try:
    from bidi.algorithm import get_display
except ImportError:
    from bidi import get_display

import core
import logic as L

# ---------------- theme ----------------
BG = (0.047, 0.043, 0.094, 1)
BAR = (0.078, 0.070, 0.145, 1)
CARD = (0.108, 0.098, 0.192, 1)
FIELD = (0.062, 0.057, 0.118, 1)
CHIP = (0.165, 0.150, 0.275, 1)
ACC = (0.80, 0.24, 0.82, 1)          # SnappShop magenta
ACC_TXT = (0.94, 0.64, 0.96, 1)      # light magenta for titles / active tab
GRN = (0.32, 0.86, 0.55, 1)
RED = (1.00, 0.45, 0.48, 1)
AMB = (1.00, 0.78, 0.25, 1)
TXT = (0.93, 0.93, 0.97, 1)
MUT = (0.62, 0.62, 0.76, 1)
# button looks: (top colour, bottom colour, text colour)
VARIANTS = {
    "pri":  ((0.88, 0.34, 0.88, 1), (0.62, 0.18, 0.80, 1), (1, 1, 1, 1)),
    "sec":  ((0.27, 0.25, 0.42, 1), (0.19, 0.18, 0.32, 1), (0.93, 0.93, 0.98, 1)),
    "grn":  ((0.36, 0.84, 0.58, 1), (0.20, 0.64, 0.42, 1), (0.03, 0.14, 0.08, 1)),
    "red":  ((0.97, 0.42, 0.45, 1), (0.78, 0.24, 0.30, 1), (1, 1, 1, 1)),
    "blue": ((0.34, 0.58, 1.00, 1), (0.22, 0.42, 0.88, 1), (1, 1, 1, 1)),
    "teal": ((0.25, 0.76, 0.70, 1), (0.14, 0.58, 0.54, 1), (0.02, 0.14, 0.13, 1)),
}

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LabelBase.register(name="fa",
                   fn_regular=os.path.join(HERE, "DejaVuSans.ttf"),
                   fn_bold=os.path.join(HERE, "DejaVuSans-Bold.ttf"))
FONT = FONT_B = "fa"
Window.clearcolor = BG
Window.softinput_mode = "below_target"

_AR = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def fa(text) -> str:
    """Logical text -> what Kivy must draw (letters joined, right-to-left runs reordered)."""
    return "\n".join(get_display(arabic_reshaper.reshape(l)) for l in str(text).split("\n"))


def unfa(text) -> str:
    """Inverse of fa(): selected on-screen text -> normal Persian, so Copy/Paste works."""
    return "\n".join(L.unshape_line(l, get_display) for l in str(text).split("\n"))


def n(x) -> str:
    return "—" if x is None else f"{int(round(x)):,}"


# ---- text measuring / wrapping (a shaped string cannot be wrapped after shaping, so we wrap first)
_MEAS: Dict[Any, Any] = {}


def measure(logical, size=13) -> float:
    cl = _MEAS.get(size)
    if cl is None:
        cl = _MEAS[size] = CoreLabel(font_name=FONT, font_size=sp(size))
    try:
        return cl.get_extents(fa(logical))[0]
    except Exception:
        return len(logical) * sp(size) * 0.6


def _fit(word, max_w, size):
    lo, hi = 1, len(word)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(word[:mid], size) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return lo


def wrap_text(text, max_w, size=13) -> List[str]:
    lines: List[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            cand = (cur + " " + word) if cur else word
            if measure(cand, size) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while len(word) > 1 and measure(word, size) > max_w:
                k = _fit(word, max_w, size)
                lines.append(word[:k])
                word = word[k:]
            cur = word
        lines.append(cur)
    return lines


# ---------------- widgets ----------------
class Bg(BoxLayout):
    """BoxLayout with a rounded background, optional hairline border and soft shadow."""
    def __init__(self, color=CARD, radius=0, border=False, shadow=False, **kw):
        super().__init__(**kw)
        self._rad = dp(radius)
        with self.canvas.before:
            if shadow:
                Color(0, 0, 0, 0.30)
                self._bg_sh = RoundedRectangle(radius=[self._rad])
            else:
                self._bg_sh = None
            self._bg_c = Color(*color)
            self._bg_r = RoundedRectangle(radius=[self._rad])
            if border and radius > 0:
                Color(1, 1, 1, 0.07)
                self._bg_b = Line(width=1)
            else:
                self._bg_b = None
        self.bind(pos=self._u, size=self._u)
        self._u()

    def _u(self, *_):
        x, y = self.pos
        w, h = self.size
        self._bg_r.pos, self._bg_r.size = (x, y), (w, h)
        if self._bg_sh is not None:
            self._bg_sh.pos, self._bg_sh.size = (x, y - dp(2)), (w, h)
        if self._bg_b is not None:
            self._bg_b.rounded_rectangle = (x, y, w, h, self._rad)


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


class StyledInput(TextInput):
    """TextInput with a rounded field background and an accent border while focused."""
    def __init__(self, **kw):
        base = dict(font_name=FONT, font_size=sp(16), size_hint_y=None, height=dp(50), multiline=False,
                    padding=[dp(14), dp(14), dp(14), dp(10)], background_normal="", background_active="",
                    background_color=(0, 0, 0, 0), foreground_color=TXT, hint_text_color=MUT,
                    cursor_color=ACC_TXT, selection_color=(ACC[0], ACC[1], ACC[2], 0.35), write_tab=False)
        base.update(kw)
        super().__init__(**base)
        with self.canvas.before:
            Color(*FIELD)
            self._bgr = RoundedRectangle(radius=[dp(12)])
            self._brc = Color(1, 1, 1, 0.10)
            self._brl = Line(width=1)
        self.bind(pos=self._ub, size=self._ub, focus=self._uf)
        self._ub()

    def _ub(self, *_):
        x, y = self.pos
        w, h = self.size
        self._bgr.pos, self._bgr.size = (x, y), (w, h)
        self._brl.rounded_rectangle = (x, y, w, h, dp(12))

    def _uf(self, _i, f):
        self._brc.rgba = (ACC[0], ACC[1], ACC[2], 0.9) if f else (1, 1, 1, 0.10)


class FaInput(StyledInput):
    """Single-line field for Persian/Arabic text.

    Kivy's TextInput cannot join Persian letters or order right-to-left text, so the real (logical)
    text stays in .text - search, IME and paste keep working - and a label on top draws the shaped
    version. The caret is pinned to the end of the text (editing = type at the end / backspace /
    the x button), which is what the search box needs."""
    def __init__(self, hint="", text="", **kw):
        self._fa_hint = hint
        super().__init__(text=text, **kw)
        self.foreground_color = (0, 0, 0, 0)       # hide the raw, unshaped glyphs
        self.cursor_color = (0, 0, 0, 0)
        self.selection_color = (0, 0, 0, 0)
        for k, v in (("use_bubble", False), ("use_handles", False)):
            try:
                setattr(self, k, v)
            except Exception:
                pass
        self._fa_ov = Label(font_name=FONT, font_size=sp(16), color=TXT, halign="right", valign="middle",
                         max_lines=1, shorten=True)
        self._fa_x = Label(text="✕", font_name=FONT_B, font_size=sp(15), color=MUT, size_hint=(None, None),
                        size=(dp(34), dp(34)))
        self.add_widget(self._fa_ov)
        self.add_widget(self._fa_x)
        with self.canvas.after:
            self._fa_cc = Color(ACC_TXT[0], ACC_TXT[1], ACC_TXT[2], 0)
            self._fa_cr = Rectangle(size=(dp(2), dp(22)))
        self.bind(pos=self._lay, size=self._lay, text=self._lay, focus=self._focus)
        self._lay()

    def _lay(self, *_):
        pad = dp(14)
        txt = self.text
        left = dp(36) if txt else 0
        ov = self._fa_ov
        ov.pos = (self.x + pad + left, self.y)
        ov.size = (max(dp(10), self.width - 2 * pad - left), self.height)
        ov.text_size = ov.size
        rtl = (not txt) or bool(_AR.search(txt))
        ov.halign = "right" if rtl else "left"
        ov.shorten_from = "right" if rtl else "left"
        ov.text = fa(txt if txt else self._fa_hint)
        ov.color = TXT if txt else MUT
        self._fa_x.opacity = 1 if txt else 0
        self._fa_x.pos = (self.x + dp(4), self.center_y - dp(17))
        ink = min(measure(txt, 16), ov.width) if txt else 0
        cx = (ov.right - ink - dp(3)) if rtl else (ov.x + ink + dp(1))
        self._fa_cr.pos = (cx, self.center_y - dp(11))

    def _focus(self, _i, f):
        Clock.unschedule(self._tick)
        self._fa_cc.a = 1 if f else 0
        if f:
            Clock.schedule_interval(self._tick, 0.55)

    def _tick(self, _dt):
        self._fa_cc.a = 0 if self._fa_cc.a else 1

    # --- keep the (invisible) caret at the end so typed text always appends
    def _pin(self):
        try:
            self.cancel_selection()
            self.cursor = self.get_cursor_from_index(len(self.text))
        except Exception:
            pass

    def insert_text(self, substring, from_undo=False):
        self._pin()
        return super().insert_text(substring.replace("\n", " "), from_undo=from_undo)

    def do_backspace(self, *a, **k):
        self._pin()
        return super().do_backspace(*a, **k)

    def do_cursor_movement(self, *a, **k):
        self._pin()

    def on_touch_down(self, touch):
        if self.text and self.collide_point(*touch.pos) and touch.x < self.x + dp(42):
            self.text = ""
            return True
        r = super().on_touch_down(touch)
        self._pin()
        return r


def inp(hint, text="", **kw):
    ti = StyledInput(hint_text=hint, text=text, **kw)
    try:
        ti.halign = "right"
    except Exception:
        pass
    return ti


_GRAD: Dict[Any, Any] = {}


def grad_tex(top, bot):
    """1x2 texture, stretched with linear filtering = vertical gradient (first row is the bottom)."""
    k = (top, bot)
    t = _GRAD.get(k)
    if t is None:
        t = Texture.create(size=(1, 2), colorfmt="rgba")
        t.blit_buffer(bytes(int(max(0.0, min(1.0, c)) * 255) for c in (*bot, *top)), colorfmt="rgba", bufferfmt="ubyte")
        t.mag_filter = "linear"
        t.min_filter = "linear"
        _GRAD[k] = t
    return t


class RBtn(ButtonBehavior, Label):
    """Rounded gradient button with a soft shadow. kind: pri | sec | grn | red | blue | teal."""
    def __init__(self, text, kind="pri", icon="", height=50, **kw):
        top, bot, fg = VARIANTS.get(kind, VARIANTS["pri"])
        self._h = dp(height)
        self._icon = icon
        super().__init__(text=fa(f"{icon}  {text}" if icon else text), font_name=FONT_B, font_size=sp(15),
                         color=fg, size_hint_y=None, height=self._h, halign="center", valign="middle", **kw)
        with self.canvas.before:
            Color(0, 0, 0, 0.35)
            self._sh = RoundedRectangle(radius=[dp(14)])
            self._col = Color(1, 1, 1, 1)
            self._r = RoundedRectangle(radius=[dp(14)], texture=grad_tex(top, bot))
        self.bind(pos=self._u, size=self._u)
        self.bind(width=lambda i, w: setattr(i, "text_size", (max(0, w - dp(20)), None)))
        self.bind(texture_size=lambda i, s: setattr(i, "height", max(i._h, s[1] + dp(22))))
        self._u()

    def _u(self, *_):
        x, y = self.pos
        w, h = self.size
        self._r.pos, self._r.size = (x, y), (w, h)
        self._sh.pos, self._sh.size = (x, y - dp(2)), (w, h)

    def set_text(self, t):
        self.text = fa(f"{self._icon}  {t}" if self._icon else t)

    def on_press(self):
        self._col.rgba = (0.78, 0.78, 0.78, 1)

    def on_release(self):
        self._col.rgba = (1, 1, 1, 1)


class Chip(ButtonBehavior, Label):
    def __init__(self, text, key, active=False, **kw):
        super().__init__(text=fa(text), font_name=FONT_B, font_size=sp(13),
                         color=(1, 1, 1, 1) if active else MUT, size_hint=(None, None), height=dp(36),
                         pos_hint={"center_y": 0.5}, **kw)
        self.key = key
        self.texture_update()
        self.width = self.texture_size[0] + dp(30)
        with self.canvas.before:
            Color(*(ACC if active else CHIP))
            self._r = RoundedRectangle(radius=[dp(18)])
        self.bind(pos=self._u, size=self._u)
        self._u()

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size


def chip_row():
    """Horizontally scrolling chips, right-to-left: the first chip sits at the right edge."""
    sv = ScrollView(size_hint_y=None, height=dp(46), do_scroll_y=False, bar_width=0)
    row = BoxLayout(orientation="horizontal", size_hint_x=None, spacing=dp(8), padding=[dp(2), 0, dp(2), 0])

    def fit(*_):
        row.width = max(row.minimum_width, sv.width)
    row.bind(minimum_width=fit)
    sv.bind(width=fit)
    sv.add_widget(row)
    return sv, row


def set_chips(sv, row, chips):
    row.clear_widgets()
    row.add_widget(Widget())                       # takes the free space so the chips hug the right edge
    for c in reversed(chips):
        row.add_widget(c)
    Clock.schedule_once(lambda _dt: setattr(sv, "scroll_x", 1), 0)


def badge(text, kind):
    bg, fg = {"r": ((0.32, 0.12, 0.14, 1), RED), "g": ((0.07, 0.24, 0.14, 1), GRN),
              "o": ((0.31, 0.23, 0.07, 1), AMB), "n": (CHIP, (0.72, 0.74, 0.92, 1)),
              "p": ((0.30, 0.10, 0.32, 1), ACC_TXT)}[kind]
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
    c = Bg(color=CARD, radius=16, border=True, shadow=True, orientation="vertical", size_hint_y=None,
           padding=dp(14), spacing=dp(10))
    c.bind(minimum_height=c.setter("height"))
    if title:
        c.add_widget(lab(title, ACC_TXT, 15, bold=True))
    for w in widgets:
        c.add_widget(w)
    return c


def page(*widgets):
    sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
    box = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(12), size_hint_y=None)
    box.bind(minimum_height=box.setter("height"))
    for w in widgets:
        box.add_widget(w)
    sv.add_widget(box)
    return sv


def hrow(*widgets, height=50, spacing=8):
    """A horizontal row in right-to-left order: the first widget ends up at the right."""
    r = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(height), spacing=dp(spacing))
    for w in reversed(widgets):
        r.add_widget(w)
    return r


class LogView(TextInput):
    """Read-only log you can select from: long-press / drag, then Copy (bubble or Ctrl+C).
    Lines are shaped and wrapped by us (see App._render_log); Copy turns them back into normal text."""
    def __init__(self, **kw):
        super().__init__(readonly=True, multiline=True, font_name=FONT, font_size=sp(13),
                         background_normal="", background_active="", background_color=(0, 0, 0, 0),
                         foreground_color=TXT, cursor_color=(0, 0, 0, 0),
                         selection_color=(ACC[0], ACC[1], ACC[2], 0.40),
                         padding=[dp(10), dp(10), dp(10), dp(10)], **kw)
        for k, v in (("do_wrap", False), ("halign", "right")):
            try:
                setattr(self, k, v)
            except Exception:
                pass

    def copy(self, data=""):
        txt = data or self.selection_text
        if txt:
            Clipboard.copy(unfa(str(txt)))


class NavBtn(ToggleButtonBehavior, BoxLayout):
    def __init__(self, text, icon, name, app, **kw):
        super().__init__(orientation="vertical", padding=[0, dp(7), 0, dp(3)], group="nav",
                         allow_no_selection=False, **kw)
        self.name, self.app = name, app
        self.ic = Label(text=icon, font_name=FONT_B, font_size=sp(19), color=MUT)
        self.tx = Label(text=fa(text), font_name=FONT_B, font_size=sp(11), color=MUT, size_hint_y=None, height=dp(16))
        self.add_widget(self.ic)
        self.add_widget(self.tx)
        with self.canvas.before:
            self._pc = Color(ACC[0], ACC[1], ACC[2], 0)
            self._pill = RoundedRectangle(radius=[dp(2)])
        self.bind(pos=self._u, size=self._u)
        self._u()

    def _u(self, *_):
        self._pill.pos = (self.x + self.width / 2 - dp(18), self.top - dp(3))
        self._pill.size = (dp(36), dp(3))

    def on_state(self, _w, st):
        on = st == "down"
        self.ic.color = self.tx.color = ACC_TXT if on else MUT
        self._pc.a = 1 if on else 0
        if on:
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
            if "prices.csv applied" in msg or msg.startswith("Undo"):
                self.app.ui(self.app.refresh_undo)
        except Exception:
            pass


class ProdCard(Bg):
    def __init__(self, o, app, **kw):
        super().__init__(color=CARD, radius=14, border=True, orientation="vertical", size_hint_y=None,
                         padding=dp(12), spacing=dp(6), **kw)
        self.o, self.app = o, app
        self.bind(minimum_height=self.setter("height"))
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ds, bb = o.discount_state(now), o.buybox_state(now)
        top = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(10))
        top.bind(minimum_height=top.setter("height"))
        cb = CheckBox(size_hint=(None, None), size=(dp(34), dp(34)), active=o.sel)
        cb.bind(active=self._sel)
        tap = Tap(orientation="vertical", size_hint_y=None)
        tap.bind(minimum_height=tap.setter("height"))
        tap.add_widget(lab(o.name, bold=True, size=14))
        tap.add_widget(lab(f"کد {o.key}" + (f"  ·  {o.variant}" if o.variant else ""), MUT, 11))
        tap.bind(on_release=lambda *_: app.edit_product(o))
        top.add_widget(tap)                        # right-to-left: text first (left), check box at the right edge
        top.add_widget(cb)
        self.add_widget(top)
        self.add_widget(lab(f"قیمت: {n(o.price)}     موجودی: {n(o.stock)}     انبار اسنپ: {n(o.wstock)}", size=13))
        if ds in ("active", "scheduled"):
            pct = f" (٪{o.sp_pct:g})" if o.sp_pct else ""
            when = (f"از {L.jdate(o.sp_start)} " if ds == "scheduled" and o.sp_start else "") + (f"تا {L.jdate(o.sp_end)}" if o.sp_end else "")
            self.add_widget(lab(f"قیمت با تخفیف: {n(o.sp)}{pct}  {when}", ACC_TXT, 12))
        if o.buy_box:
            self.add_widget(lab(f"قیمت باکس (کمترین قیمت): {n(o.buy_box)}", GRN if bb == "win" else (AMB if bb == "lose" else MUT), 12))
        bs = []
        if o.active is False: bs.append(badge("غیرفعال", "r"))
        if o.blacklist: bs.append(badge("لیست سیاه", "r"))
        if o.stock is not None and o.stock <= 0: bs.append(badge("ناموجود", "o"))
        elif o.stock is not None and o.stock <= app.low: bs.append(badge("کم‌موجودی", "o"))
        if ds == "active": bs.append(badge("تخفیف فعال", "g"))
        elif ds == "scheduled": bs.append(badge("تخفیف زمان‌بندی‌شده", "p"))
        if bb == "win": bs.append(badge("برنده باکس", "g"))
        elif bb == "lose": bs.append(badge("رقیب ارزان‌تر", "o"))
        if bs:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            row.add_widget(Widget())
            for b in reversed(bs):                 # first badge at the right edge
                row.add_widget(b)
            self.add_widget(row)

    def _sel(self, _i, val):
        self.o.sel = val
        self.app.upd_sel()


# ---------------- app ----------------
class SnappShopApp(App):
    title = "SnappShop"

    def build(self):
        self.log_entries: List[Dict[str, Any]] = []
        self._log_trigger = Clock.create_trigger(self._render_log)
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
        # journal of changes (shared with the background bot on desktop) -> "Undo"
        self.undo = L.UndoStore(os.path.join(self.out_dir() if self.desktop else self.data_dir, "undo.json"))

        root = BoxLayout(orientation="vertical")
        header = Bg(color=BAR, orientation="vertical", size_hint_y=None, height=dp(54))
        header.add_widget(lab("پنل اسنپ‌شاپ", TXT, 18, bold=True, halign="center"))
        root.add_widget(header)
        root.add_widget(Bg(color=ACC, size_hint_y=None, height=dp(2)))
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
        b = RBtn("تست اتصال و دریافت شناسه فروشگاه", "pri", "⚡")
        b.bind(on_release=lambda *_: self.test_connection())
        b2 = RBtn("دریافت نمونه داده‌ها", "sec", "❐")
        b2.bind(on_release=lambda *_: self.dump_samples())
        self._add("conn", page(
            card("احراز هویت", lab("کد یکتا (User-Agent)", MUT, 12), self.ent_ua,
                 lab("توکن", MUT, 12), self.ent_token, lab("شناسه فروشگاه", MUT, 12), self.ent_vid, b),
            card("نمونه داده‌ها",
                 lab("یک نمونه از کالا، سفارش و رویداد را می‌گیرد (نام و تلفن و آدرس مشتری پنهان می‌شود) و کپی می‌کند.", MUT, 11), b2)))

        # --- products
        self.pcount = lab("", MUT, 12, halign="center")
        self.pchips_sv, self.pchips = chip_row()
        self.ent_q = FaInput("جستجو در نام، کد یا رنگ")
        self.ent_q.bind(text=self._on_q)
        self.ent_low = inp("3", str(self.low), input_filter="int")
        self.ent_low.bind(text=self._on_low)
        p1 = RBtn("بروزرسانی لیست", "pri", "⟳")
        p1.bind(on_release=lambda *_: self.get_products())
        p2 = RBtn("انتخاب همه", "sec", "☑")
        p2.bind(on_release=lambda *_: self.sel_all(True))
        p3 = RBtn("لغو انتخاب", "sec", "☐")
        p3.bind(on_release=lambda *_: self.sel_all(False))
        brow = hrow(p2, p3)
        p4 = RBtn("ویرایش گروهی (قیمت و موجودی)", "blue", "✎")
        p4.bind(on_release=lambda *_: self.bulk_edit())
        p5 = RBtn("تخفیف گروهی با تاریخ شروع و پایان", "teal", "★")
        p5.bind(on_release=lambda *_: self.discount_campaign())
        self.undo_lbl = lab("", MUT, 12)
        self.undo_btn = RBtn("بازگردانی آخرین تغییر", "red", "↶")
        self.undo_btn.bind(on_release=lambda *_: self.undo_last())
        hist_btn = RBtn("تاریخچه‌ی تغییرات", "sec", "▤", height=44)
        hist_btn.bind(on_release=lambda *_: self.show_history())
        self.pl = vbox()
        self.pl.spacing = dp(10)
        self._add("prod", page(
            card("", p1, brow, p4, p5, self.pcount, self.ent_q,
                 lab("حد «کم‌موجودی» (تعداد)", MUT, 12), self.ent_low, self.pchips_sv),
            card("بازگردانی (Undo)", self.undo_lbl, self.undo_btn, hist_btn),
            self.pl))

        # --- orders
        self.ent_sd = inp("1405/07/20  یا  2026-10-12")
        self.ent_ed = inp("1405/07/27  یا  2026-10-19")
        self.ent_ord = inp("Order Number", input_filter="int")
        o1 = RBtn("نمایش لیست سفارشات", "pri", "☰")
        o1.bind(on_release=lambda *_: self.load_orders())
        o2 = RBtn("گزارش فروش (Excel)", "grn", "⬇")
        o2.bind(on_release=lambda *_: self.export_sales())
        o4 = RBtn("جزئیات سفارش", "pri")
        o4.bind(on_release=lambda *_: self.get_order())
        self.ochips_sv, self.ochips = chip_row()
        self.ol = vbox()
        self.ol.spacing = dp(10)
        self._add("ord", page(
            card("سفارشات و گزارش فروش",
                 lab("از تاریخ (شمسی یا میلادی؛ خالی = ۱۴ روز اخیر)", MUT, 12), self.ent_sd,
                 lab("تا تاریخ (شمسی یا میلادی)", MUT, 12), self.ent_ed, o1, o2),
            self.ochips_sv, self.ol,
            card("جزئیات یک سفارش", lab("شماره سفارش", MUT, 12), self.ent_ord, o4)))

        # --- automation page
        if not self.desktop:
            self.ent_wi = inp("Seconds", str(self.cfg.get("watch_sec", 60)), input_filter="int")
            self.watch_lbl = lab("وضعیت: خاموش", MUT, 14, bold=True)
            self.watch_last = lab("", MUT, 12)
            w1 = RBtn("روشن کردن هشدار سفارش جدید", "grn", "▶")
            w1.bind(on_release=lambda *_: self.start_watch())
            w2 = RBtn("خاموش کردن", "red", "■")
            w2.bind(on_release=lambda *_: self.stop_watch())
            self._add("auto", page(card(
                "هشدار سفارش جدید", lab("هر چند ثانیه بررسی شود", MUT, 12), self.ent_wi,
                self.watch_lbl, self.watch_last, w1, w2,
                lab("هشدار فقط وقتی کار می‌کند که برنامه باز باشد. برای اجرای بی‌وقفه از برنامه‌ی ویندوز استفاده کنید.", MUT, 11))))
        else:
            self.ent_wi = inp("Seconds", "60")
            self.bot_lbl = lab("وضعیت ربات: خاموش", MUT, 14, bold=True)
            bb1 = RBtn("روشن کردن ربات", "grn", "▶")
            bb1.bind(on_release=lambda *_: self.start_bot())
            bb2 = RBtn("خاموش کردن ربات", "red", "■")
            bb2.bind(on_release=lambda *_: self.stop_bot())
            self.dry_btn = RBtn("", "sec")
            self._dry_text()
            self.dry_btn.bind(on_release=lambda *_: self.toggle_dry())
            bb3 = RBtn("ساخت فایل قیمت‌ها (prices_export.csv)", "sec", "⬇")
            bb3.bind(on_release=lambda *_: self.bot_export())
            bb4 = RBtn("گزارش فروش همین حالا", "sec", "☰")
            bb4.bind(on_release=lambda *_: self.bot_report())
            bb5 = RBtn("باز کردن پوشه‌ی فایل‌ها", "sec", "▤")
            bb5.bind(on_release=lambda *_: self.open_folder())
            cards_auto = [
                card("ربات پس‌زمینه", self.bot_lbl, bb1, bb2,
                     lab("تا وقتی ربات روشن است: سفارش جدید و لغو را با صدا اعلام می‌کند، تغییرات فایل prices.csv را (قیمت، موجودی، تخفیف) روی اسنپ‌شاپ اعمال می‌کند و هر شب گزارش Excel می‌سازد. برنامه را Minimize کنید، نه Close.", MUT, 11)),
                card("قیمت از روی فایل (Excel)", self.dry_btn, bb3,
                     lab("۱) «ساخت فایل قیمت‌ها» را بزنید. ۲) فایل prices_export.csv را با نام prices.csv کپی کنید. ۳) ستون‌های price و stock و special_price را در Excel ویرایش و ذخیره کنید. ۴) اول در حالت آزمایشی نتیجه را در گزارش ببینید، بعد حالت آزمایشی را خاموش کنید. تغییر قیمت بیش از ۵۰٪ برای جلوگیری از اشتباه تایپی رد می‌شود. هر تغییر واقعی در صفحه‌ی «محصولات ← بازگردانی» قابل برگشت است.", MUT, 11)),
                card("فایل‌ها", bb4, bb5)]
            if os.name == "nt":
                self.win_btn = RBtn("", "sec")
                self._win_text()
                self.win_btn.bind(on_release=lambda *_: self.toggle_winstart())
                cards_auto.append(card("ویندوز", self.win_btn,
                                       lab("با روشن شدن ویندوز، برنامه Minimize باز می‌شود و ربات (اگر روشن بوده) خودش ادامه می‌دهد. تا ربات روشن است ویندوز به حالت خواب نمی‌رود.", MUT, 11)))
            self._add("auto", page(*cards_auto))

        # --- log (selectable / copyable)
        self.log_view = LogView()
        self.log_view.bind(width=lambda *_: self._log_trigger())
        clr = RBtn("پاک کردن", "sec", "✖", height=42)
        clr.bind(on_release=lambda *_: self.clear_log())
        cpy = RBtn("کپی همه", "pri", "❐", height=42)
        cpy.bind(on_release=lambda *_: self.copy_log())
        logbox = Bg(color=CARD, radius=14, border=True, padding=dp(2))
        logbox.add_widget(self.log_view)
        lp = BoxLayout(orientation="vertical", padding=[dp(12), dp(8), dp(12), dp(8)], spacing=dp(8))
        lp.add_widget(hrow(cpy, clr, height=42))
        lp.add_widget(lab("جدیدترین پیام بالاست. برای انتخاب بخشی از متن، روی آن نگه دارید و بکشید، بعد «Copy» را بزنید.", MUT, 11))
        lp.add_widget(logbox)
        self._add("log", lp)

        root.add_widget(self.sm)
        nav = Bg(color=BAR, size_hint_y=None, height=dp(60))
        self.navs = []
        tabs = (("اتصال", "⚡", "conn"), ("محصولات", "▦", "prod"), ("سفارشات", "☰", "ord"),
                ("ربات" if self.desktop else "هشدار", "⚙", "auto"), ("گزارش", "▤", "log"))
        for text, icon, name in tabs:
            self.navs.append(NavBtn(text, icon, name, self))
        for nb in reversed(self.navs):             # right-to-left: the first tab sits at the right edge
            nav.add_widget(nb)
        root.add_widget(nav)
        self.navs[0].state = "down"
        self.render_products()
        self.render_orders()
        self.refresh_undo()
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

    # ---- log
    def log(self, text, kind="info"):
        text = str(text)[:6000]
        e = {"ts": time.strftime("%H:%M:%S"), "kind": kind, "text": text, "w": None, "lines": []}

        def _do(_dt):
            self.log_entries.append(e)
            if len(self.log_entries) > 300:
                del self.log_entries[:len(self.log_entries) - 300]
            self.status.text = fa(text.split("\n")[0][:90])
            self.status.color = {"ok": GRN, "err": RED}.get(kind, MUT)
            self._log_trigger()
        Clock.schedule_once(_do, 0)

    def _render_log(self, *_):
        lv = self.log_view
        avail = lv.width - lv.padding[0] - lv.padding[2] - dp(12)
        if avail < dp(60):
            return                                  # not laid out yet; the width binding re-triggers us
        sym = {"ok": "✔", "err": "✖"}
        blocks = []
        for e in reversed(self.log_entries):        # newest first, so the latest line is always in view
            if e["w"] != avail:
                e["lines"] = wrap_text(f"{sym.get(e['kind'], '•')} {e['ts']}  {e['text']}", avail)
                e["w"] = avail
            blocks.append("\n".join(fa(l) for l in e["lines"]))
        at_top = lv.scroll_y <= dp(8)
        lv.text = "\n\n".join(blocks)
        if at_top:
            lv.scroll_y = 0

    def copy_log(self):
        if not self.log_entries:
            self.toast("گزارشی برای کپی نیست.")
            return
        Clipboard.copy("\n".join(f"{e['ts']} {e['text']}" for e in self.log_entries))
        self.toast("کل گزارش کپی شد.")

    def clear_log(self):
        self.log_entries.clear()
        self._log_trigger()

    def toast(self, text):
        def _do(_dt):
            l = Label(text=fa(text), font_name=FONT_B, font_size=sp(13), color=TXT)
            l.texture_update()
            w = min(Window.width - dp(32), l.texture_size[0] + dp(40))
            b = Bg(color=(0.17, 0.15, 0.29, 0.98), radius=14, border=True, size_hint=(None, None),
                   size=(w, dp(44)), pos=((Window.width - w) / 2, dp(84)), opacity=0)
            b.add_widget(l)
            Window.add_widget(b)
            Animation(opacity=1, duration=0.15).start(b)

            def _rm(_d):
                a = Animation(opacity=0, duration=0.3)
                a.bind(on_complete=lambda *_: Window.remove_widget(b))
                a.start(b)
            Clock.schedule_once(_rm, 1.9)
        Clock.schedule_once(_do, 0)

    def progress(self, text):
        self.ui(lambda: setattr(self.status, "text", fa(text)))

    def modal(self, title, sub, body, buttons, h=0.86):
        mv = ModalView(size_hint=(0.94, h), auto_dismiss=True, background="", background_color=(0, 0, 0, 0),
                       overlay_color=(0, 0, 0, 0.65))
        box = Bg(color=CARD, radius=18, border=True, orientation="vertical", padding=dp(14), spacing=dp(10))
        box.add_widget(lab(title, ACC_TXT, 16, bold=True))
        if sub:
            box.add_widget(lab(sub, MUT, 12))
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        sv.add_widget(body)
        box.add_widget(sv)
        btns = []
        for text, kind, cb in buttons:
            bt = RBtn(text, kind)
            def _rel(_b, cb=cb):
                r = cb() if cb else None
                if r is not False:
                    mv.dismiss()
            bt.bind(on_release=_rel)
            btns.append(bt)
        box.add_widget(hrow(*btns))                 # first button at the right edge
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
        return [o for o in self.P if L.match(o, self.PF, self.low, today) and (not q or L.match_query(o, q))]

    def _on_q(self, _i, val):
        self.Q = val.strip()
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
        today = datetime.date.today().isoformat()
        chips = []
        for key, label in L.FILTERS:
            cnt = sum(1 for o in self.P if L.match(o, key, self.low, today))
            ch = Chip(f"{label}  {n(cnt)}", key, active=(self.PF == key))
            ch.bind(on_release=lambda c: self.set_pf(c.key))
            chips.append(ch)
        set_chips(self.pchips_sv, self.pchips, chips)

    def render_products(self):
        self.render_pchips()
        self.pl.clear_widgets()
        Lst = self.vis()
        for o in Lst[:self.shown]:
            self.pl.add_widget(ProdCard(o, self))
        if len(Lst) > self.shown:
            more = RBtn(f"نمایش بیشتر ({n(len(Lst) - self.shown)})", "sec")
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

    def patch(self, items, then, label="", targets=None):
        """Send items; log failures; remember how things were (for Undo); call then(bad_keys) on the UI thread.
        `targets` = the Prod objects behind `items` (same order), captured now = the 'before' state."""
        snaps = [L.snap(o) for o in targets] if targets else []
        def f():
            res = self.client.patch_products(self.vendor_id, items)
            out = L.patch_outcome(items, res)
            bad = [(L.item_key(it), m) for it, (ok, m) in zip(items, out) if not ok]
            good = [(s, it) for s, it, (ok, _m) in zip(snaps, items, out) if ok]
            if good:
                try:
                    self.undo.push(L.make_undo_entry(label or "تغییر", good))
                except Exception as e:
                    self.log(f"ذخیره‌ی سابقه‌ی بازگردانی ناموفق بود: {e}", "err")
            def done():
                okn = len(items) - len(bad)
                if bad:
                    self.log(f"{okn} مورد انجام شد، {len(bad)} مورد ناموفق:\n" + "\n".join(f"{k}: {m}" for k, m in bad[:8]), "err")
                else:
                    self.log(f"{okn} مورد با موفقیت به‌روزرسانی شد. (برگشت: صفحه‌ی محصولات ← بازگردانی)", "ok")
                then({k for k, _ in bad})
                self.refresh_undo()
            self.ui(done)
        self._run(f)

    def edit_product(self, o):
        ep = inp("Price", "" if o.price is None else str(int(o.price)), input_filter="int")
        es = inp("Stock", "" if o.stock is None else str(int(o.stock)), input_filter="int")
        body = vbox()
        info = []
        if o.variant:
            info.append(lab(o.variant, MUT, 12))
        if o.buy_box:
            info.append(lab(f"قیمت باکس (کمترین قیمت): {n(o.buy_box)}", MUT, 12))
        for w in (*info, lab("قیمت پایه (تومان)", MUT, 12), ep, lab("موجودی", MUT, 12), es):
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
            self.patch([item], then, f"ویرایش «{o.name[:40]}»", [o])
        self.modal(o.name, o.key, body, [("انصراف", "sec", None), ("ذخیره", "pri", save)], h=0.62)

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
            self.patch(items, then, f"ویرایش گروهی ({len(changes)} کالا)", [o for o, _p, _s in changes])
        self.modal("ویرایش گروهی", f"{n(len(sel))} کالا انتخاب شده است. فقط فیلدهای پرشده اعمال می‌شود.", body,
                   [("انصراف", "sec", None), ("اعمال", "pri", apply)], h=0.7)

    def discount_campaign(self):
        sel = [o for o in self.P if o.sel]
        if not sel:
            self.log("ابتدا کالاهای مورد نظر را انتخاب کنید (تیک بزنید).", "err")
            return
        if not self._need_vid():
            return
        today = datetime.date.today()
        e_pct = inp("مثلاً 10", "", input_filter="int")
        e_st = inp("1405/07/25  یا  2026-10-17", L.jdate(today.isoformat()))
        e_en = inp("1405/08/02  یا  2026-10-24", L.jdate((today + datetime.timedelta(days=7)).isoformat()))
        e_ds = inp("خالی = موجودی کالا", "", input_filter="int")
        body = vbox()
        for w in (lab("درصد تخفیف", MUT, 12), e_pct, lab("تاریخ شروع (شمسی یا میلادی)", MUT, 12), e_st,
                  lab("تاریخ پایان (شمسی یا میلادی)", MUT, 12), e_en, lab("موجودی مخصوص تخفیف (اختیاری)", MUT, 12), e_ds):
            body.add_widget(w)
        def apply():
            pct = self._fnum(e_pct.text)
            try:
                st = L.parse_date(e_st.text)
                en = L.parse_date(e_en.text)
            except Exception:
                self.log("تاریخ‌ها نامعتبر است. نمونه: 1405/07/25 یا 2026-10-17", "err")
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
            self.log(f"در حال ثبت تخفیف {pct:g}٪ روی {len(plan)} کالا (از {L.jdate(st.isoformat())} تا {L.jdate(en.isoformat())})...")
            def then(bad):
                for o, it in plan:
                    if o.key not in bad:
                        o.sp, o.sp_start, o.sp_end = it["special_price"], st.isoformat(), en.isoformat()
                        o.sp_stock, o.sp_pct = it["special_price_stock"], pct
                for o in sel:
                    o.sel = False
                self.render_products()
            self.patch([it for _o, it in plan], then, f"تخفیف {pct:g}٪ ({len(plan)} کالا)", [o for o, _it in plan])
        self.modal("تخفیف گروهی", f"{n(len(sel))} کالا انتخاب شده است. قیمت پس از تخفیف از روی قیمت پایه محاسبه می‌شود.", body,
                   [("انصراف", "sec", None), ("ثبت تخفیف", "pri", apply)], h=0.8)

    # ---- undo
    def refresh_undo(self):
        e = self.undo.last()
        if e:
            self.undo_lbl.text = fa(f"آخرین تغییر: {e.get('label') or 'تغییر'}\n{L.jdate(e['ts'])} {e['ts'][11:16]} · {n(e.get('n'))} کالا")
            self.undo_lbl.color = TXT
        else:
            self.undo_lbl.text = fa("تغییری برای بازگردانی وجود ندارد. هر ویرایش قیمت، موجودی یا تخفیف که از این برنامه بزنید اینجا ثبت می‌شود.")
            self.undo_lbl.color = MUT
        self.undo_btn.disabled = not e
        self.undo_btn.opacity = 1 if e else 0.4

    def undo_last(self):
        e = self.undo.last()
        if not e:
            self.toast("تغییری برای بازگردانی نیست.")
            return
        if not self._need_vid():
            return
        _items, removals, _skipped = L.revert_items(e)
        body = vbox()
        body.spacing = dp(6)
        for it in e["items"][:8]:
            body.add_widget(lab(L.describe_change(it), TXT, 12))
        if len(e["items"]) > 8:
            body.add_widget(lab(f"و {n(len(e['items']) - 8)} کالای دیگر…", MUT, 11))
        if removals:
            body.add_widget(lab(f"توجه: برای {n(removals)} کالا تخفیف تازه‌ثبت‌شده باید برداشته شود. API اسنپ‌شاپ حذف تخفیف را مستند نکرده؛ تاریخ پایان تخفیف به دیروز تغییر داده می‌شود. اگر نپذیرفت، تخفیف را از پنل فروشندگان بردارید.", AMB, 11))
        self.modal("بازگردانی آخرین تغییر",
                   f"«{e.get('label') or 'تغییر'}» — {n(len(e['items']))} کالا به مقدار قبلی برمی‌گردد. مقدارهای فعلی روی اسنپ‌شاپ جایگزین می‌شوند.",
                   body, [("انصراف", "sec", None), ("بازگردانی", "red", self._do_undo)], h=0.8)

    def _do_undo(self):
        client, vid = self.client, self.vendor_id
        self.go("log")
        self.log("در حال بازگردانی آخرین تغییر...")
        def f():
            r = L.run_undo(client, vid, self.undo)
            def done():
                if r is None:
                    self.log("تغییری برای بازگردانی نبود.", "err")
                    self.refresh_undo()
                    return
                by_key = {p.key: p for p in self.P}
                for x in r["restored"]:
                    p = by_key.get(x.get("sku") or x.get("id"))
                    b = x["before"]
                    if p is not None:
                        p.price, p.stock = b.get("price"), b.get("stock")
                        p.sp, p.sp_start, p.sp_end, p.sp_stock = b.get("sp"), b.get("sp_start") or "", b.get("sp_end") or "", b.get("sp_stock")
                self.render_products()
                self.refresh_undo()
                if r["bad"]:
                    self.log(f"{r['ok']} کالا برگشت، {len(r['bad'])} مورد ناموفق (در تاریخچه می‌ماند، دوباره بازگردانی بزنید):\n" +
                             "\n".join(f"{k}: {m}" for k, m in r["bad"][:8]), "err")
                else:
                    self.log(f"{r['ok']} کالا به مقدار قبلی برگشت.", "ok")
                if r["removals"] and not r["bad"]:
                    self.log("تخفیف‌های تازه‌ثبت‌شده با تاریخ پایانِ گذشته بسته شدند؛ در پنل فروشندگان بررسی کنید.", "info")
            self.ui(done)
        self._run(f)

    def show_history(self):
        h = list(reversed(self.undo.history()))
        body = vbox()
        if not h:
            body.add_widget(lab("هنوز تغییری ثبت نشده است.", MUT, 13, halign="center"))
        for i, e in enumerate(h):
            c = Bg(color=CHIP, radius=12, orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(2))
            c.bind(minimum_height=c.setter("height"))
            c.add_widget(lab(e.get("label") or "تغییر", TXT, 13, bold=True))
            c.add_widget(lab(f"{L.jdate(e['ts'])} {e['ts'][11:16]} · {n(e.get('n'))} کالا" + (" · آخرین (قابل بازگردانی)" if i == 0 else ""), MUT, 11))
            body.add_widget(c)
        self.modal("تاریخچه‌ی تغییرات", "بازگردانی همیشه از آخرین تغییر شروع می‌شود؛ بعد از آن، تغییر قبل‌تر.", body,
                   [("بستن", "sec", None)], h=0.8)

    # ---- orders
    def _range(self):
        out = []
        for e in (self.ent_sd, self.ent_ed):
            t = e.text.strip()
            out.append(L.parse_date(t).isoformat() if t else None)
        if out[0] and out[1] and out[1] < out[0]:
            raise ValueError("end before start")
        return out

    def _orders_list(self, sd, ed):
        return self.client.orders(self.vendor_id, sd, ed,
                                  progress=lambda p, c: self.progress(f"دریافت سفارشات: {c} سفارش..."))

    def _range_or_log(self):
        try:
            return self._range()
        except Exception:
            self.log("تاریخ‌ها نامعتبر است (یا پایان قبل از شروع است). نمونه: 1405/07/20 یا 2026-10-12", "err")
            self.go("ord")
            return None

    def render_orders(self):
        self.ol.clear_widgets()
        chips = []
        if self.O:
            cnt = {}
            for o in self.O:
                cnt[o.status] = cnt.get(o.status, 0) + 1
            def addc(label, key, c):
                ch = Chip(f"{label}  {n(c)}", key, active=(self.OF == key))
                ch.bind(on_release=lambda x: self.set_of(x.key))
                chips.append(ch)
            addc("همه", "all", len(self.O))
            addc("نیازمند آماده‌سازی", "prep", sum(1 for o in self.O if o.prep))
            for s, c in cnt.items():
                addc(L.status_fa(s) or "—", "st:" + s, c)
        set_chips(self.ochips_sv, self.ochips, chips)
        ix = L.ProdIndex(self.P)
        sel = [o for o in self.O if self.OF == "all" or (self.OF == "prep" and o.prep) or self.OF == "st:" + o.status]
        sel = sorted(sel, key=lambda o: o.pickup_end or "9") if self.OF == "prep" else list(reversed(sel))
        nowt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for o in sel[:150]:
            c = TapBg(color=CARD, radius=14, border=True, orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(4))
            c.bind(minimum_height=c.setter("height"))
            c.add_widget(lab(f"سفارش {o.num}", bold=True, size=14))
            c.add_widget(lab(f"{L.jdate(o.created)}  {o.created[11:16]}", MUT, 11))
            names = []
            for it in o.items[:3]:
                p = ix.find(it)
                if p:
                    names.append(p.name[:32])
            if names:
                more = f" (+{len(o.items) - len(names)})" if len(o.items) > len(names) else ""
                c.add_widget(lab("کالا: " + " ، ".join(names) + more, TXT, 12))
            if o.prep and o.pickup_end:
                late = o.pickup_end < nowt
                c.add_widget(lab(("مهلت تحویل به پیک گذشته: " if late else "مهلت تحویل به پیک: ") + f"{L.jdate(o.pickup_end)} {o.pickup_end[11:16]}", RED if late else AMB, 12))
            meta = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            meta.add_widget(Widget())
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
        rng = self._range_or_log()
        if rng is None:
            return
        def f():
            d = self._orders_list(*rng)
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
            ix = L.ProdIndex(self.P)
            def done():
                body = vbox()
                body.spacing = dp(2)
                def kv(k, v):
                    row = BoxLayout(orientation="horizontal", size_hint_y=None, spacing=dp(8))
                    row.bind(minimum_height=row.setter("height"))
                    kl = lab(k, MUT, 12, halign="right")
                    kl.size_hint_x = 0.34
                    row.add_widget(lab(str(v), TXT, 13, halign="right"))   # value left, key at the right edge
                    row.add_widget(kl)
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
                    p = ix.find(it)
                    kv("کالا", (p.name if p else "") or it.get("sku") or it.get("product_number"))
                    q, cq = it.get("quantity"), it.get("canceled_quantity")
                    kv("تعداد", f"{q} (لغو: {cq})")
                    kv("قیمت نهایی", n(L.to_num(it.get("final_price"))))
                self.modal(f"سفارش {num}", f"جمع: {n(o.total)}", body, [("بستن", "sec", None)])
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
        rng = self._range_or_log()
        if rng is None:
            return
        def f():
            d = self._orders_list(*rng)
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
