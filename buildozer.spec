[app]
title = SnappShop
package.name = snappshop
package.domain = org.vendor
source.dir = .
source.include_exts = py,ttf,png
version = 2.3.0
icon.filename = %(source.dir)s/icon.png
requirements = python3,kivy==2.3.0,pyjnius,android,androidstorage4kivy,requests,urllib3,idna,charset-normalizer,certifi,arabic-reshaper,python-bidi==0.4.2,future
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1