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
