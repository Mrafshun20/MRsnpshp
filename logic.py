# -*- coding: utf-8 -*-
"""Pure logic shared by the Android app and the Windows bot (no Kivy, no network).
Built on the official SnappShop vendor API (v2.1.2) field names."""
import datetime
import io
import json
import os
import re
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape


def to_num(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v and abs(v) != float("inf") else None
    if isinstance(v, str):
        t = re.sub(r"[,\s\u066c\u060c]", "", v)
        if not t:
            return None
        try:
            return float(t)
        except ValueError:
            return None
    return None


def flat(o, pre="", out=None, d=0):
    if out is None:
        out = []
    if isinstance(o, dict) and d < 3:
        for k, v in o.items():
            flat(v, f"{pre}.{k}" if pre else str(k), out, d + 1)
    elif pre:
        out.append((pre, o))
    return out


# ---------------- redaction (for sample dumps) ----------------
SENS = re.compile(r"phone|mobile|\btel\b|email|national|postal|zip|latitude|longitude|\blat\b|\blng\b|address|plaque", re.I)
SENSOBJ = re.compile(r"customer|receiver|recipient|buyer|user|consignee", re.I)


def redact(o, hide=False):
    if isinstance(o, list):
        return [redact(x, hide) for x in o]
    if isinstance(o, dict):
        return {k: redact(v, hide or bool(SENSOBJ.search(k)) or bool(SENS.search(k))) for k, v in o.items()}
    if hide and isinstance(o, str):
        return "***"
    if hide and isinstance(o, (int, float)) and not isinstance(o, bool):
        return 0
    return o


# ---------------- Jalali (Persian) dates ----------------
def g2j(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jdate(s: str) -> str:
    """'2026-10-12 17:51:47' -> '1405/07/20'"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m:
        return ""
    y, mo, d = g2j(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return f"{y:04d}/{mo:02d}/{d:02d}"


def j2g(jy: int, jm: int, jd: int):
    """Jalali -> (gy, gm, gd). Raises ValueError for impossible dates (e.g. 1405/07/31)."""
    if not (1 <= jm <= 12 and 1 <= jd <= 31):
        raise ValueError("bad jalali date")
    doy = (jm - 1) * 31 + jd - 1 if jm <= 6 else 186 + (jm - 7) * 30 + jd - 1
    base = datetime.date(jy + 621, 3, 20) + datetime.timedelta(days=doy)
    for k in (0, 1, -1, 2, -2):
        c = base + datetime.timedelta(days=k)
        if g2j(c.year, c.month, c.day) == (jy, jm, jd):
            return c.year, c.month, c.day
    raise ValueError("bad jalali date")


_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})


def norm_fa(text) -> str:
    """Normalize Persian/Arabic text for searching: ي/ك, digits, ZWNJ, case."""
    t = str(text or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک").replace("ى", "ی")
    t = t.replace("\u200c", "").replace("\u200f", "").replace("\u200e", "")
    return t.lower()


def parse_date(text) -> datetime.date:
    """Accepts Gregorian or Jalali, '-' or '/', Persian digits. Raises ValueError."""
    t = norm_fa(text).strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if not m:
        raise ValueError("bad date: " + str(text))
    y, mo, d = (int(x) for x in m.groups())
    if y < 1700:
        y, mo, d = j2g(y, mo, d)
    return datetime.date(y, mo, d)


def match_query(o, q: str) -> bool:
    """Every word of the query must appear in name / English name / code / variant."""
    toks = norm_fa(q).split()
    if not toks:
        return True
    hay = norm_fa(" ".join((o.name, o.name_en, o.sku, o.id, o.pnum, o.variant)))
    return all(t in hay for t in toks)


def unshape_line(shaped: str, bidi) -> str:
    """Undo arabic_reshaper+bidi for one displayed line, so copied text is normal Persian again."""
    out = []
    for ch in bidi(shaped):
        o = ord(ch)
        out.append(unicodedata.normalize("NFKC", ch) if (0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF) else ch)
    return "".join(out)


ORDER_STATUS_FA = {"CONFIRMED": "تأیید شده", "CANCELED": "لغو شده", "CANCELLED": "لغو شده"}
EVENT_FA = {"NEW_ORDER": "سفارش جدید", "CANCELLATION": "لغو کالا", "CHANGE_STATUS": "تغییر وضعیت"}


def status_fa(s: str) -> str:
    return ORDER_STATUS_FA.get(str(s).upper(), str(s))


# ---------------- products ----------------
class Prod:
    def __init__(self, raw: dict, i: int):
        g = raw.get
        self.raw, self.i, self.sel = raw, i, False
        self.id = str(g("id") or "")
        self.sku = str(g("sku")) if g("sku") not in (None, "") else ""
        self.name = str(g("title") or g("title_en") or "(بدون نام)")
        self.pnum = str(g("product_number") or "")
        self.parent = str(g("parent_product_number") or "")
        self.vpi = str(g("vendor_product_info_id") or "")
        self.name_en = str(g("title_en") or "")
        va = g("variation_attributes") if isinstance(g("variation_attributes"), list) else []
        self.variant = "، ".join(
            f"{(v.get('attribute') or {}).get('title', '')}: {(v.get('value') or {}).get('title', '')}"
            for v in va if isinstance(v, dict) and (v.get("value") or {}).get("title"))
        self.price = to_num(g("price"))
        self.stock = to_num(g("stock"))
        self.wstock = to_num(g("warehouse_stock"))
        self.active = g("active") if isinstance(g("active"), bool) else None
        self.capacity = g("capacity")
        d = g("discount") if isinstance(g("discount"), dict) else {}
        self.sp = to_num(d.get("special_price"))
        self.sp_start = str(d.get("start_at") or "")
        self.sp_end = str(d.get("end_at") or "")
        self.sp_stock = to_num(d.get("stock"))
        self.sp_pct = to_num(d.get("percent"))
        self.buy_box = to_num(g("buy_box"))
        self.is_bb = g("is_buy_box") is True
        rp = g("reference_price") if isinstance(g("reference_price"), dict) else {}
        self.ref_lo, self.ref_hi = to_num(rp.get("lower_margin")), to_num(rp.get("upper_margin"))
        self.blacklist = g("is_blacklist") is True

    @property
    def key(self) -> str:
        return self.sku or self.id

    def discount_state(self, now: str):
        """None (no discount) | 'scheduled' | 'active' | 'expired'. `now` = 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'."""
        if not self.sp or self.sp <= 0:
            return None
        now = str(now)
        full = len(now) > 10
        cur = now[:19] if full else now[:10]
        st, en = self.sp_start[:19], self.sp_end[:19]
        if full:
            st = st + " 00:00:00" if len(st) == 10 else st
            en = en + " 23:59:59" if len(en) == 10 else en
        else:
            st, en = st[:10], en[:10]
        if st and cur < st:
            return "scheduled"
        if en and cur > en:
            return "expired"
        return "active"

    def has_discount(self, today: str) -> bool:
        return self.discount_state(today) == "active"

    def eff_price(self, now: str):
        """Price the customer really pays: active special price, else the base price."""
        return self.sp if self.has_discount(now) else self.price

    eff = eff_price

    def buybox_state(self, now: str = ""):
        if self.is_bb:
            return "win"
        return "lose" if self.buy_box is not None else None

    def url(self) -> str:
        """Product page on the SnappShop website. SnappShop addresses products as
        https://snappshop.ir/product/snp-<parent_product_number>."""
        n = (self.parent or "").strip()
        if n and not n.lower().startswith("snp-"):
            n = "snp-" + n
        return PRODUCT_URL.format(n=n) if n else ""

    def lose_bb(self, today: str) -> bool:
        return self.buybox_state(today) == "lose"

    def item(self, price=None, stock=None, **extra) -> dict:
        """PATCH item: id|sku + stock + price are mandatory in the API."""
        p = self.price if price is None else price
        s = self.stock if stock is None else stock
        if p is None or s is None:
            raise ValueError("price/stock unknown")
        it = {"sku": self.sku} if self.sku else {"id": self.id}
        it["price"], it["stock"] = int(p), int(s)
        it.update(extra)
        return it


def norm_prod(raw: dict, i: int = 0) -> Prod:
    return Prod(raw, i)


PRODUCT_URL = "https://snappshop.ir/product/{n}"   # change here if SnappShop changes its page address

# filters that cannot be combined (choosing one replaces its opposite)
FILTER_EXCLUSIVE = {"active": "inactive", "inactive": "active", "instock": "oos", "oos": "instock",
                    "bbwin": "bblose", "bblose": "bbwin"}


def match_all(o, keys, low, today) -> bool:
    """All chosen filters must match (e.g. بای‌باکس ندارم + فعال)."""
    return all(match(o, k, low, today) for k in keys)


FILTERS = [("all", "همه"), ("mylist", "⭐ لیست من"), ("active", "فعال"), ("inactive", "غیرفعال"),
           ("instock", "موجود"), ("low", "کم‌موجودی"), ("oos", "ناموجود"), ("disc", "دارای تخفیف"),
           ("bbwin", "بای‌باکس دارم"), ("bblose", "بای‌باکس ندارم")]


def match(o: Prod, key: str, low: int, today: str) -> bool:
    if key == "all":
        return True
    if key == "active":
        return o.active is True
    if key == "inactive":
        return o.active is False
    if key == "instock":
        return o.stock is not None and o.stock > 0
    if key == "low":
        return o.stock is not None and 0 < o.stock <= low
    if key == "oos":
        return o.stock is not None and o.stock <= 0
    if key == "disc":
        return o.has_discount(today)
    if key == "bbwin":
        return o.buybox_state(today) == "win"
    if key == "bblose":
        return o.buybox_state(today) == "lose"
    return True


class ProdIndex:
    """Find the product behind an order item: product_number, then vendor_product_info_id, id, sku."""
    def __init__(self, prods):
        self.pn = {p.pnum: p for p in prods or [] if p.pnum}
        self.vpi = {p.vpi: p for p in prods or [] if p.vpi}
        self.id = {p.id: p for p in prods or [] if p.id}
        self.sku = {p.sku: p for p in prods or [] if p.sku}

    def find(self, it: dict):
        return (self.pn.get(str(it.get("product_number") or "")) or self.vpi.get(str(it.get("vendor_product_info_id") or ""))
                or self.id.get(str(it.get("inventory_product_id") or "")) or self.sku.get(str(it.get("sku") or "")))


def plan_bulk(prods: List[Prod], pct=None, amt=None, stock=None):
    """Returns (changes, skipped). changes: [(prod, new_price, new_stock)]."""
    changes, skipped = [], 0
    for o in prods:
        if o.price is None or o.stock is None:
            skipped += 1
            continue
        np_ = o.price
        if pct is not None:
            np_ *= 1 + pct / 100
        if amt is not None:
            np_ += amt
        np_ = int(round(np_))
        ns = int(stock) if stock is not None else int(o.stock)
        if np_ <= 0:
            skipped += 1
            continue
        if np_ != int(o.price) or ns != int(o.stock):
            changes.append((o, np_, ns))
    return changes, skipped


def plan_discount(prods: List[Prod], pct: float, start: str, end: str, dstock=None):
    """Percent-off campaign using special_price (+ start/end dates, YYYY-MM-DD Gregorian)."""
    out, skipped = [], 0
    for o in prods:
        if o.price is None or o.stock is None:
            skipped += 1
            continue
        sp = int(round(o.price * (1 - pct / 100)))
        if sp <= 0 or sp >= o.price:
            skipped += 1
            continue
        ds = int(dstock) if dstock is not None else int(o.stock)
        out.append((o, o.item(special_price=sp, special_price_start_at=start,
                              special_price_end_at=end, special_price_stock=ds)))
    return out, skipped


def reprice_floor(o: Prod, explicit=None, max_disc_pct=45.0, today=None):
    """Lowest special_price the bot may ever set: the highest of (your min_price, SnappShop's
    reference lower margin, effective price minus max_disc_pct %).

    The base for the max_disc_pct computation is the discounted (effective) price when a
    discount is active, otherwise the base list price."""
    base = o.eff_price(today) if today else o.price
    f = [0.0]
    if explicit:
        f.append(float(explicit))
    if o.ref_lo:
        f.append(float(o.ref_lo))
    if base:
        f.append(float(base) * (1 - max_disc_pct / 100.0))
    return int(max(f) + 0.999)


def plan_reprice(prods: List[Prod], today: str, delta=5000, floors=None, max_disc_pct=45.0,
                 max_drop_pct=15.0, days=30, done_today=None, max_per_day=4, max_rise_pct=15.0):
    """Buy-box repricing through special_price, always targeting (buy_box - delta).

    The gap to the runner-up ("نفر دوم") is kept at `delta` in both directions:
      * losing (or winning by less than delta): lower the effective price to buy_box - delta;
      * winning by more than delta: RAISE the effective price to buy_box - delta, so when the
        runner-up raises their price, yours follows up instead of leaving money on the table.
    Safety: while holding the buy box the price is never lowered (only raised toward the
    target); single-move drops are capped by max_drop_pct and rises by max_rise_pct.
    Returns (changes, skips):
    changes = [(prod, patch_item, old_effective, new_price)], skips = [(prod, reason)]."""
    floors, done_today = floors or {}, done_today or {}
    changes, skips = [], []
    end_default = (datetime.date.fromisoformat(today) + datetime.timedelta(days=int(days))).isoformat()
    for o in prods:
        if o.buy_box is None:
            continue
        if o.blacklist:
            skips.append((o, "blacklisted")); continue
        if o.active is not True or not o.stock or o.stock <= 0:
            skips.append((o, "inactive or out of stock")); continue
        if o.price is None:
            continue
        eff = o.sp if o.has_discount(today) else o.price
        if eff is None:
            continue
        target = int(o.buy_box - delta)
        if target == int(eff):
            continue  # already exactly delta below the runner-up
        if not o.is_bb and o.buy_box >= eff:
            continue  # marked as losing but price already at/below the box: stale data, skip quietly
        if o.is_bb and target <= int(eff):
            continue  # holding the box: never lower the price, only follow up
        if done_today.get(o.key, 0) >= max_per_day:
            skips.append((o, f"daily limit {max_per_day} reached")); continue
        floor = reprice_floor(o, floors.get(o.key) or floors.get(o.id), max_disc_pct, today)
        if target < floor:
            skips.append((o, f"competitor {int(o.buy_box)} -> target {target} is below floor {floor}")); continue
        if target < eff:
            if eff > 0 and (eff - target) / eff * 100 > max_drop_pct:
                skips.append((o, f"drop {int(eff)}->{target} exceeds {max_drop_pct:g}% (suspicious)")); continue
        elif eff > 0 and (target - eff) / eff * 100 > max_rise_pct:
            skips.append((o, f"rise {int(eff)}->{target} exceeds {max_rise_pct:g}% (suspicious)")); continue
        if o.has_discount(today):
            start, end = (o.sp_start[:10] or today), (o.sp_end[:10] or end_default)
            ds = int(min(o.sp_stock, o.stock)) if o.sp_stock else int(o.stock)
        else:
            start, end, ds = today, end_default, int(o.stock)
        changes.append((o, o.item(special_price=target, special_price_start_at=start,
                                  special_price_end_at=end, special_price_stock=ds), int(eff), target))
    return changes, skips


def summarize_patch(results: List[dict]):
    """(ok_count, [(key, message)]) from PATCH response data."""
    ok, bad = 0, []
    for r in results or []:
        if r.get("status") is False:
            bad.append((r.get("sku") or r.get("id") or "?", "; ".join(str(m) for m in (r.get("messages") or [])) or "failed"))
        else:
            ok += 1
    return ok, bad


# ---------------- orders / events ----------------
class Order:
    def __init__(self, raw: dict, i: int):
        g = raw.get
        self.raw, self.i = raw, i
        self.num = str(g("order_number") or "")
        self.status = str(g("order_status") or "")
        self.created = str(g("created_at") or "")
        self.delivery = str(g("delivery_type") or "")
        pt = g("pickup_time") if isinstance(g("pickup_time"), dict) else {}
        self.pickup_start, self.pickup_end = str(pt.get("start") or ""), str(pt.get("end") or "")
        self.items = [it for it in (g("items") or []) if isinstance(it, dict)]
        self.total = sum(to_num(it.get("final_price")) or 0 for it in self.items)
        self.prep = self.status.upper() == "CONFIRMED"
        self.canceled = self.status.upper() in ("CANCELED", "CANCELLED")


def norm_order(raw: dict, i: int = 0) -> Order:
    return Order(raw, i)


def event_line(e: dict) -> str:
    t = str(e.get("event_type") or "")
    items = e.get("items") or []
    total = sum(to_num(it.get("final_price")) or 0 for it in items if isinstance(it, dict))
    ea = str(e.get("event_at") or "")
    msg = f"{EVENT_FA.get(t, t)} | سفارش {e.get('order_number')}"
    if t == "NEW_ORDER" and items:
        msg += f" | {len(items)} قلم | {int(total):,} تومان"
    if t == "CHANGE_STATUS":
        msg += f" | وضعیت جدید: {status_fa(e.get('new_status'))}"
    if ea:
        msg += f" | {jdate(ea)} {ea[11:16]}"
    return msg


# ---------------- Excel report ----------------
_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _x(s) -> str:
    return escape(_CTRL.sub("", str(s)), {'"': "&quot;"})


def _col(i: int) -> str:
    s, i = "", i + 1
    while i > 0:
        m = (i - 1) % 26
        s = chr(65 + m) + s
        i = (i - 1) // 26
    return s


def _sheet_xml(cols, rows) -> str:
    NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    H = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    sd = [H, f'<worksheet xmlns="{NS}"><sheetViews><sheetView rightToLeft="1" workbookViewId="0">'
             '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>']
    for i, c in enumerate(cols):
        sd.append(f'<col min="{i+1}" max="{i+1}" width="{min(40, max(12, len(str(c)) + 4))}" customWidth="1"/>')
    sd.append('</cols><sheetData><row r="1">')
    for i, c in enumerate(cols):
        sd.append(f'<c r="{_col(i)}1" s="1" t="inlineStr"><is><t>{_x(c)}</t></is></c>')
    sd.append("</row>")
    for ri, r in enumerate(rows):
        sd.append(f'<row r="{ri+2}">')
        for ci, c in enumerate(cols):
            v = r.get(c)
            if v is None or v == "":
                continue
            ref = f"{_col(ci)}{ri+2}"
            if isinstance(v, bool):
                sd.append(f'<c r="{ref}" t="b"><v>{1 if v else 0}</v></c>')
            elif isinstance(v, (int, float)):
                sd.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                sd.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_x(v)}</t></is></c>')
        sd.append("</row>")
    sd.append("</sheetData></worksheet>")
    return "".join(sd)


def make_xlsx_multi(sheets) -> bytes:
    """sheets: list of (name, cols, rows)."""
    NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    H = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    n = len(sheets)
    ct = "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n))
    sh = "".join(f'<sheet name="{_x(s[0])[:31]}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, s in enumerate(sheets))
    rel = "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(n))
    rel += f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    files = {
        "[Content_Types].xml": H + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ct + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": H + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": H + f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sh}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": H + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rel + '</Relationships>',
        "xl/styles.xml": H + f'<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    }
    for i, (_name, cols, rows) in enumerate(sheets):
        files[f"xl/worksheets/sheet{i+1}.xml"] = _sheet_xml(cols, rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_xlsx(cols, rows, sheet="Sales") -> bytes:
    return make_xlsx_multi([(sheet, cols, rows)])


SALES_COLS = [("order_number", "شماره سفارش"), ("date", "تاریخ میلادی"), ("jdate", "تاریخ شمسی"), ("time", "ساعت"),
              ("order_status", "وضعیت سفارش"), ("delivery_type", "نوع ارسال"), ("item_status", "وضعیت آیتم"),
              ("sku", "کد فروشنده (SKU)"), ("title", "نام کالا"), ("product_number", "شماره محصول"),
              ("quantity", "تعداد"), ("canceled_quantity", "لغو شده"), ("net_quantity", "تعداد خالص"),
              ("original_price", "قیمت اصلی"), ("discount_amount", "تخفیف"), ("final_price", "قیمت نهایی")]


def build_sales_workbook(orders: List[dict], prods: Optional[List[Prod]] = None, low: int = 3) -> bytes:
    ix = ProdIndex(prods)
    rows, by_sku, by_day = [], {}, {}
    for o in orders:
        num = o.get("order_number")
        created = str(o.get("created_at") or "")
        day = created[:10]
        status = str(o.get("order_status") or "")
        dd = by_day.setdefault(day, {"orders": set(), "canceled": set(), "net": 0.0, "rev": 0.0, "cq": 0.0})
        dd["orders"].add(num)
        if status.upper() in ("CANCELED", "CANCELLED"):
            dd["canceled"].add(num)
        for it in (o.get("items") or [{}]):
            q = to_num(it.get("quantity")) or 0
            cq = to_num(it.get("canceled_quantity")) or 0
            p = ix.find(it)
            sku = it.get("sku") or (p.sku if p else "") or ""
            fp = to_num(it.get("final_price")) or 0
            row = {"order_number": num, "date": day, "jdate": jdate(created), "time": created[11:19],
                   "order_status": status_fa(status), "delivery_type": o.get("delivery_type"),
                   "item_status": status_fa(it.get("item_status") or ""), "sku": sku,
                   "title": p.name if p else "", "product_number": it.get("product_number"),
                   "quantity": q, "canceled_quantity": cq, "net_quantity": q - cq,
                   "original_price": to_num(it.get("original_price")), "discount_amount": to_num(it.get("discount_amount")),
                   "final_price": fp}
            rows.append({lab: row[k] for k, lab in SALES_COLS})
            key = sku or str(it.get("product_number") or "؟")
            s = by_sku.setdefault(key, {"کد کالا": key, "نام کالا": p.name if p else "", "تعداد خالص": 0.0,
                                        "جمع قیمت نهایی": 0.0, "_o": set()})
            s["تعداد خالص"] += q - cq
            s["جمع قیمت نهایی"] += fp
            s["_o"].add(num)
            dd["net"] += q - cq
            dd["rev"] += fp
            dd["cq"] += cq
    sku_rows = [{"کد کالا": s["کد کالا"], "نام کالا": s["نام کالا"], "تعداد خالص": s["تعداد خالص"],
                 "جمع قیمت نهایی": s["جمع قیمت نهایی"], "تعداد سفارش": len(s["_o"])}
                for s in sorted(by_sku.values(), key=lambda x: -x["جمع قیمت نهایی"])]
    day_rows = [{"تاریخ میلادی": d, "تاریخ شمسی": jdate(d), "تعداد سفارش": len(v["orders"]),
                 "تعداد سفارش لغوشده": len(v["canceled"]), "تعداد کالای خالص": v["net"],
                 "تعداد کالای لغوشده": v["cq"], "جمع قیمت نهایی": v["rev"]} for d, v in sorted(by_day.items())]
    sheets = [
        ("ریز فروش", [lab for _k, lab in SALES_COLS], rows),
        ("خلاصه کالا", ["کد کالا", "نام کالا", "تعداد خالص", "جمع قیمت نهایی", "تعداد سفارش"], sku_rows),
        ("خلاصه روزانه", ["تاریخ میلادی", "تاریخ شمسی", "تعداد سفارش", "تعداد سفارش لغوشده", "تعداد کالای خالص",
                          "تعداد کالای لغوشده", "جمع قیمت نهایی"], day_rows),
    ]
    if prods:
        lows = [{"کد": p.key, "نام کالا": p.name, "موجودی": p.stock, "موجودی انبار اسنپ": p.wstock,
                 "فعال": "بله" if p.active else "خیر"}
                for p in prods if p.active is not False and p.stock is not None and p.stock <= low]
        sheets.append(("کم‌موجودی", ["کد", "نام کالا", "موجودی", "موجودی انبار اسنپ", "فعال"], lows))
    return make_xlsx_multi(sheets)


def products_export_rows(prods: List[Prod]):
    cols = ["sku", "id", "title", "price", "stock", "warehouse_stock", "active", "special_price",
            "special_start", "special_end", "special_stock", "buy_box", "is_buy_box", "ref_min", "ref_max"]
    rows = [{"sku": p.sku, "id": p.id, "title": p.name, "price": p.price, "stock": p.stock,
             "warehouse_stock": p.wstock, "active": p.active, "special_price": p.sp,
             "special_start": p.sp_start, "special_end": p.sp_end, "special_stock": p.sp_stock, "buy_box": p.buy_box, "is_buy_box": p.is_bb,
             "ref_min": p.ref_lo, "ref_max": p.ref_hi} for p in prods]
    return cols, rows


# ---------------- manual buy-box undercut (preview first) ----------------
def plan_undercut(prods: List[Prod], delta: int, floor: int, maxdrop: float, today: str, selected_only: bool, only=None,
                  maxrise: float = None):
    """Target buy_box - delta for every product with buy-box data, in both directions.

    Losers are lowered to buy_box - delta; winners whose gap to the runner-up exceeds delta
    are raised to it (so a runner-up raising their price pulls yours up too). While holding
    the buy box the price is never lowered (safety). maxrise caps a single manual raise
    (None = no cap; the user reviews every row anyway).
    Returns (rows, skipped); row = {o, np, old, why, item, kind, up} (up=True means a rise)."""
    sel = [o for o in prods if o.sel]
    if only is not None:                       # explicit list (one product, or the filtered list on screen)
        cands = list(only)
    else:
        cands = sel if (selected_only and sel) else list(prods)
    rows, skipped = [], 0
    for o in cands:
        e = o.eff_price(today)
        if o.buy_box is None or e is None or o.stock is None or o.price is None:
            skipped += 1
            continue
        np_ = int(o.buy_box - delta)
        old = int(e)
        if np_ == old:
            continue  # already exactly on target
        if not o.is_bb and o.buy_box >= e:
            continue  # stale: marked losing but already at/below the box
        if o.is_bb and np_ <= old:
            continue  # holding the box: never lower, only follow up
        lowest = reprice_floor(o, floor or None, 45.0, today)
        why = ""
        if o.blacklist:
            why = "در لیست سیاه"
        elif o.active is False or o.stock <= 0:
            why = "غیرفعال/ناموجود"
        elif np_ <= 0:
            why = "قیمت نامعتبر"
        elif np_ < lowest:
            why = "زیر حداقل مجاز"
        elif maxdrop and (e - np_) / e * 100 > maxdrop:
            why = "افت قیمت بیش از حد مجاز"
        elif maxrise and (np_ - e) / e * 100 > maxrise:
            why = "افزایش قیمت بیش از حد مجاز"
        kind = "special" if o.has_discount(today) else "base"
        item = None
        if not why:
            if kind == "special":
                extra = {"special_price": np_, "special_price_start_at": o.sp_start[:10], "special_price_end_at": o.sp_end[:10]}
                if o.sp_stock is not None:
                    extra["special_price_stock"] = int(o.sp_stock)
                item = o.item(**extra)
            else:
                item = o.item(price=np_)
        rows.append({"o": o, "np": np_, "old": old, "why": why, "item": item, "kind": kind, "up": np_ > old})
    return rows, skipped


# ---------------- undo journal ----------------
_SP_KEYS = ("special_price", "special_price_start_at", "special_price_end_at", "special_price_stock")


def snap(p: Prod, today: str = "") -> dict:
    """State of a product BEFORE a change (what Undo will restore)."""
    today = today or datetime.date.today().isoformat()
    return {"id": p.id, "sku": p.sku, "key": p.key, "name": p.name, "price": p.price, "stock": p.stock,
            "sp": p.sp, "sp_start": p.sp_start[:10], "sp_end": p.sp_end[:10], "sp_stock": p.sp_stock,
            "disc": p.discount_state(today) in ("active", "scheduled")}


def _changed(b: dict, it: dict) -> bool:
    if "price" in it and b.get("price") is not None and int(it["price"]) != int(b["price"]):
        return True
    if "stock" in it and b.get("stock") is not None and int(it["stock"]) != int(b["stock"]):
        return True
    if "special_price" in it:
        same = (b.get("sp") is not None and int(it["special_price"]) == int(b["sp"])
                and str(it.get("special_price_start_at") or b["sp_start"])[:10] == b["sp_start"]
                and str(it.get("special_price_end_at") or b["sp_end"])[:10] == b["sp_end"]
                and (it.get("special_price_stock") is None or b.get("sp_stock") is None
                     or int(it["special_price_stock"]) == int(b["sp_stock"])))
        return not same
    return False


def make_undo_entry(label: str, pairs) -> dict:
    """pairs: [(snap_before, patch_item)]. Items that change nothing are not recorded."""
    items = []
    for b, it in pairs:
        if not _changed(b, it):
            continue
        after = {k: v for k, v in it.items() if k in ("price", "stock") or k in _SP_KEYS}
        items.append({"key": b["key"], "id": b["id"], "sku": b["sku"], "name": b["name"], "before": b, "after": after})
    now = datetime.datetime.now()
    return {"id": now.strftime("%Y%m%d%H%M%S%f"), "t": now.strftime("%Y-%m-%d %H:%M:%S"), "label": label,
            "n": len(items), "items": items}


def revert_items(entry: dict, today=None):
    """-> (patch_items, removals, skipped). removals = new discounts that can only be ended, not deleted."""
    today = today or datetime.date.today()
    y = (today - datetime.timedelta(days=1)).isoformat()
    out, rem, skipped = [], 0, 0
    for x in entry.get("items", []):
        b, a = x["before"], x.get("after", {})
        if b.get("price") is None or b.get("stock") is None:
            skipped += 1
            continue
        r = {"sku": b["sku"]} if b.get("sku") else {"id": b["id"]}
        r["price"], r["stock"] = int(b["price"]), int(b["stock"])
        if any(k in a for k in _SP_KEYS):
            if b.get("disc") and b.get("sp"):
                r["special_price"] = int(b["sp"])
                r["special_price_start_at"], r["special_price_end_at"] = b["sp_start"], b["sp_end"]
                if b.get("sp_stock") is not None:
                    r["special_price_stock"] = int(b["sp_stock"])
            else:
                rem += 1
                r["special_price"] = int(a.get("special_price") or 1)
                r["special_price_start_at"] = r["special_price_end_at"] = y
        out.append(r)
    return out, rem, skipped


def patch_outcome(items: List[dict], results: List[dict]):
    """[(ok, message)] aligned with `items`; matches by sku/id, falls back to position."""
    res = list(results or [])
    out = [(True, "")] * len(items)
    def msg(r):
        return "; ".join(str(m) for m in (r.get("messages") or [])) or "failed"
    matched = False
    for i, it in enumerate(items):
        for r in res:
            if (r.get("sku") and r.get("sku") == it.get("sku")) or (r.get("id") and r.get("id") == it.get("id")):
                out[i] = (False, msg(r)) if r.get("status") is False else (True, "")
                matched = True
                break
    if not matched and len(res) == len(items):
        out = [(False, msg(r)) if r.get("status") is False else (True, "") for r in res]
    return out


def describe_change(x: dict) -> str:
    """One Persian line: what pressing Undo will do for this product (current -> restored)."""
    a, b = x.get("after", {}), x["before"]
    parts = []
    if "price" in a and b.get("price") is not None:
        parts.append(f"قیمت {int(a['price']):,} به {int(b['price']):,}")
    if "stock" in a and b.get("stock") is not None:
        parts.append(f"موجودی {int(a['stock'])} به {int(b['stock'])}")
    if "special_price" in a:
        parts.append(f"تخفیف {int(a['special_price']):,} به " + (f"{int(b['sp']):,}" if b.get("disc") and b.get("sp") else "بدون تخفیف"))
    return f"{x.get('name', '')[:40]}: " + " · ".join(parts)


class UndoStore:
    MAX_ENTRIES = 20

    def __init__(self, path: str):
        self.path = path

    def history(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return [e for e in d if isinstance(e, dict) and "items" in e and "n" in e] if isinstance(d, list) else []
        except Exception:
            return []

    def _save(self, data: list):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data[-self.MAX_ENTRIES:], f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def push(self, entry: dict):
        if not entry or not entry.get("n"):
            return
        self._save(self.history() + [entry])

    def last(self):
        h = self.history()
        return h[-1] if h else None

    def get(self, eid: str):
        return next((e for e in self.history() if e.get("id") == eid), None)

    def remove(self, eid: str):
        self._save([e for e in self.history() if e.get("id") != eid])

    def replace(self, entry: dict):
        self._save([entry if e.get("id") == entry.get("id") else e for e in self.history()])


def run_undo(client, vid: str, store: UndoStore, entry_id=None):
    """Send the restore items. Entries fully restored are removed; failed products stay for a retry."""
    e = store.get(entry_id) if entry_id else store.last()
    if not e:
        return None
    items, rem, skipped = revert_items(e)
    if not items:
        store.remove(e["id"])
        return {"ok": 0, "bad": [], "restored": [], "removed": rem, "skipped": skipped}
    out = patch_outcome(items, client.patch_products(vid, items))
    ok, bad, restored = 0, [], []
    for it, (good, m) in zip(items, out):
        if good:
            ok += 1
            restored.append(it)
        else:
            bad.append((it.get("sku") or it.get("id"), m))
    if not bad:
        store.remove(e["id"])
    else:
        failed = {k for k, _ in bad}
        e["items"] = [x for x in e["items"] if (x["before"].get("sku") or x["before"].get("id")) in failed]
        e["n"] = len(e["items"])
        store.replace(e)
    return {"ok": ok, "bad": bad, "restored": restored, "removed": rem, "skipped": skipped}
