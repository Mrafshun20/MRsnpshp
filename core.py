# -*- coding: utf-8 -*-
"""SnappShop vendor automation API client (stdlib only; shared by the Android app and the Windows bot)."""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SNAPP_BASE_URL", "https://apix.snappshop.ir/automation/v1")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


_CTX = _ctx()


class ApiError(Exception):
    pass


class AuthError(ApiError):
    pass


class Client:
    def __init__(self, ua: str, token: str, base: str = None, timeout: int = 30):
        self.ua = ua.strip()
        self.token = token.strip()
        self.base = (base or BASE).rstrip("/")
        self.timeout = timeout

    # ---- low level
    def _url(self, endpoint, params=None):
        url = endpoint if endpoint.startswith("http") else f"{self.base}/{endpoint.lstrip('/')}"
        if params:
            q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
            if q:
                url += ("&" if "?" in url else "?") + q
        return url

    def request(self, method, endpoint, params=None, body=None):
        url = self._url(endpoint, params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"User-Agent": self.ua, "Authorization": "Bearer " + self.token,
                   "Accept": "application/json", "Content-Type": "application/json"}
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=_CTX) as r:
                    txt = r.read().decode("utf-8", "replace")
                try:
                    return json.loads(txt) if txt.strip() else {}
                except ValueError:
                    raise ApiError("invalid JSON response: " + txt[:200])
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "replace")[:400]
                if e.code in (401, 403):
                    raise AuthError(f"HTTP {e.code}: {txt}")
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise ApiError(f"HTTP {e.code} {method} {endpoint}: {txt}")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise ApiError(f"network error: {e}")

    @staticmethod
    def _next(resp, endpoint, params):
        pg = (resp.get("meta") or {}).get("pagination") or {}
        if not pg.get("has_more"):
            return None
        nxt = (pg.get("links") or {}).get("next")
        if nxt and str(nxt).startswith("http"):
            return str(nxt), None
        cur = pg.get("next_cursor")
        if cur:
            p = dict(params or {})
            p["cursor"] = cur
            return endpoint, p
        return None

    # ---- endpoints
    def vendors(self):
        return self.request("GET", "vendors").get("data") or []

    def products(self, vid, progress=None, max_pages=2000):
        out, page = [], 1
        while page <= max_pages:
            r = self.request("GET", f"vendors/{vid}/products", {"page": page})
            d = r.get("data") or []
            if not d:
                break
            out.extend(d)
            tp = ((r.get("meta") or {}).get("pagination") or {}).get("total_pages") or 1
            if progress:
                progress(page, tp)
            if page >= tp:
                break
            page += 1
        return out

    def patch_products(self, vid, items):
        """items need id|sku + stock + price. Returns per-item results [{sku,id,status,messages}]."""
        res = []
        for i in range(0, len(items), 50):
            r = self.request("PATCH", f"vendors/{vid}/products", body={"products": items[i:i + 50]})
            res.extend(r.get("data") or [])
        return res

    def orders(self, vid, start=None, end=None, max_pages=1000, progress=None):
        endpoint, params = f"vendors/{vid}/orders", {"start_date": start, "end_date": end}
        out, seen = [], set()
        for n in range(max_pages):
            r = self.request("GET", endpoint, params)
            out.extend(r.get("data") or [])
            if progress:
                progress(n + 1, len(out))
            nx = self._next(r, endpoint, params)
            if not nx:
                break
            key = json.dumps(nx, sort_keys=True)
            if key in seen:
                break
            seen.add(key)
            endpoint, params = nx
        return out

    def order(self, vid, number):
        r = self.request("GET", f"vendors/{vid}/orders/{number}")
        return r.get("data", r) if isinstance(r, dict) else r

    def events(self, vid, cursor=None, max_pages=1000):
        """Order events stream. Returns (events, last_cursor). Send last_cursor next time."""
        endpoint, params = f"vendors/{vid}/orders/events", {"cursor": cursor}
        out, last, seen = [], cursor, set()
        for _ in range(max_pages):
            r = self.request("GET", endpoint, params)
            out.extend(r.get("data") or [])
            pg = (r.get("meta") or {}).get("pagination") or {}
            if pg.get("next_cursor"):
                last = pg["next_cursor"]
            nx = self._next(r, endpoint, params)
            if not nx:
                break
            key = json.dumps(nx, sort_keys=True)
            if key in seen:
                break
            seen.add(key)
            endpoint, params = nx
        return out, last
