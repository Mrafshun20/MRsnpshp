# -*- coding: utf-8 -*-
"""Pure logic shared by the Android app and the Windows bot (no Kivy, no network).
Built on the official SnappShop vendor API (v2.1.2) field names."""
import datetime
import io
import re
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

    @property
    def key(self) -> str:
        return self.sku or self.id

    def has_discount(self, today: str) -> bool:
        return self.sp is not None and self.sp > 0 and (not self.sp_end or self.sp_end[:10] >= today)

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


FILTERS = [("all", "همه"), ("active", "فعال"), ("inactive", "غیرفعال"), ("instock", "موجود"),
           ("low", "کم‌موجودی"), ("oos", "ناموجود"), ("disc", "دارای تخفیف")]


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
    return True


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
    num = e.get("order_number")
    items = e.get("items") or []
    total = sum(to_num(it.get("final_price")) or 0 for it in items if isinstance(it, dict))
    extra = f" | {len(items)} items | {int(total):,}" if t == "NEW_ORDER" and items else ""
    if t == "CHANGE_STATUS":
        extra = f" -> {e.get('new_status')}"
    return f"{t} order {num} at {e.get('event_at')}{extra}"


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
    by_pn = {p.pnum: p for p in (prods or []) if p.pnum}
    by_id = {p.id: p for p in (prods or []) if p.id}
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
            p = by_pn.get(str(it.get("product_number") or "")) or by_id.get(str(it.get("vendor_product_info_id") or ""))
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
            "special_start", "special_end", "special_stock"]
    rows = [{"sku": p.sku, "id": p.id, "title": p.name, "price": p.price, "stock": p.stock,
             "warehouse_stock": p.wstock, "active": p.active, "special_price": p.sp,
             "special_start": p.sp_start, "special_end": p.sp_end, "special_stock": p.sp_stock} for p in prods]
    return cols, rows
