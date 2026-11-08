"""
mobile_app.py — Mobile Kivy interface for lyrify.
Can be compiled into an Android APK with Buildozer or run directly on desktop.
"""

import os
import sys
import threading
import time

try:
    import kivy
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.checkbox import CheckBox
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.label import Label
    from kivy.uix.progressbar import ProgressBar
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.spinner import Spinner
    from kivy.uix.textinput import TextInput
    from kivy.utils import platform
except ImportError:
    kivy = None

import requests
import lyrify

# Request permissions on Android if running as APK
def request_android_permissions():
    if kivy and platform == "android":
        try:
            from android.permissions import Permission, request_permissions
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.INTERNET,
                "android.permission.READ_MEDIA_AUDIO",
                "android.permission.MANAGE_EXTERNAL_STORAGE",
            ])
        except Exception as e:
            print("[warn] Android permission request failed:", e)


class ConfigArgs:
    """Mock args namespace for lyrify.process_file."""
    def __init__(self, album=None, artist=None, title=None, year=None,
                 genre=None, provider="auto", force=False, dry_run=False,
                 save_lrc=True, verbose=True):
        self.album = album
        self.artist = artist
        self.title = title
        self.year = year
        self.genre = genre
        self.provider = provider
        self.force = force
        self.dry_run = dry_run
        self.save_lrc = save_lrc
        self.verbose = verbose
        self.ext = sorted(lyrify.SUPPORTED_EXTS)


if kivy:
    class LyrifyMobileApp(App):
        def build(self):
            self.title = "Lyrify — Audio Lyrics Tagger"
            Window.clearcolor = (0.12, 0.13, 0.15, 1)

            self.is_running = False
            self.stop_requested = False

            root = BoxLayout(orientation="vertical", padding=16, spacing=10)

            # Title
            title_box = BoxLayout(size_hint_y=None, height=40)
            title_lbl = Label(
                text="[b]Lyrify[/b] — Music Lyrics Tagger",
                markup=True,
                font_size="20sp",
                color=(0.9, 0.95, 1, 1),
            )
            title_box.add_widget(title_lbl)
            root.add_widget(title_box)

            # Folder selection
            folder_box = BoxLayout(orientation="vertical", size_hint_y=None, height=70, spacing=4)
            folder_lbl = Label(text="Music Folder Path:", size_hint_y=None, height=20, halign="left", color=(0.7, 0.8, 0.9, 1))
            folder_lbl.bind(size=folder_lbl.setter("text_size"))
            default_path = "/storage/emulated/0/Music" if platform == "android" else os.path.expanduser("~/Music")
            self.folder_input = TextInput(
                text=default_path,
                multiline=False,
                size_hint_y=None,
                height=40,
                background_color=(0.18, 0.20, 0.24, 1),
                foreground_color=(1, 1, 1, 1),
            )
            folder_box.add_widget(folder_lbl)
            folder_box.add_widget(self.folder_input)
            root.add_widget(folder_box)

            # Options grid
            grid = GridLayout(cols=2, size_hint_y=None, height=120, spacing=8)

            # Provider spinner
            prov_lbl = Label(text="Lyrics Provider:", color=(0.8, 0.8, 0.8, 1))
            self.prov_spinner = Spinner(
                text="auto (LRCLIB + Genius)",
                values=("auto", "lrclib", "genius", "lyricsovh", "search"),
                size_hint_y=None,
                height=38,
                background_color=(0.25, 0.35, 0.5, 1),
            )
            grid.add_widget(prov_lbl)
            grid.add_widget(self.prov_spinner)

            # Overwrite toggle
            force_lbl = Label(text="Overwrite Existing Lyrics:", color=(0.8, 0.8, 0.8, 1))
            self.force_chk = CheckBox(active=False, size_hint_y=None, height=38)
            grid.add_widget(force_lbl)
            grid.add_widget(self.force_chk)

            # Save .LRC companion file toggle
            lrc_lbl = Label(text="Save .LRC Files (Synced):", color=(0.8, 0.8, 0.8, 1))
            self.lrc_chk = CheckBox(active=True, size_hint_y=None, height=38)
            grid.add_widget(lrc_lbl)
            grid.add_widget(self.lrc_chk)

            root.add_widget(grid)

            # Progress Bar & Counter
            prog_box = BoxLayout(orientation="vertical", size_hint_y=None, height=45, spacing=4)
            self.progress_bar = ProgressBar(max=100, value=0, size_hint_y=None, height=15)
            self.status_lbl = Label(
                text="Ready. Tap 'Start Tagging' to begin.",
                size_hint_y=None,
                height=25,
                font_size="13sp",
                color=(0.6, 0.8, 0.7, 1),
            )
            prog_box.add_widget(self.progress_bar)
            prog_box.add_widget(self.status_lbl)
            root.add_widget(prog_box)

            # Action Buttons
            btn_box = BoxLayout(size_hint_y=None, height=48, spacing=12)
            self.start_btn = Button(
                text="Start Tagging",
                background_color=(0.15, 0.65, 0.35, 1),
                bold=True,
            )
            self.start_btn.bind(on_press=self.on_start_pressed)
            self.stop_btn = Button(
                text="Stop",
                background_color=(0.75, 0.25, 0.25, 1),
                disabled=True,
                bold=True,
            )
            self.stop_btn.bind(on_press=self.on_stop_pressed)
            btn_box.add_widget(self.start_btn)
            btn_box.add_widget(self.stop_btn)
            root.add_widget(btn_box)

            # Log area
            log_scroll = ScrollView(size_hint=(1, 1))
            self.log_text = Label(
                text="[System] Welcome to Lyrify!\n",
                markup=False,
                size_hint_y=None,
                font_size="12sp",
                color=(0.85, 0.85, 0.85, 1),
                halign="left",
                valign="top",
            )
            self.log_text.bind(width=lambda *args: setattr(self.log_text, "text_size", (self.log_text.width, None)))
            self.log_text.bind(texture_size=lambda *args: setattr(self.log_text, "height", self.log_text.texture_size[1]))
            log_scroll.add_widget(self.log_text)
            root.add_widget(log_scroll)

            return root

        def on_start(self):
            request_android_permissions()

        def append_log(self, text):
            def _update(dt):
                self.log_text.text += text + "\n"
            Clock.schedule_once(_update)

        def update_progress(self, current, total, text=""):
            def _update(dt):
                pct = int((current / total) * 100) if total else 0
                self.progress_bar.value = pct
                self.status_lbl.text = text or f"{current}/{total} ({pct}%)"
            Clock.schedule_once(_update)

        def on_start_pressed(self, instance):
            if self.is_running:
                return
            target_folder = self.folder_input.text.strip()
            if not os.path.isdir(target_folder):
                self.append_log(f"[Error] Directory not found: {target_folder}")
                return

            self.is_running = True
            self.stop_requested = False
            self.start_btn.disabled = True
            self.stop_btn.disabled = False
            self.progress_bar.value = 0

            prov = self.prov_spinner.text.split()[0]
            args = ConfigArgs(
                provider=prov,
                force=self.force_chk.active,
                save_lrc=self.lrc_chk.active,
            )

            thread = threading.Thread(target=self.run_tagging, args=(target_folder, args), daemon=True)
            thread.start()

        def on_stop_pressed(self, instance):
            if self.is_running:
                self.stop_requested = True
                self.append_log("[Info] Stopping after current track...")
                self.stop_btn.disabled = True

        def run_tagging(self, folder, args):
            self.append_log(f"[Scan] Scanning {folder}...")
            files = []
            for dirpath, _, names in os.walk(folder):
                for name in names:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in lyrify.SUPPORTED_EXTS:
                        files.append(os.path.join(dirpath, name))

            total = len(files)
            if not total:
                self.append_log("[Scan] No audio files found.")
                Clock.schedule_once(lambda dt: self.finish_run(0, {}))
                return

            files.sort()
            self.append_log(f"[Scan] Found {total} audio files. Starting tagging...")
            stats = {"written": 0, "skipped_existing": 0, "skipped_filter": 0,
                     "no_lyrics": 0, "errors": 0}
            session = requests.Session()
            session.headers.update(lyrify.HEADERS)

            for i, path in enumerate(files, 1):
                if self.stop_requested:
                    self.append_log("[Info] Stopped by user.")
                    break
                fname = os.path.basename(path)
                self.update_progress(i, total, f"Processing {i}/{total}: {fname[:30]}...")

                # Intercept output
                old_stdout = sys.stdout
                from io import StringIO
                buf = StringIO()
                sys.stdout = buf
                try:
                    lyrify.process_file(path, args, session, stats, lock=None, index=i, total=total)
                finally:
                    sys.stdout = old_stdout

                line = buf.getvalue().strip()
                if line:
                    self.append_log(line)
                time.sleep(0.3)

            Clock.schedule_once(lambda dt: self.finish_run(total, stats))

        def finish_run(self, total, stats):
            self.is_running = False
            self.start_btn.disabled = False
            self.stop_btn.disabled = True
            written = stats.get("written", 0)
            miss = stats.get("no_lyrics", 0)
            skipped = stats.get("skipped_existing", 0)
            self.status_lbl.text = f"Complete: {written} written, {miss} missed, {skipped} skipped."
            self.append_log(f"\n[Complete] Finished! Tagged: {written} | Missed: {miss} | Skipped: {skipped}")


def main():
    if kivy is None:
        print("Kivy is not installed. To run the mobile GUI on desktop:")
        print("  pip install kivy")
        print("\nTo build an Android APK, use Buildozer (see buildozer.spec and ANDROID_GUIDE.md).")
        return
    LyrifyMobileApp().run()


if __name__ == "__main__":
    main()
