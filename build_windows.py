# Builds SnappShop.exe (Kivy GUI + built-in bot) with PyInstaller. Run on Windows: python build_windows.py
import os
import sys

import PyInstaller.__main__
import kivy_deps.angle
import kivy_deps.glew
import kivy_deps.sdl2

share = os.path.join(sys.prefix, "share")
bins = [f"--add-binary={p};." for p in (kivy_deps.sdl2.dep_bins + kivy_deps.glew.dep_bins + kivy_deps.angle.dep_bins)
        if os.path.isdir(p)]
PyInstaller.__main__.run([
    "--noconfirm", "--onefile", "--windowed", "--name=SnappShop",
    "--add-data=DejaVuSans.ttf;.", "--add-data=DejaVuSans-Bold.ttf;.", f"--add-data={share};share", *bins,
    "--hidden-import=logic", "--hidden-import=core", "--hidden-import=bot",
    "--hidden-import=licensing", "--hidden-import=license_secret",
    "--hidden-import=kivy_deps.sdl2", "--hidden-import=kivy_deps.glew", "--hidden-import=kivy_deps.angle",
    "main.py",
])
