# -*- coding: utf-8 -*-
"""SnappShop unattended bot (Windows/Linux, stdlib only).

What it does while it runs:
  1. Watches new orders/cancellations (order events, cursor kept between runs) -> log + sound + orders_log.csv
  2. Applies price/stock/discount changes from prices.csv whenever you save that file
  3. Writes a daily Excel sales report (reports\\sales-YYYY-MM-DD.xlsx) with Jalali dates and low-stock sheet
Run with --help for options.
"""
import argparse
import csv
import datetime
import hashlib
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import core
import logic as L

FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.environ.get("SNAPP_BOT_DIR") or (os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__)))
def P(name): return os.path.join(APP_DIR, name)
CFG, STATE, PRICES = P("config.json"), P("state.json"), P("prices.csv")
EXPORT, ORDERS_LOG, REPORTS = P("prices_export.csv"), P("orders_log.csv"), P("reports")
REPRICE_LOG = P("reprice_log.csv")

DEFAULT = {
    "user_agent": "", "token": "", "vendor_id": "",
    "events_interval_sec": 60,        # how often to look for new orders
    "report_time": "23:30",           # daily Excel report time (24h, local); "" disables
    "report_days": 1,                 # report covers this many days ending today
    "low_stock_threshold": 3,
    "beep": True,
    "prices_dry_run": True,           # true = only show what prices.csv WOULD change; set false to apply
    "max_price_change_pct": 50,       # safety: rows changing a price by more than this % are skipped
    "reprice_mode": "off",            # buy-box repricer: off | dry (log only) | live
    "reprice_interval_min": 10,
    "reprice_delta": 5000,            # toman below the buy-box price
    "reprice_max_discount_pct": 45,   # never go lower than list price minus this %
    "reprice_max_drop_pct": 15,       # skip a single move larger than this % (bad data guard)
    "reprice_days": 30,               # length of a newly created discount
    "reprice_max_per_day": 4,         # max automatic changes per product per day
}
log = logging.getLogger("bot")


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(), RotatingFileHandler(P("bot.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def keep_awake():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass


def startup(on: bool):
    if os.name != "nt":
        print("Windows only.")
        return
    import winreg
    cmd = (f'cmd /c start "" /min "{sys.executable}" --minimized' if FROZEN
           else f'cmd /c start "" /min "{sys.executable}" "{os.path.abspath(__file__)}"')
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
    if on:
        winreg.SetValueEx(k, "SnappShopBot", 0, winreg.REG_SZ, cmd)
        print("Will start automatically when you sign in to Windows.")
    else:
        try:
            winreg.DeleteValue(k, "SnappShopBot")
        except FileNotFoundError:
            pass
        print("Automatic start removed.")
    winreg.CloseKey(k)


def wizard(cfg):
    import getpass
    print("First-time setup (saved to config.json next to this program).")
    cfg["user_agent"] = input("Unique code (User-Agent): ").strip()
    cfg["token"] = getpass.getpass("Token (hidden while typing): ").strip()
    vs = core.Client(cfg["user_agent"], cfg["token"]).vendors()
    if not vs:
        raise SystemExit("No store found for this token.")
    if len(vs) == 1:
        v = vs[0]
    else:
        for i, x in enumerate(vs):
            print(f"  {i + 1}. {x.get('title')} ({x.get('id')})")
        v = vs[int(input("Which store number? ")) - 1]
    cfg["vendor_id"] = v["id"]
    print("Store:", v.get("title"), v["id"])
    jsave(CFG, cfg)
    return cfg


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = jload(STATE, {})
        self.client = core.Client(cfg["user_agent"], cfg["token"])
        self.vid = cfg["vendor_id"]
        self.cfg_mtime = os.path.getmtime(CFG) if os.path.exists(CFG) else 0
        self.stop_ev = threading.Event()
        self.publish = None          # optional hook: path -> where the user can find the file (Android Downloads)

    def stop(self):
        self.stop_ev.set()

    def save_state(self):
        jsave(STATE, self.state)

    def reload_cfg(self):
        try:
            m = os.path.getmtime(CFG)
            if m != self.cfg_mtime:
                self.cfg_mtime = m
                self.cfg.update(jload(CFG, {}))
                log.info("config.json reloaded")
        except OSError:
            pass

    def journal(self, label, pairs, items, res):
        """Record the previous values of successfully changed products so the app can Undo them."""
        try:
            out = L.patch_outcome(items, res)
            good = [pr for pr, (g, _m) in zip(pairs, out) if g]
            L.UndoStore(P("undo.json")).push(L.make_undo_entry(label, good))
        except Exception:
            log.exception("undo journal failed")

    def products(self):
        return [L.norm_prod(p, i) for i, p in enumerate(self.client.products(self.vid))]

    # ---- 1) order events
    def beep(self, kind):
        if not self.cfg.get("beep") or os.name != "nt":
            return
        try:
            import winsound
            for f in ((1200, 1200) if kind == "NEW_ORDER" else (500,)):
                winsound.Beep(f, 250)
        except Exception:
            pass

    def poll_events(self):
        first = not self.state.get("events_init")
        evs, last = self.client.events(self.vid, self.state.get("events_cursor"))
        if last:
            self.state["events_cursor"] = last
        self.state["events_init"] = True
        self.save_state()
        if first:
            log.info("پایش سفارشات فعال شد؛ از این لحظه سفارش جدید و لغو اعلام می‌شود (%d رویداد قبلی نادیده گرفته شد).", len(evs))
            return
        for e in evs:
            t = e.get("event_type")
            log.info("EVENT %s", L.event_line(e))
            if t in ("NEW_ORDER", "CANCELLATION"):
                new = not os.path.exists(ORDERS_LOG)
                with open(ORDERS_LOG, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["زمان ثبت", "نوع رویداد", "شماره سفارش", "تاریخ رویداد (شمسی)", "تعداد اقلام", "مبلغ کل (تومان)"])
                    items = e.get("items") or []
                    tot = sum(L.to_num(i.get("final_price")) or 0 for i in items if isinstance(i, dict))
                    ea = str(e.get("event_at") or "")
                    w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), L.EVENT_FA.get(t, t), e.get("order_number"),
                                (L.jdate(ea) + " " + ea[11:16]).strip(), len(items), int(tot)])
                self.beep(t)

    # ---- 2) prices.csv sync
    @staticmethod
    def read_csv(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]

    def sync_prices(self):
        if not os.path.exists(PRICES):
            return
        with open(PRICES, "rb") as f:
            h = hashlib.sha1(f.read()).hexdigest()
        dry = bool(self.cfg.get("prices_dry_run", True))
        hkey = "dry_hash" if dry else "prices_hash"
        if self.state.get(hkey) == h:
            return
        rows = self.read_csv(PRICES)
        prods = self.products()
        by_sku = {p.sku: p for p in prods if p.sku}
        by_id = {p.id: p for p in prods}
        limit = float(self.cfg.get("max_price_change_pct", 50))
        items, lines, skipped, pairs = [], [], 0, []
        for r in rows:
            p = by_sku.get(r.get("sku", "")) if r.get("sku") else None
            if p is None and r.get("id"):
                p = by_id.get(r["id"])
            if p is None:
                if r.get("sku") or r.get("id"):
                    log.warning("prices.csv: کالا پیدا نشد: %s", r.get("sku") or r.get("id"))
                continue
            price, stock = L.to_num(r.get("price")), L.to_num(r.get("stock"))
            np_ = int(price) if price is not None else p.price
            ns = int(stock) if stock is not None else p.stock
            if np_ is None or ns is None or np_ <= 0 or ns < 0:
                log.warning("prices.csv: مقدار نامعتبر برای %s", p.key)
                skipped += 1
                continue
            if p.price and abs(np_ - p.price) / p.price * 100 > limit:
                log.warning("رد شد %s: تغییر قیمت %d ← %d بیش از %s٪ است (احتمال اشتباه تایپی)", p.key, p.price, np_, limit)
                skipped += 1
                continue
            extra = {}
            sp = L.to_num(r.get("special_price"))
            if sp is not None and sp > 0:
                st, en = r.get("special_start", "")[:10] or p.sp_start[:10], r.get("special_end", "")[:10] or p.sp_end[:10]
                if (int(sp), st, en) != (int(p.sp or 0), p.sp_start[:10], p.sp_end[:10]):
                    extra["special_price"] = int(sp)
                    if st:
                        extra["special_price_start_at"] = st
                    if en:
                        extra["special_price_end_at"] = en
                    ss = L.to_num(r.get("special_stock"))
                    if ss is not None:
                        extra["special_price_stock"] = int(ss)
            if np_ != p.price or ns != p.stock or extra:
                it = p.item(np_, ns, **extra)
                items.append(it)
                pairs.append((L.snap(p), it))
                lines.append(f"{p.key}: price {int(p.price or 0)}->{np_}, stock {int(p.stock or 0)}->{ns}" + (", discount" if extra else ""))
        if dry:
            log.info("prices.csv (حالت آزمایشی - چیزی ارسال نشد): %d تغییر، %d رد شده. برای اعمال واقعی، حالت آزمایشی را در برنامه خاموش کنید.", len(items), skipped)
            for ln in lines[:30]:
                log.info("  تغییر می‌کرد: %s", ln)
        elif items:
            res = self.client.patch_products(self.vid, items)
            ok, bad = L.summarize_patch(res)
            self.journal("فایل prices.csv", pairs, items, res)
            log.info("prices.csv اعمال شد: %d موفق، %d ناموفق، %d رد شده (با «بازگردانی تغییرات» برگردانید)", ok, len(bad), skipped)
            for k, m in bad[:20]:
                log.warning("  ناموفق %s: %s", k, m)
        else:
            log.info("prices.csv: تغییری لازم نبود (%d رد شده)", skipped)
        self.state[hkey] = h
        self.save_state()

    # ---- 2b) buy-box repricer (special_price = buy_box - delta)
    def reprice(self):
        mode = str(self.cfg.get("reprice_mode", "off")).lower()
        if mode not in ("dry", "live"):
            return
        floors = {}
        if os.path.exists(PRICES):
            for r in self.read_csv(PRICES):
                v = L.to_num(r.get("min_price"))
                if v:
                    for k in (r.get("sku"), r.get("id")):
                        if k:
                            floors[k] = v
        today = datetime.date.today().isoformat()
        st = self.state.get("reprice_n") or {}
        if st.get("date") != today:
            st = {"date": today, "n": {}}
        prods = self.products()
        changes, skips = L.plan_reprice(
            prods, today, float(self.cfg.get("reprice_delta", 5000)), floors,
            float(self.cfg.get("reprice_max_discount_pct", 45)), float(self.cfg.get("reprice_max_drop_pct", 15)),
            int(self.cfg.get("reprice_days", 30)), st["n"], int(self.cfg.get("reprice_max_per_day", 4)))
        for o, why in skips[:20]:
            log.info("تعدیل قیمت: %s رد شد (%s)", o.key, why)
        if not changes:
            log.info("تعدیل قیمت: تغییری لازم نبود (%d رد شده)", len(skips))
            return
        rows = []
        if mode == "dry":
            for o, it, old, new in changes[:30]:
                log.info("تعدیل قیمت (آزمایشی) %s: %d ← %d  (بای‌باکس %d)", o.key, old, new, int(o.buy_box))
                rows.append((o, old, new, "dry"))
        else:
            raw_res = self.client.patch_products(self.vid, [c[1] for c in changes])
            self.journal("تعدیل خودکار بای‌باکس", [(L.snap(c[0]), c[1]) for c in changes], [c[1] for c in changes], raw_res)
            ok, bad = L.summarize_patch(raw_res)
            badk = {k for k, _ in bad}
            log.info("تعدیل قیمت اعمال شد: %d موفق، %d ناموفق", ok, len(bad))
            for k, m in bad[:20]:
                log.warning("  FAILED %s: %s", k, m)
            for o, it, old, new in changes:
                if o.key in badk:
                    continue
                st["n"][o.key] = st["n"].get(o.key, 0) + 1
                rows.append((o, old, new, "live"))
                log.info("تعدیل قیمت %s: %d ← %d  (بای‌باکس %d)", o.key, old, new, int(o.buy_box))
            self.state["reprice_n"] = st
            self.save_state()
        new_file = not os.path.exists(REPRICE_LOG)
        with open(REPRICE_LOG, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "mode", "key", "title", "old_price", "new_price", "buy_box"])
            for o, old, new, m in rows:
                w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m, o.key, o.name, old, new, int(o.buy_box)])

    def export_products(self):
        prods = self.products()
        cols, rows = L.products_export_rows(prods)
        with open(EXPORT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if v is None else (int(v) if isinstance(v, float) else v)) for k, v in r.items()})
        log.info("فایل قیمت‌ها (%d کالا) ساخته شد:\n%s\nآن را با نام prices.csv کپی کنید، ویرایش و ذخیره کنید.", len(rows), self.publish(EXPORT) if self.publish else EXPORT)

    # ---- 3) daily report
    def report(self, force=False):
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        if not force:
            ct = str(self.cfg.get("report_time") or "")
            if not ct or self.state.get("last_report") == today:
                return
            hh, mm = ct.split(":")
            if now < now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0):
                return
        days = max(1, int(self.cfg.get("report_days", 1)))
        start = (now - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d")
        orders = self.client.orders(self.vid, start, today)
        try:
            prods = self.products()
        except core.ApiError as e:
            log.warning("report: product list unavailable (%s) - titles/low-stock sheet skipped", e)
            prods = None
        data = L.build_sales_workbook(orders, prods, int(self.cfg.get("low_stock_threshold", 3)))
        os.makedirs(REPORTS, exist_ok=True)
        path = os.path.join(REPORTS, f"sales-{today}.xlsx")
        with open(path, "wb") as f:
            f.write(data)
        self.state["last_report"] = today
        self.save_state()
        log.info("گزارش فروش ذخیره شد (%d سفارش، %s تا %s):\n%s", len(orders), start, today, self.publish(path) if self.publish else path)

    # ---- main loop
    def safe(self, name, fn):
        try:
            fn()
        except core.AuthError as e:
            log.error("Token rejected (%s). Put a valid token in config.json.", e)
            raise
        except core.ApiError as e:
            log.warning("%s: %s", name, e)
        except Exception:
            log.exception("%s failed", name)

    def run(self, once=False):
        keep_awake()
        log.info("ربات برای فروشگاه %s روشن شد (بررسی سفارش هر %s ثانیه | حالت آزمایشی prices.csv: %s).",
                 self.vid, self.cfg.get("events_interval_sec"), self.cfg.get("prices_dry_run"))
        last_ev = last_rp = 0.0
        while not self.stop_ev.is_set():
            now = time.monotonic()
            try:
                if once or now - last_ev >= max(15, int(self.cfg.get("events_interval_sec", 60))):
                    self.safe("events", self.poll_events)
                    last_ev = now
                self.safe("prices", self.sync_prices)
                if str(self.cfg.get("reprice_mode", "off")).lower() in ("dry", "live") and (
                        once or now - last_rp >= max(60, 60 * int(self.cfg.get("reprice_interval_min", 10)))):
                    self.safe("reprice", self.reprice)
                    last_rp = now
                self.safe("report", self.report)
            except core.AuthError:
                return 2
            if once:
                return 0
            if self.stop_ev.wait(10):
                log.info("ربات متوقف شد.")
                return 0
            self.reload_cfg()


def main(argv=None):
    ap = argparse.ArgumentParser(description="SnappShop unattended bot")
    ap.add_argument("--once", action="store_true", help="run one pass and exit")
    ap.add_argument("--export", action="store_true", help="write prices_export.csv with all products")
    ap.add_argument("--report", action="store_true", help="write the Excel sales report now")
    ap.add_argument("--setup", action="store_true", help="re-run first-time setup")
    ap.add_argument("--install-startup", action="store_true", help="start with Windows")
    ap.add_argument("--uninstall-startup", action="store_true")
    ap.add_argument("--minimized", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    setup_logging()
    if a.install_startup or a.uninstall_startup:
        startup(a.install_startup)
        return 0
    cfg = dict(DEFAULT)
    cfg.update(jload(CFG, {}))
    try:
        if a.setup or not (cfg["user_agent"] and cfg["token"] and cfg["vendor_id"]):
            if not sys.stdin or not sys.stdin.isatty():
                log.error("config.json is incomplete. Run the program once from a console to set it up.")
                return 1
            cfg = wizard(cfg)
        elif not os.path.exists(CFG):
            jsave(CFG, cfg)
        if not os.path.exists(CFG):
            jsave(CFG, cfg)
        bot = Bot(cfg)
        if a.export:
            bot.export_products()
            return 0
        if a.report:
            bot.report(force=True)
            return 0
        return bot.run(once=a.once)
    except core.AuthError as e:
        log.error("Token rejected: %s", e)
        return 2
    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
