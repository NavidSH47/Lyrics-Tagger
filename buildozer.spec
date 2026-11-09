[app]

# (str) Title of your application
title = Lyrify

# (str) Package name
package.name = lyrify

# (str) Package domain (needed for android/ios packaging)
package.domain = org.lyrify

# (str) Source code where the main.py / mobile_app.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,txt,env,json

# (str) Application versioning
version = 2.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy,mutagen,requests,beautifulsoup4,urllib3,certifi,chardet,idna

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO

# (int) Target Android API, should be as high as possible.
android.api = 34

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (bool) If True, then skip trying to update the Android SDK
# This can be useful to avoid excess Internet downloads or save time
# when an update is due and you just want to test/build your package
android.skip_update = False

# (bool) If True, then automatically accept SDK license
# agreements. This is intended for automation only.
android.accept_sdk_license = True

# (str) The Android arch to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
# For modern Android phones, arm64-v8a is the standard.
android.archs = arm64-v8a, armeabi-v7a

# (str) Entry point file
# android.entrypoint = main.py

# (bool) Copy library instead of making a libpymodules.so
android.copy_libs = 1

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug with command output)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
