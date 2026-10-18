SnappShop vendor app (Android APK + Windows EXE) - same code, same tools on both.

Branch ui-modern: same logic as main, rebuilt light seller-panel UI.
Branch main is unchanged.

Repo root must contain:
  main.py logic.py core.py bot.py build_windows.py buildozer.spec icon.png DejaVuSans.ttf DejaVuSans-Bold.ttf
  tests/test_logic.py
  .github/workflows/build.yml          -> Android APK  (Actions artifact "SnappShop-APK" + Releases "latest")
  .github/workflows/windows-build.yml  -> Windows EXE  (Actions artifact "SnappShop-Windows-App" + Releases "latest")
Must NOT exist (delete if present): main_v3_unused.py  logic_v3_unused.py  .github/workflows/bot-windows.yml

Tests (no Kivy needed):  python -m unittest discover -s tests -v

Licensing (selling the app):
  - Keys are HMAC-signed offline (licensing.py). The signing secret is NEVER in the repo:
    it is baked in at build time from the GitHub Actions secret LICENSE_SECRET
    (repo Settings > Secrets and variables > Actions > New repository secret).
    Generate a value with:  python3 -c "import secrets; print(secrets.token_hex(32))"
    Builds FAIL without it (fail-safe: never ship builds that accept dev keys).
  - Mint keys locally:  export MRSM_LIC_SECRET="<secret>"
                        python3 gen_license.py --plan m --note "vendor name"
    Plans: t=trial 7d, m=monthly 30d, q=quarterly 90d, y=annual 365d.
  - The app asks for a key on first run (license screen); the bot refuses to run
    without a valid license. Edit SALES_INFO in main.py with your contact/payment info.
