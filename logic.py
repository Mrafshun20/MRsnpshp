# -*- coding: utf-8 -*-
"""Pure logic (no Kivy): field detection, order classification, Excel export, redaction."""
import io
import re
import zipfile
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

# ---------------- helpers ----------------
def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


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


def find(o, names, fl=None):
    if fl is None:
        fl = flat(o)
    for name in names:
        best = None
        for path, val in fl:
            seg = path.split(".")
            if norm(seg[-1]) != name or val is None or isinstance(val, (dict, list)):
                continue
            if best is None or len(seg) < best[2]:
                best = (path, val, len(seg))
        if best:
            return {"path": best[0], "value": best[1]}
    return None


NAMEK = ["title", "name", "productname", "producttitle", "titlefa", "namefa"]
SKUK = ["sku", "vendorsku", "sellersku", "productcode", "code", "id"]
PRICEK = ["price", "sellingprice", "saleprice", "finalprice", "currentprice"]
STOCKK = ["stock", "quantity", "inventory", "qty", "stockcount", "availablestock"]
ACTK = ["active", "isactive", "enabled", "isenabled", "status", "state", "visible", "isvisible"]
BBK = ["buybox", "isbuybox", "hasbuybox", "buyboxwinner", "isbuyboxwinner", "winbuybox", "isbuyboxowner", "iswinner"]
RANKK = ["rank", "position", "buyboxrank", "sellerrank"]
COMPK = ["buyboxprice", "lowestprice", "lowestcompetitorprice", "competitorprice", "bestprice", "firstprice",
         "lowestsellerprice", "buyboxwinnerprice", "topprice", "minimumcompetitorprice"]
INACT_RE = re.compile(r"inactive|deactiv|disabled?|draft|hidden|archiv|stopped|suspend|غیر\s*فعال|غیرفعال|متوقف|مخفی", re.I)
BOOL_KEYS = {"active", "isactive", "enabled", "isenabled", "visible", "isvisible"}


class Prod:
    def __init__(self, raw, idx):
        self.raw = raw
        self.i = idx
        self.sel = False
        self.name = "(بدون نام)"
        self.sku = ""
        self.price = None
        self.stock = None
        self.comp = None
        self.active = None
        self.bb = None
        self.inactive = self.oos = self.lose = False
        self.det: Dict[str, Optional[str]] = {}

    def calc(self):
        self.inactive = self.active is False
        self.oos = self.stock is not None and self.stock <= 0
        lose = False
        if self.bb is False:
            lose = True
        elif self.bb is not True and self.comp is not None and self.price is not None and self.price > self.comp:
            lose = True
        self.lose = lose


def norm_prod(p, idx) -> Prod:
    fl = flat(p)
    g = lambda names: find(p, names, fl)
    nm, sk, pr, st = g(NAMEK), g(SKUK), g(PRICEK), g(STOCKK)
    ac, bb, rk, cp = g(ACTK), g(BBK), g(RANKK), g(COMPK)
    if not cp:
        for path, val in fl:
            lp, ls = norm(path), norm(path.split(".")[-1])
            if ("." in path and re.search(r"buybox|lowest|competitor|firstseller|topseller|bestoffer", lp)
                    and re.fullmatch(r"price|sellingprice|amount|value|finalprice", ls)
                    and val is not None and not isinstance(val, (dict, list))):
                cp = {"path": path, "value": val}
                break
    o = Prod(p, idx)
    if nm:
        o.name = str(nm["value"])
    if sk:
        o.sku = str(sk["value"])
    o.price = to_num(pr["value"]) if pr else None
    o.stock = to_num(st["value"]) if st else None
    o.comp = to_num(cp["value"]) if cp else None
    if ac:
        v, k = ac["value"], norm(ac["path"].split(".")[-1])
        if isinstance(v, bool):
            o.active = v
        elif isinstance(v, str):
            if v == "true":
                o.active = True
            elif v == "false":
                o.active = False
            elif k in ("status", "state"):
                o.active = not INACT_RE.search(v)
        elif isinstance(v, (int, float)) and k in BOOL_KEYS:
            o.active = v != 0
    if bb:
        b = bb["value"]
        if isinstance(b, bool):
            o.bb = b
        elif b == "true" or b == 1:
            o.bb = True
        elif b == "false" or b == 0:
            o.bb = False
    if o.bb is None and rk and to_num(rk["value"]) is not None:
        o.bb = to_num(rk["value"]) == 1
    o.calc()
    o.det = {"نام": nm and nm["path"], "کد": sk and sk["path"], "قیمت": pr and pr["path"],
             "موجودی": st and st["path"], "فعال/غیرفعال": ac and ac["path"],
             "بای‌باکس": (bb and bb["path"]) or (rk and rk["path"]), "قیمت نفر اول": cp and cp["path"]}
    return o


# ---------------- orders ----------------
ONUMK = ["ordernumber", "number", "orderid", "ordercode", "code", "id"]
OSTK = ["status", "orderstatus", "statustitle", "statusname", "statuslabel", "state"]
ODTK = ["createdat", "orderdate", "placedat", "createdon", "createddate", "ordereddate", "date"]
OTOTK = ["total", "totalprice", "totalamount", "payable", "payableamount", "grandtotal", "amount", "finalprice"]


def is_shipped(s: str) -> bool:
    return bool(re.search(r"ship|sent|dispatch|handover|transit|post|ارسال|پست|در\s*راه|پیک", s, re.I)) and \
        not re.search(r"نشده|not\s*(yet\s*)?(sent|shipped)|unshipped|unsent", s, re.I)


def is_delivered(s: str) -> bool:
    return bool(re.search(r"\bdelivered\b|received|\bcomplete(d)?\b|finished|تحویل\s*مشتری|تحویل\s*شد|تحویل\s*داده\s*شد|تکمیل|دریافت\s*شده", s, re.I)) and \
        not re.search(r"undelivered|not\s*delivered|نشده", s, re.I)


class Order:
    pass


def norm_order(o, idx) -> Order:
    fl = flat(o)
    g = lambda names: find(o, names, fl)
    nu, st, dt, to = g(ONUMK), g(OSTK), g(ODTK), g(OTOTK)
    r = Order()
    r.raw, r.i = o, idx
    r.num = str(nu["value"]) if nu else ""
    r.status = str(st["value"]) if st else ""
    r.date = str(dt["value"]) if dt else ""
    r.total = to_num(to["value"]) if to else None
    r.shipped, r.delivered = is_shipped(r.status), is_delivered(r.status)
    r.snd = r.shipped and not r.delivered
    return r


def first_array(o):
    pref = ["items", "products", "lines", "orderitems", "cartitems", "skus", "details"]
    if not isinstance(o, dict):
        return None
    for name in pref:
        for k, v in o.items():
            if norm(k) == name and isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    for v in o.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return None


def scalars(o, prefix="") -> Dict[str, Any]:
    return {prefix + k: v for k, v in flat(o) if not isinstance(v, (dict, list))}


SENS = re.compile(r"phone|mobile|\btel\b|email|national|postal|zip|latitude|longitude|\blat\b|\blng\b|address|plaque|unit", re.I)
SENSOBJ = re.compile(r"customer|receiver|recipient|buyer|user|consignee", re.I)
PRI = re.compile(r"number|order.?id|date|created|status|title|name|sku|qty|quantity|count|price|total|amount|fee|commission|discount", re.I)


def sales_rows(orders: List[dict]):
    rows = []
    for o in orders:
        base = scalars(o)
        arr = first_array(o)
        if arr:
            for it in arr:
                r = dict(base)
                r.update(scalars(it, "item."))
                rows.append(r)
        else:
            rows.append(base)
    cols, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    cols = [c for c in cols if PRI.search(c)] + [c for c in cols if not PRI.search(c)]
    cols = [c for c in cols if not SENS.search(c)][:60]
    return cols, rows


# ---------------- xlsx ----------------
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


# ---------------- sales summaries (accounting) ----------------
ITSKUK = ["sku", "vendorsku", "sellersku", "productcode", "code", "id"]
ITNAMEK = ["title", "name", "productname", "producttitle"]
QTYK = ["quantity", "qty", "count"]
UPK = ["price", "unitprice", "sellingprice", "finalprice", "unitamount", "amount"]
FA_HEAD = {"ordernumber": "شماره سفارش", "orderid": "شماره سفارش", "number": "شماره سفارش", "status": "وضعیت",
           "createdat": "تاریخ", "orderdate": "تاریخ", "date": "تاریخ", "total": "مبلغ کل", "totalprice": "مبلغ کل",
           "sku": "کد کالا", "title": "نام", "name": "نام", "quantity": "تعداد", "qty": "تعداد", "price": "قیمت واحد",
           "count": "تعداد"}


def fa_header(col: str) -> str:
    tail = norm(col.split(".")[-1])
    base = FA_HEAD.get(tail)
    if not base:
        return col
    return ("کالا: " + base) if col.startswith("item.") else base


def sales_summary(orders: List[dict]):
    by_sku: Dict[str, dict] = {}
    by_day: Dict[str, dict] = {}
    for o in orders:
        t = find(o, OTOTK)
        total = to_num(t["value"]) if t else None
        d = find(o, ODTK)
        day = str(d["value"])[:10] if d else "؟"
        nu = find(o, ONUMK)
        num = str(nu["value"]) if nu else ""
        rec = by_day.setdefault(day, {"تاریخ": day, "تعداد سفارش": 0, "جمع فروش": 0.0})
        rec["تعداد سفارش"] += 1
        rec["جمع فروش"] += total or 0
        for it in first_array(o) or []:
            sk, nm = find(it, ITSKUK), find(it, ITNAMEK)
            q, p = find(it, QTYK), find(it, UPK)
            key = str(sk["value"]) if sk else "؟"
            qty = to_num(q["value"]) if q else 1
            qty = 1 if qty is None else qty
            price = to_num(p["value"]) if p else None
            r = by_sku.setdefault(key, {"کد کالا": key, "نام": str(nm["value"]) if nm else "", "تعداد": 0,
                                        "جمع فروش": 0.0, "_orders": set()})
            r["تعداد"] += qty
            r["جمع فروش"] += qty * price if price is not None else 0
            r["_orders"].add(num)
    sku_rows = []
    for r in sorted(by_sku.values(), key=lambda x: -x["جمع فروش"]):
        sku_rows.append({"کد کالا": r["کد کالا"], "نام": r["نام"], "تعداد": r["تعداد"],
                         "جمع فروش": r["جمع فروش"], "تعداد سفارش": len(r["_orders"])})
    day_rows = [by_day[k] for k in sorted(by_day)]
    return sku_rows, day_rows


def build_sales_workbook(orders: List[dict]) -> bytes:
    cols, rows = sales_rows(orders)
    head = {c: fa_header(c) for c in cols}
    drows = [{head[c]: r.get(c) for c in cols} for r in rows]
    sku_rows, day_rows = sales_summary(orders)
    return make_xlsx_multi([
        ("ریز سفارشات", [head[c] for c in cols], drows),
        ("خلاصه کالا", ["کد کالا", "نام", "تعداد", "جمع فروش", "تعداد سفارش"], sku_rows),
        ("خلاصه روزانه", ["تاریخ", "تعداد سفارش", "جمع فروش"], day_rows),
    ])


# ---------------- redaction ----------------
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


# ---------------- undercut plan ----------------
def plan_undercut(products: List[Prod], delta: int, floor: int):
    """Returns (rows, skipped). rows: dicts {o, np, why}."""
    sel = [o for o in products if o.sel]
    base = sel if sel else [o for o in products if o.lose]
    rows, skipped = [], 0
    for o in base:
        if o.comp is None or o.price is None or not o.sku:
            skipped += 1
            continue
        np_ = int(o.comp - delta)
        why = ""
        if np_ <= 0:
            why = "قیمت نامعتبر"
        elif floor and np_ < floor:
            why = "زیر حداقل مجاز"
        elif np_ >= o.price:
            why = "قیمت شما از قبل پایین‌تر است"
        rows.append({"o": o, "np": np_, "why": why})
    return rows, skipped


# ---------------- automatic repricing ----------------
def plan_auto(products: List[Prod], delta: int, mins: Dict[str, float], max_drop_pct: float = 15.0,
              require_min: bool = True):
    """Safe automatic undercut. Returns (changes, skips).
    changes: [{sku,name,old,new,comp}]; skips: {reason: [sku,...]}"""
    changes, skips = [], {}
    def skip(why, sku):
        skips.setdefault(why, []).append(sku)
    for o in products:
        if not o.lose:
            continue
        if o.inactive or o.oos:
            skip("غیرفعال/ناموجود", o.sku)
            continue
        if o.comp is None or o.price is None or not o.sku:
            skip("قیمت نفر اول نامشخص", o.sku)
            continue
        np_ = int(o.comp - delta)
        if np_ <= 0:
            skip("قیمت نامعتبر", o.sku)
            continue
        if np_ >= o.price:
            skip("قیمت شما از قبل پایین‌تر است", o.sku)
            continue
        floor = mins.get(o.sku)
        if floor is None and require_min:
            skip("بدون حداقل قیمت", o.sku)
            continue
        if floor is not None and np_ < floor:
            skip("زیر حداقل قیمت", o.sku)
            continue
        if max_drop_pct and (o.price - np_) / o.price * 100 > max_drop_pct:
            skip("افت قیمت بیش از حد مجاز", o.sku)
            continue
        changes.append({"sku": o.sku, "name": o.name, "old": int(o.price), "new": np_, "comp": int(o.comp)})
    return changes, skips


def read_mins_csv(path: str) -> Dict[str, float]:
    import csv
    out: Dict[str, float] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return out
    head = [norm(h) for h in rows[0]]
    si = next((i for i, h in enumerate(head) if h in ("sku", "code", "id")), 0)
    mi = next((i for i, h in enumerate(head) if "min" in h), None)
    if mi is None:
        mi = 1 if len(head) > 1 else 0
    for r in rows[1:]:
        if len(r) <= max(si, mi):
            continue
        v = to_num(r[mi])
        if r[si].strip() and v is not None and v > 0:
            out[r[si].strip()] = v
    return out


def write_mins_csv(path: str, products: List[Prod], mins: Dict[str, float]):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sku", "name", "price", "competitor_price", "min_price"])
        for o in products:
            w.writerow([o.sku, o.name, "" if o.price is None else int(o.price),
                        "" if o.comp is None else int(o.comp), "" if o.sku not in mins else int(mins[o.sku])])
