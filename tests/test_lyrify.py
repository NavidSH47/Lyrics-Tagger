"""Canonical test suite for lyrify (Genius-token logic + .bat launcher).

Network is mocked so tests are deterministic. Run: python -m pytest -q
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LYRIFY = os.path.join(PROJECT, "lyrify.py")
BAT = os.path.join(PROJECT, "add-lyrics.bat")
CMD = r"C:\Windows\System32\cmd.exe"

NEED_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                 reason="ffmpeg not installed")

GENIUS_ENV = ("GENIUS_ACCESS_TOKEN", "GENIUS_TOKEN",
              "GENIUS_CLIENT_ID", "GENIUS_CLIENT_SECRET")


def load_fresh():
    """Import lyrify.py from scratch (fresh _TOKEN_CACHE + clean Genius env)."""
    spec = importlib.util.spec_from_file_location("lyrify_%s" % time.time_ns(), LYRIFY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for k in GENIUS_ENV:
        os.environ.pop(k, None)
    return m


class Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class FakeSession:
    """post() canned; any get() is a failure (tests must not hit the network)."""
    def __init__(self, post_result):
        self.post_result = post_result
        self.posted = None

    def post(self, url, **kwargs):
        self.posted = (url, kwargs)
        return self.post_result

    def get(self, url, **kwargs):
        raise AssertionError("network get() should never run in these tests")


# --- genius_access_token ---------------------------------------------------

def test_no_creds_skips():
    m = load_fresh()
    with pytest.raises(m.LyricsNotFound):
        m.genius_access_token(FakeSession(None))


def test_classic_token_short_circuits():
    m = load_fresh()
    os.environ["GENIUS_ACCESS_TOKEN"] = "tok"
    assert m.genius_access_token(FakeSession(None)) == "tok"


def test_oauth_happy_path():
    m = load_fresh()
    os.environ.update(GENIUS_CLIENT_ID="cid", GENIUS_CLIENT_SECRET="csec")
    s = FakeSession(Resp(200, {"access_token": "tok-oauth"}))
    assert m.genius_access_token(s) == "tok-oauth"
    url, kwargs = s.posted
    assert url == "https://api.genius.com/oauth/token"
    assert kwargs["json"] == {"grant_type": "client_credentials",
                              "client_id": "cid", "client_secret": "csec"}


def test_oauth_401_raises():
    m = load_fresh()
    os.environ.update(GENIUS_CLIENT_ID="cid", GENIUS_CLIENT_SECRET="csec")
    with pytest.raises(m.LyricsNotFound):
        m.genius_access_token(FakeSession(Resp(401, {})))


def test_token_cached_no_reexchange():
    m = load_fresh()
    os.environ.update(GENIUS_CLIENT_ID="cid", GENIUS_CLIENT_SECRET="csec")
    s = FakeSession(Resp(200, {"access_token": "t"}))
    m.genius_access_token(s)
    first = s.posted
    m.genius_access_token(s)
    assert s.posted is first


# --- genious extract / clean_lyrics ---

GENIUS_HTML = """
<html><body>
<div data-lyrics-container="true">46 Contributors
Translations
Italiano
Español
Français</div>
<div data-lyrics-container="true">[Verse 1]
Wake up to the morning light
The coffee's brewing and the day is bright
Windows open and the world is wide
Nothing to lose and nowhere to hide</div>
<div data-lyrics-container="true">[Chorus]
And I sing along, la la la
Sing it with me, la la la</div>
</body></html>
"""


def test_extract_genius_skips_junk_blocks():
    m = load_fresh()
    out = m.extract_lyrics_from_html(GENIUS_HTML)
    assert "Contributors" not in out and "Translations" not in out
    assert "Wake up to the morning light" in out
    assert out.splitlines()[0] == "[Verse 1]"


def test_clean_lyrics_strips_heading_and_blank_lines():
    m = load_fresh()
    assert m.clean_lyrics("Lyrics\n\nWake up to the light") == "Wake up to the light"
    assert m.clean_lyrics("Song Lyrics\n\nla la la\n\n\nsing it") == "la la la\n\nsing it"
    assert m.clean_lyrics("Morning Light Lyrics\nWake up to the light") == "Wake up to the light"
    assert m.clean_lyrics("Lyrics to 'Morning Light'\nWake up to the light") == "Wake up to the light"
    assert m.clean_lyrics("Lyrics:\nWake up to the light") == "Wake up to the light"


def test_clean_lyrics_keeps_real_first_lines():
    m = load_fresh()
    raw = "Wake up to the morning light\nAnd I feel so alive"
    assert m.clean_lyrics(raw) == raw
    # a lowercase, not-heading opening must not be stripped
    assert m.clean_lyrics("these lyrics\nare real") == "these lyrics\nare real"


# --- artist resolution (album artist vs track artist) ------------------------

def test_resolve_artist_prefers_album_artist():
    m = load_fresh()
    assert m.resolve_artist({"artist": "Track Guy", "albumartist": "Album Band"}) == "Album Band"
    assert m.resolve_artist({"TPE1": "Track", "TPE2": "Album"}) == "Album"
    assert m.resolve_artist({"artist": ["Track"], "albumartist": ["Album"]}) == "Album"
    assert m.resolve_artist({"artist": "Track Guy", "album artist": "Album Band"}) == "Album Band"


def test_resolve_artist_falls_back_and_ignores_generic():
    m = load_fresh()
    assert m.resolve_artist({"artist": "Track Guy"}) == "Track Guy"
    assert m.resolve_artist({"TPE1": "Track"}) == "Track"
    # generic album-artist values must not be used
    for bad in ("Various Artists", "VA", "Compilation", "Soundtrack", "OST"):
        assert m.resolve_artist({"artist": "Track Guy", "albumartist": bad}) == "Track Guy", bad


@NEED_FFMPEG
def test_resolve_artist_from_real_file_uses_tpe2(tmp_path):
    p = _make_song(tmp_path, "a.mp3", "Hey Jude", "Track Guy", "x")
    from mutagen.id3 import ID3, TPE2
    t = ID3(p)
    t.add(TPE2(encoding=3, text="The Beatles"))
    t.save(p)
    m = load_fresh()
    assert m.resolve_artist(m.MutagenFile(p).tags) == "The Beatles"


# --- --show ----------------------------------------------------------------

def _make_song(tmpdir, name, title, artist, lyrics):
    """Build a tiny real MP3 with tags + an embedded USLT lyric frame."""
    path = os.path.join(str(tmpdir), name)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-codec:a", "libmp3lame", "-qscale:a", "9", path, "-loglevel", "error"],
        check=True, capture_output=True)
    from mutagen.id3 import ID3, TIT2, TPE1, USLT
    t = ID3(path)
    t.add(TIT2(encoding=3, text=title))
    t.add(TPE1(encoding=3, text=artist))
    t.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
    t.save(path)
    return path


@NEED_FFMPEG
def test_show_file_path_prints_lyrics(tmp_path):
    p = _make_song(tmp_path, "demo.mp3", "Morning Breeze", "Demo Band",
                   "Wake up to the light\nSo fine")
    r = subprocess.run([sys.executable, LYRIFY, "--show", p],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0
    assert "Wake up to the light" in r.stdout


@NEED_FFMPEG
def test_show_search_in_dir_by_title(tmp_path):
    _make_song(tmp_path, "demo.mp3", "Morning Breeze", "Demo Band",
               "la la la\nsing it loud")
    r = subprocess.run([sys.executable, LYRIFY, str(tmp_path), "--show", "morning"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0
    assert "la la la" in r.stdout


@NEED_FFMPEG
def test_show_no_match_returns_error(tmp_path):
    _make_song(tmp_path, "demo.mp3", "Morning Breeze", "Demo Band", "some lyrics")
    r = subprocess.run([sys.executable, LYRIFY, str(tmp_path), "--show", "zzznothing"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 1
    assert "No song matching" in r.stderr


# --- launcher ---------------------------------------------------------------

def run_bat_auto(folder, cfg, timeout=60):
    """Run the .bat in /auto mode with environment variables.

    This bypasses the interactive menu (which requires a real console
    for `choice.exe` / `set /p`) and is suitable for CI / pytest.
    """
    env = os.environ.copy()
    env["AUTO_MODE"] = "1"
    if "album" in cfg:
        env["F_ALBUM"] = cfg["album"]
    if "artist" in cfg:
        env["F_ARTIST"] = cfg["artist"]
    if "title" in cfg:
        env["F_TITLE"] = cfg["title"]
    if "year" in cfg:
        env["F_YEAR"] = cfg["year"]
    if "genre" in cfg:
        env["F_GENRE"] = cfg["genre"]
    if "provider" in cfg:
        env["F_PROVIDER"] = cfg["provider"]
    if "ext" in cfg:
        env["F_EXT"] = cfg["ext"]
    if cfg.get("force"):
        env["FORCE"] = "--force"

    return subprocess.run([CMD, "/c", BAT, "/auto", folder],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=PROJECT, env=env, timeout=timeout)


def test_launcher_parses_and_quits_cleanly():
    # regression: stray ')' in an if-block once broke cmd parsing (255).
    r = run_bat_auto(r"C:\definitely-missing-folder", {})
    out = r.stdout + r.stderr
    assert "unexpected at this time" not in out
    assert r.returncode == 0


@NEED_FFMPEG
def test_launcher_menu_sets_filter_and_runs(tmp_path):
    # an untagged MP3: lyrify skips it fast, no network needed
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-codec:a", "libmp3lame", "-qscale:a", "9",
         os.path.join(str(tmp_path), "noise.mp3"), "-loglevel", "error"],
        check=True, capture_output=True)
    # album filter "My Album" + rewrite = --force
    r = run_bat_auto(str(tmp_path), {"album": "My Album", "force": True})
    out = r.stdout + r.stderr
    assert "unexpected at this time" not in out
    assert '--album="My Album"' in out
    assert "--force" in out
    assert r.returncode == 0


# --- clean_song_query -------------------------------------------------------

def test_clean_song_query():
    m = load_fresh()
    assert m.clean_song_query("Queen", "Bohemian Rhapsody - Remastered 2011") == ("Queen", "Bohemian Rhapsody")
    assert m.clean_song_query("Eminem feat. Rihanna", "Love the Way You Lie (feat. Rihanna)") == ("Eminem", "Love the Way You Lie")
    assert m.clean_song_query("Nirvana", "Smells Like Teen Spirit (Remastered)") == ("Nirvana", "Smells Like Teen Spirit")
    assert m.clean_song_query("Coldplay", "Yellow [Official HD Music Video]") == ("Coldplay", "Yellow")
    assert m.clean_song_query("Eagles", "Hotel California - 2013 Remaster") == ("Eagles", "Hotel California")


# --- fetch_lrclib (mocked) --------------------------------------------------

class FakeLrclibSession:
    def __init__(self, get_responses):
        self.get_responses = get_responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        res = self.get_responses.get(url, Resp(404, {}))
        if isinstance(res, Exception):
            raise res
        return res


def test_fetch_lrclib_exact_match():
    m = load_fresh()
    s = FakeLrclibSession({
        "https://lrclib.net/api/get": Resp(200, {
            "plainLyrics": "Is this the real life?",
            "syncedLyrics": "[00:01.00] Is this the real life?\n[00:05.00] Is this just fantasy?"
        })
    })
    res = m.fetch_lrclib("Queen", "Bohemian Rhapsody", s)
    assert "Is this the real life?" in res
    assert res.synced is not None
    assert "[00:01.00]" in res.synced


def test_fetch_lrclib_search_fallback():
    m = load_fresh()
    s = FakeLrclibSession({
        "https://lrclib.net/api/get": Resp(404, {}),
        "https://lrclib.net/api/search": Resp(200, [{
            "plainLyrics": "Look at the stars",
            "syncedLyrics": "[00:10.00] Look at the stars"
        }])
    })
    res = m.fetch_lrclib("Coldplay", "Yellow", s)
    assert res == "Look at the stars"
    assert res.synced == "[00:10.00] Look at the stars"


def test_fetch_lrclib_not_found_raises():
    m = load_fresh()
    s = FakeLrclibSession({
        "https://lrclib.net/api/get": Resp(404, {}),
        "https://lrclib.net/api/search": Resp(200, [])
    })
    with pytest.raises(m.LyricsNotFound):
        m.fetch_lrclib("NonExistent", "SongThatDoesNotExist", s)


# --- multi-format tag saving & LRC companion --------------------------------

@NEED_FFMPEG
def test_all_formats_tagging_and_lrc(tmp_path):
    m = load_fresh()
    formats = [
        ("track.mp3", "libmp3lame"),
        ("track.flac", "flac"),
        ("track.m4a", "aac"),
        ("track.ogg", "libvorbis"),
        ("track.wav", "pcm_s16le"),
    ]
    for name, codec in formats:
        p = os.path.join(str(tmp_path), name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
             "-c:a", codec, p, "-loglevel", "error"],
            check=True)
        aud = m.MutagenFile(p)
        lyrics_obj = m.LyricsResult("Plain song lyrics", synced="[00:01.00] Synced lyric")
        ok = m.set_lyrics(aud, p, lyrics_obj, save_lrc=True)
        assert ok, f"Failed to set lyrics on {name}"

        # verify embedded lyrics
        aud_check = m.MutagenFile(p)
        embedded = m.get_lyrics(aud_check)
        assert embedded == "Plain song lyrics", f"Mismatch on {name}: {embedded}"

        # verify companion .lrc file
        lrc_file = os.path.splitext(p)[0] + ".lrc"
        assert os.path.isfile(lrc_file), f"LRC file missing for {name}"
        with open(lrc_file, "r", encoding="utf-8") as f:
            assert "[00:01.00] Synced lyric" in f.read()
