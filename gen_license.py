#!/usr/bin/env python3
"""Mint a license key for the seller app.

The signing secret is NEVER in the repo. Provide it via:
  export MRSM_LIC_SECRET="$(cat ~/.mrsm_secret)"
or keep it in ~/.mrsm_secret (chmod 600).

Examples:
  python3 gen_license.py --plan m --note "vendor: Ali"
  python3 gen_license.py --plan t --note "trial"
Plans: t=trial 7d, m=monthly 30d, q=quarterly 90d, y=annual 365d
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import licensing as L


def get_secret() -> str:
    s = os.environ.get("MRSM_LIC_SECRET", "").strip()
    if s:
        return s
    p = os.path.expanduser("~/.mrsm_secret")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    sys.exit("error: set MRSM_LIC_SECRET env var or put the secret in ~/.mrsm_secret")


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint a seller-app license key")
    ap.add_argument("--plan", choices=sorted(L.PLANS), default="m",
                    help="t=trial, m=monthly, q=quarterly, y=annual")
    ap.add_argument("--note", default="", help="free-form note (not embedded in key)")
    a = ap.parse_args()
    secret = get_secret()
    if not secret or secret == "dev-secret-change-me":
        sys.exit("error: refusing to mint keys with the dev secret")
    key = L.make_key(secret, a.plan)
    ok, plan, exp, err = L.validate_key(key, secret)
    assert ok, err
    print("key:     " + key)
    print("plan:    %s (%s)" % (L.plan_label(plan), plan))
    print("expires: " + exp)
    if a.note:
        print("note:    " + a.note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
