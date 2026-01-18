[app]
# (str) Title of your application
title = Naza

# (str) Package name
package.name = naza

# (str) Package domain (needed for android/ios packaging)
package.domain = com.naza

# (str) Source code where the main.py lives
source.dir = .

# (str) The main entry point for your app
source.main = main.py

# (str) Application versioning
version = 0.1.0
android.version_code = 1

# (list) Application requirements
# NOTE: llama-cpp-python does not build reliably for Android/Buildozer.
requirements = python3,kivy==2.2.1,httpx,cryptography,aiosqlite,psutil,pennylane

# (list) Application orientation
orientation = portrait
fullscreen = 0

# (list) Files to include
include_patterns =
    *.py,
    *.kv,
    *.json,
    assets/*

# (list) Permissions
android.permissions = INTERNET

# (int) Target Android API, minimum API, and NDK API to use
android.sdk_path = /usr/local/lib/android/sdk
android.api = 35
android.minapi = 23
android.ndk_api = 23
android.build_tools_version = 35.0.0

# (list) Target architectures
android.archs = arm64-v8a

# (str) Android bootstrap to use
p4a.bootstrap = sdl2

# (bool) Allow Android backups
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = .buildozer
