# lyrify — batch-add lyrics to your music files

Scans a folder of audio files, reads each file's own tags (artist / title / album),
fetches lyrics, and writes them into the file's lyrics tag so any player (Windows
Media Player, VLC, MusicBee, iTunes, Android / iOS phones…) shows them.

```
        ┌──────────┐   read tags    ┌─────────────┐   fetch    ┌──────────┐
        │   .mp3   │ ─────────────▶ │ lyrify.py   │ ─────────▶ │ genius   │  verified (optional)
        │ .flac/.  │ ◀───────────── │             │ ◀───────── │ lrclib   │  free, fast, synced
        └──────────┘  write USLT/   └─────────────┘            │ lyricsovh│  free, no token
                       lyrics tag                              │ search   │  last resort
                                                               └──────────┘
```

## Install

```bash
pip install -r requirements.txt
```

## Usage

**Double-click launcher (easiest):** double-click `add-lyrics.bat`, drag a music
folder onto the window (or type its path), and answer the prompts (rewrite existing?
save companion `.lrc` files? y/N). It uses the bundled venv automatically,
and if the venv or dependencies are missing it creates/installs them itself on
first run. Optional Genius credentials can go in a `genius.env` file next to it
(copy `genius.env.example`). For a no-write preview use the CLI with
`--dry-run`.

**Command line (filters & options):**

```bash
# add lyrics to EVERYTHING under D:/Music (skips tracks that already have lyrics)
python lyrify.py "D:/Music"

# preview first — nothing is written
python lyrify.py "D:/Music" --dry-run

# also save companion .lrc files (synced if available) for mobile music players
python lyrify.py "D:/Music" --save-lrc

# run multithreaded (e.g. 4 concurrent workers) for fast library processing
python lyrify.py "D:/Music" --workers 4

# only one album (case-insensitive)
python lyrify.py "D:/Music" --album "A Night at the Opera"

# only one artist
python lyrify.py "D:/Music" --artist "Pink Floyd"

# only files WITHOUT lyrics (same as default --skip-existing)
python lyrify.py "D:/Music" --only-missing

# force-overwrite existing lyrics
python lyrify.py "D:/Music" --force

# print embedded lyrics: a file path, or a title/artist/filename in a folder
python lyrify.py --show "D:/Music/Song.mp3"
python lyrify.py "D:/Music" --show "Song Title"

# force a specific provider / limit file types
python lyrify.py "D:/Music" --provider lrclib
python lyrify.py "D:/Music" --ext .mp3 .flac
```

## Filters & Options

| Flag              | What it does                                                 |
|-------------------|--------------------------------------------------------------|
| `--save-lrc`      | Write companion `.lrc` files (synced timestamped if available)|
| `--workers`, `-j` | Number of parallel worker threads (e.g. `-j 4`)             |
| `--album`         | album tag (substring, case-insensitive)                      |
| `--artist`        | artist tag                                                   |
| `--title`         | title tag                                                    |
| `--year`          | date/year tag (exact)                                        |
| `--genre`         | genre tag                                                    |
| `--skip-existing` | (default) skip files that already contain lyrics             |
| `--force`         | overwrite existing lyrics                                    |
| `--dry-run`       | show what would happen, write nothing                        |
| `--ext`           | only these extensions (.mp3 .flac .m4a .ogg .wav .opus)      |

**Artist & Title fuzzy matching:** Lyrics lookups automatically clean noisy tag
suffixes like `(feat. ...)`, `(Remastered 2011)`, `[Official HD Video]`, etc. as
a smart fallback if exact search yields no hits!

## Providers

Tried in this order in `auto` mode:

1. **genius** — best, most accurate lyrics, verified annotations. Needs a free token. If none is set, it skips silently to LRCLIB.
2. **lrclib** — free, open, fast API (`lrclib.net`) with synced lyrics (`.lrc`) and plain lyrics. No token required.
3. **lyricsovh** — free no-token API (`api.lyrics.ovh`).
4. **search** — no token, last-resort web search (Bing then DuckDuckGo).

Force any one with `--provider lrclib|genius|lyricsovh|search`.

### Get a Genius token (optional)

1. Go to https://genius.com/api-clients and click **New API Client**.
2. **App website URL** → `https://example.com`. Leave **Redirect URI** blank.
3. Copy the **Client ID** and **Client Secret**.
4. Set them in PowerShell:
   ```powershell
   $env:GENIUS_CLIENT_ID="your-client-id"
   $env:GENIUS_CLIENT_SECRET="your-client-secret"
   ```
   or drop them into `genius.env` next to `add-lyrics.bat`.

## Android Support & APK Build

You can run Lyrify directly on your Android phone or build a standalone `.apk`:

- **One-click GitHub Actions APK**: Push to GitHub and download the built APK directly from the Actions tab (no Android SDK or Linux needed!).
- **Buildozer (Local)**: `buildozer android debug` using the provided `buildozer.spec`.
- **Termux (Zero build)**: Run `python lyrify.py /sdcard/Music --save-lrc` directly on your phone.
- **Mobile GUI (`mobile_app.py`)**: Touch-friendly interface with progress bar, real-time logs, and folder selection.

See [ANDROID_GUIDE.md](file:///c:/Users/XMART/lyrics-tagger/ANDROID_GUIDE.md) for the complete walkthrough.

## Testing

```bash
python -m pytest          # deterministic, network mocked
```
