"""Offline license keys for the seller app.

Keys are HMAC-SHA256 signed (truncated) so the app can validate them without a
server. The signing secret is baked in at build time from the GitHub Actions
secret LICENSE_SECRET (see .github/workflows); it is NEVER in the repo.
Local dev runs fall back to a public dev secret whose keys never validate in
production builds.

Key format: SSV-XXXX-XXXX-... (7 groups of 4), e.g.
  SSV-V1M2-0270-117A-1B2C-3D4E-5F6A-7B8C
Payload (before signing): v1-<plan>-<YYYY-MM-DD expiry>-<random>
"""
import datetime
import hashlib
import hmac
import json
import os

try:
    from license_secret import SECRET
except ImportError:
    SECRET = "dev-secret-change-me"  # local dev only

PREFIX = "SSV"
# plan code -> (Persian label, days)
PLANS = {
    "t": ("آزمایشی", 7),
    "m": ("ماهانه", 30),
    "q": ("فصلی", 90),
    "y": ("سالیانه", 365),
}


def make_key(secret: str, plan: str = "m", today=None) -> str:
    """Mint a new license key. Raises ValueError on unknown plan."""
    if plan not in PLANS:
        raise ValueError("unknown plan: %r" % plan)
    import secrets as _secrets
    today = today or datetime.date.today()
    exp = (today + datetime.timedelta(days=PLANS[plan][1])).isoformat()
    rnd = _secrets.token_hex(3)[:5]
    body = "v1-%s-%s-%s" % (plan, exp, rnd)
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:12]
    raw = (body + "-" + sig).replace("-", "").upper()
    return PREFIX + "-" + "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def normalize(key: str) -> str:
    k = (key or "").strip().upper().replace(" ", "").replace("-", "")
    if k.startswith(PREFIX):
        k = k[len(PREFIX):]
    return k


def validate_key(key: str, secret: str, today=None):
    """-> (ok, plan_code, expiry_iso, err_fa). err_fa is '' when ok."""
    today = today or datetime.date.today()
    k = normalize(key)
    if len(k) != 28:
        return False, "", "", "فرمت کلید درست نیست."
    body_raw, sig_given = k[:16], k[16:]
    ver, plan = body_raw[0:2], body_raw[2:3].lower()
    exp8, rnd = body_raw[3:11], body_raw[11:16]
    if ver != "V1" or plan not in PLANS or not exp8.isdigit():
        return False, "", "", "کلید معتبر نیست."
    exp_iso = "%s-%s-%s" % (exp8[0:4], exp8[4:6], exp8[6:8])
    try:
        exp = datetime.date(int(exp8[0:4]), int(exp8[4:6]), int(exp8[6:8]))
    except ValueError:
        return False, "", "", "کلید معتبر نیست."
    body = "v1-%s-%s-%s" % (plan, exp_iso, rnd.lower())
    sig_calc = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:12].upper()
    if not hmac.compare_digest(sig_calc, sig_given):
        return False, "", "", "کلید معتبر نیست."
    if exp < today:
        return False, "", "", "لایسنس منقضی شده است."
    return True, plan, exp_iso, ""


def days_left(expiry_iso: str, today=None) -> int:
    today = today or datetime.date.today()
    try:
        exp = datetime.date(*map(int, expiry_iso.split("-")))
    except Exception:
        return -1
    return (exp - today).days


def plan_label(plan: str) -> str:
    return PLANS.get(plan, ("", 0))[0]


def license_dirs():
    """Candidate dirs holding license.json (script dir + desktop out dir)."""
    here = os.path.dirname(os.path.abspath(__file__))
    desk = os.path.join(os.path.expanduser("~"), "Documents", "SnappShop")
    return [here, desk]


def load_license(search_dirs=None):
    """Return the saved {'key': ...} dict or None."""
    for d in search_dirs or license_dirs():
        p = os.path.join(d, "license.json")
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("key"):
                return data
        except Exception:
            continue
    return None


def save_license(directory: str, key: str):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "license.json"), "w", encoding="utf-8") as f:
        json.dump({"key": normalize(key)}, f, ensure_ascii=False)
