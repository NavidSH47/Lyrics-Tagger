# Building and Running Lyrify on Android

This guide explains how to turn **Lyrify** into an Android APK or run it directly on your Android phone.

---

## Architecture Overview

```
                      ┌───────────────────────────────────────┐
                      │             Android Device            │
                      ├───────────────────────────────────────┤
                      │  UI: Kivy (mobile_app.py) or Native   │
                      │  Engine: lyrify.py (Mutagen + APIs)   │
                      └──────────────────┬────────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     ┌───────────────────────┐                       ┌───────────────────────┐
     │  Local Music Storage  │                       │   Lyrics Providers    │
     │  (/sdcard/Music)      │                       │  (LRCLIB / Genius)    │
     │  - Read ID3/Vorbis    │                       │  - Fast JSON APIs     │
     │  - Embed tags         │                       │  - Synced LRC lines   │
     │  - Save .lrc files    │                       └───────────────────────┘
     └───────────────────────┘
```

On Android, there are **3 ways** to get this app running:
1. **GitHub Actions (Easiest)**: Automated cloud build generates the `.apk` in 5 minutes without installing Linux or Android SDK on your PC.
2. **Local Buildozer (WSL2 / Linux)**: Compile locally using Ubuntu/WSL.
3. **Termux (Zero Build)**: Run the script directly on your phone in under 2 minutes.

---

## Method 1: Cloud Build with GitHub Actions (Recommended)

You don't need Linux, Android Studio, or Android NDK installed on your Windows PC.

1. **Push this repository to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Add mobile app and buildozer config"
   git branch -M main
   git remote add origin https://github.com/<your-username>/lyrics-tagger.git
   git push -u origin main
   ```
2. In your GitHub repository, open the **Actions** tab.
3. You will see the **Build Android APK** workflow running.
4. Once completed (approx. 8–10 minutes on first run), click on the workflow run.
5. Under **Artifacts**, download `lyrify-android-debug-apk.zip`.
6. Extract the `.apk` and install it on your Android phone!

---

## Method 2: Local Build with Buildozer (WSL2 / Linux)

Buildozer requires a Linux environment (Ubuntu 22.04+ or WSL2 on Windows).

### 1. Set up WSL on Windows (PowerShell as Administrator)
```powershell
wsl --install -d Ubuntu
```

### 2. Install prerequisites in Ubuntu
```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-setuptools autoconf \
    libtool pkg-config zlib1g-dev libncurses-dev cmake libffi-dev libssl-dev

pip install --upgrade pip
pip install buildozer cython virtualenv
```

### 3. Build the APK
Navigate to your project directory inside WSL:
```bash
cd /mnt/c/Users/XMART/lyrics-tagger
cp mobile_app.py main.py
buildozer -v android debug
```

Your compiled APK will be output to the `bin/` folder:
```
bin/lyrify-2.0.0-arm64-v8a_armeabi-v7a-debug.apk
```

Install it to a connected phone with ADB:
```bash
adb install -r bin/lyrify-2.0.0-debug.apk
```

---

## Method 3: Instant Run on Phone with Termux (No Build Needed)

If you just want to tag music directly on your phone right now without building an APK:

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/).
2. Open Termux and run:
   ```bash
   # Update and install Python & Git
   pkg update -y && pkg install -y python git

   # Grant storage permission
   termux-setup-storage

   # Clone or copy your project files
   git clone https://github.com/<your-username>/lyrics-tagger.git
   cd lyrics-tagger

   # Install dependencies
   pip install -r requirements.txt

   # Run lyrify on your music directory
   python lyrify.py /sdcard/Music --save-lrc
   ```

---

## Method 4: Native Android Studio App (Chaquopy)

If you prefer building a native Kotlin UI (Jetpack Compose) in Android Studio while keeping the Python engine:

1. Add the **Chaquopy** plugin in your Android Studio `build.gradle.kts`:
   ```kotlin
   plugins {
       id("com.android.application")
       id("org.jetbrains.kotlin.android")
       id("com.chaquo.python") version "15.0.1"
   }
   ```
2. Configure Python in `app/build.gradle.kts`:
   ```kotlin
   chaquopy {
       defaultConfig {
           version = "3.11"
           pip {
               install("mutagen>=1.47")
               install("requests>=2.31")
               install("beautifulsoup4>=4.12")
           }
       }
   }
   ```
3. Copy `lyrify.py` into `app/src/main/python/`.
4. Call Python from your Kotlin Activity:
   ```kotlin
   import com.chaquo.python.Python
   import com.chaquo.python.android.AndroidPlatform

   if (!Python.isStarted()) {
       Python.start(AndroidPlatform(context))
   }
   val py = Python.getInstance()
   val lyrifyModule = py.getModule("lyrify")

   // Call lyrify functions directly in Kotlin!
   ```

---

## ⚠️ Important Android 11+ Permission Step

Modern Android versions (Android 11, 12, 13, 14, 15) use **Scoped Storage**. For any music tagger to modify tags directly inside `/sdcard/Music`, it needs "All Files Access":

1. Install the APK on your phone.
2. Go to **Settings → Apps → Special app access → All files access**.
3. Locate **Lyrify** and toggle **Allow access to manage all files**.
4. Open Lyrify, choose `/storage/emulated/0/Music`, and tap **Start Tagging**!
