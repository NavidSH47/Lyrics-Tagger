#!/usr/bin/env python3
"""
lyrify.py — batch-add lyrics to MP3 (and other audio) files from their ID3/metadata tags.

Providers (tried in order; --provider to force one):
  1. genius   — verified lyrics & annotations (needs free GENIUS_ACCESS_TOKEN or client credentials).
  2. lrclib   — free, open, fast API (lrclib.net) with plain + timestamped synced lyrics.
  3. lyricsovh — free no-token API (api.lyrics.ovh).
  4. search   — last-resort web search fallback (Bing/DuckDuckGo).

Filters: --album, --artist, --title, --year, --genre, --skip-existing (default),
         --only-missing, --dry-run, --ext, --save-lrc, --workers.

Example:
  python lyrify.py "D:/Music" --album "Dark Side of the Moon" --dry-run
  python lyrify.py "D:/Music" --artist "Pink Floyd" --force
  python lyrify.py "D:/Music" --provider lrclib --save-lrc
  python lyrify.py "D:/Music" --workers 4
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time

import requests
from bs4 import BeautifulSoup

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import USLT, ID3, ID3NoHeaderError
except ImportError:
    sys.exit("mutagen not installed: pip install mutagen")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
LRCLIB_HEADERS = {"User-Agent": "Lyrify/2.0 (https://github.com/lyrify)"}
SUPPORTED_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus"}
USLT_LANG = "eng"
USLT_DESC = ""  # empty desc: players show no "lyrics" label in front of the text


# --------------------------------------------------------------------------
# data structures & helpers
# --------------------------------------------------------------------------

class LyricsNotFound(Exception):
    pass


class LyricsResult(str):
    """String subclass that also carries optional synced lyrics."""
    def __new__(cls, text, synced=None):
        obj = super().__new__(cls, text)
        obj.synced = synced
        return obj


def clean_song_query(artist, title):
    """Strip feat., remaster, live, official tags from title and artist for fuzzy retry."""
    clean_t = title
    # Remove bracketed/parenthesized extra info
    clean_t = re.sub(
        r"\s*[\(\[](?:feat\.?|ft\.?|featuring|remaster(?:ed)?|live|official|audio|video|deluxe|version|mono|stereo|bonus|radio edit|original mix)[\s\S]*?[\)\]]",
        "", clean_t, flags=re.I)
    # Remove trailing ' - Remastered / Live / etc.'
    clean_t = re.sub(
        r"\s*-\s*.*?(?:remaster(?:ed)?|live|official|deluxe|radio edit|mono|stereo|bonus track).*$",
        "", clean_t, flags=re.I)
    clean_t = clean_t.strip()

    clean_a = artist
    clean_a = re.sub(r"\s*(?:feat\.?|ft\.?|featuring|vs\.?)\s+.*$", "", clean_a, flags=re.I)
    clean_a = clean_a.strip()
    return clean_a or artist, clean_t or title


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------

def fetch_lrclib(artist, title, session=None):
    """Free no-token API with plain & synced lyrics: https://lrclib.net"""
    session = session or requests.Session()
    # 1. Exact match
    try:
        r = session.get(
            "https://lrclib.net/api/get",
            params={"artist_name": artist, "track_name": title},
            headers=LRCLIB_HEADERS,
            timeout=12)
        if r.status_code == 200:
            data = r.json()
            synced = (data.get("syncedLyrics") or "").strip() or None
            plain = (data.get("plainLyrics") or "").strip()
            if plain:
                return LyricsResult(plain, synced=synced)
            elif synced:
                lines = [re.sub(r"^\[\d{2}:\d{2}\.\d{2,3}\]\s*", "", l) for l in synced.splitlines()]
                return LyricsResult("\n".join(lines).strip(), synced=synced)
    except Exception:
        pass

    # 2. Search fallback
    try:
        q = "{} {}".format(artist, title)
        r = session.get(
            "https://lrclib.net/api/search",
            params={"q": q},
            headers=LRCLIB_HEADERS,
            timeout=12)
        if r.status_code == 200:
            hits = r.json()
            if isinstance(hits, list):
                for item in hits:
                    synced = (item.get("syncedLyrics") or "").strip() or None
                    plain = (item.get("plainLyrics") or "").strip()
                    if plain:
                        return LyricsResult(plain, synced=synced)
                    elif synced:
                        lines = [re.sub(r"^\[\d{2}:\d{2}\.\d{2,3}\]\s*", "", l) for l in synced.splitlines()]
                        return LyricsResult("\n".join(lines).strip(), synced=synced)
    except Exception:
        pass

    raise LyricsNotFound("lrclib: no lyrics found for {!r} — {!r}".format(artist, title))


def fetch_lyricsovh(artist, title, session=None):
    """Free no-token API: https://api.lyrics.ovh/v1/artist/title"""
    session = session or requests.Session()
    url = "https://api.lyrics.ovh/v1/{}/{}".format(
        requests.utils.quote(artist), requests.utils.quote(title))
    r = session.get(url, headers=HEADERS, timeout=15)
    if r.status_code == 404:
        raise LyricsNotFound("lyrics.ovh: no lyrics for {!r} — {!r}".format(artist, title))
    r.raise_for_status()
    lyrics = r.json().get("lyrics", "").strip()
    if not lyrics:
        raise LyricsNotFound("lyrics.ovh: empty result")
    return lyrics


_TOKEN_CACHE = {}


def genius_access_token(session):
    """Resolve a bearer token from env: classic token, or OAuth client_credentials."""
    if _TOKEN_CACHE.get("token"):
        return _TOKEN_CACHE["token"]
    token = (os.environ.get("GENIUS_ACCESS_TOKEN") or os.environ.get("GENIUS_TOKEN"))
    if token:
        _TOKEN_CACHE["token"] = token
        return token
    cid = os.environ.get("GENIUS_CLIENT_ID")
    sec = os.environ.get("GENIUS_CLIENT_SECRET")
    if not (cid and sec):
        raise LyricsNotFound("genius: no GENIUS_ACCESS_TOKEN nor GENIUS_CLIENT_ID/SECRET set (skipping)")
    r = session.post(
        "https://api.genius.com/oauth/token",
        json={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec},
        headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise LyricsNotFound("genius: token exchange failed (HTTP {})".format(r.status_code))
    tok = r.json().get("access_token")
    if not tok:
        raise LyricsNotFound("genius: token response missing access_token")
    _TOKEN_CACHE["token"] = tok
    return tok


def fetch_genius(artist, title, session):
    """Genius search API + page scrape. Token from env (classic or OAuth)."""
    token = genius_access_token(session)
    q = requests.utils.quote("{} {}".format(artist, title))
    r = session.get("https://api.genius.com/search?q={}".format(q),
                    headers={**HEADERS, "Authorization": "Bearer " + token}, timeout=15)
    r.raise_for_status()
    hits = r.json().get("response", {}).get("hits", [])
    for hit in hits:
        song = hit.get("result", {})
        if not song:
            continue
        path = song.get("path")
        if not path:
            continue
        page = session.get("https://genius.com" + path, headers=HEADERS, timeout=20)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        containers = soup.select("div[data-lyrics-container='true']")
        if not containers:
            continue
        chunks = []
        for c in containers:
            for br in c.find_all("br"):
                br.replace_with("\n")
            chunks.append(c.get_text("\n"))
        text = "\n".join(chunks)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 60:
            return text
    raise LyricsNotFound("genius: no lyrics found for {!r} — {!r}".format(artist, title))


LYRICS_CONTAINERS = [
    "div[data-lyrics-container='true']",
    "div.lyrics", "div.lyricbox", "div#lyrics", "div.lyrics-text",
    "div.song-lyrics", "p.lyrics", "div.lyric", "div#lyric", "div.lyricbox",
    "div.lyrics__content", "div[class*='lyrics']",
]
JUNK_BLOCK_RE = re.compile(r"contributors?|translations?\b", re.I)


def _block_text(el):
    """Clean text of one candidate lyrics element; None if it's junk/too short."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    lines = [l.strip() for l in el.get_text("\n").splitlines() if l.strip()]
    lines = [l for l in lines
             if not re.search(r"^(lyrics|share|embed|about|advert|you might also|correct these)", l, re.I)]
    if len(lines) < 4:
        return None
    txt = "\n".join(lines)
    if len(txt) <= 100 or JUNK_BLOCK_RE.search(txt[:300]):
        return None
    return txt


def extract_lyrics_from_html(html):
    """Pick real lyric blocks (skip Contributors/Translations boxes), else longest block."""
    soup = BeautifulSoup(html, "html.parser")
    for sel in LYRICS_CONTAINERS:
        parts = []
        for el in soup.select(sel):
            txt = _block_text(el)
            if txt:
                parts.append(txt)
        if parts:
            return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)).strip()
    soup2 = BeautifulSoup(html, "html.parser")
    for tag in soup2(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    best = ""
    for el in soup2.find_all(["div", "p", "article", "pre"]):
        txt = el.get_text("\n", strip=True)
        if len(txt) > len(best):
            best = txt
    if len(best) > 200:
        return re.sub(r"\n{3,}", "\n\n", best).strip()
    raise LyricsNotFound("no lyrics block found in page")


HEADING_RE = re.compile(r"^(?:lyrics|song lyrics)$", re.I)
TITLE_LYRICS_RE = re.compile(r"^[A-Z][^.?]{0,60}\s+[lL]yrics$")
LYRICS_PREFIX_RE = re.compile(r"^lyrics[:\s]+", re.I)


def clean_lyrics(text):
    """Strip leading 'Lyrics'/'Song Title Lyrics'/'Lyrics to ...' headings and blanks."""
    synced = getattr(text, "synced", None)
    lines = [l.strip() for l in str(text).splitlines()]
    while lines and (not lines[0]
                     or HEADING_RE.match(lines[0])
                     or TITLE_LYRICS_RE.match(lines[0])
                     or LYRICS_PREFIX_RE.match(lines[0])):
        lines.pop(0)
    while lines and not lines[0]:
        lines.pop(0)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return LyricsResult(cleaned, synced=synced) if synced else cleaned


def fetch_search(artist, title, session):
    """Last resort: Bing/DuckDuckGo search → open a lyrics page → extract full lyrics."""
    q = requests.utils.quote("{} {} lyrics".format(artist, title))
    links = []
    for engine in ("bing", "ddg"):
        try:
            if engine == "bing":
                r = session.get("https://www.bing.com/search?q=" + q,
                                headers=HEADERS, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")
                hrefs = [a.get("href") for a in soup.select("li.b_algo h2 a")]
            else:
                r = session.get("https://html.duckduckgo.com/html/?q=" + q,
                                headers=HEADERS, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")
                hrefs = [a.get("href") for a in soup.select("a.result__a")]
            links.extend(h for h in hrefs if h and h.startswith("http"))
        except Exception:
            continue
    if not links:
        raise LyricsNotFound("search: no results for {!r} — {!r}".format(artist, title))
    seen, uniq = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    uniq.sort(key=lambda u: 0 if "lyrics" in u.lower() or "azlyrics" in u.lower() else 1)
    last_err = None
    for url in uniq[:3]:
        try:
            page = session.get(url, headers=HEADERS, timeout=20)
            page.raise_for_status()
            return extract_lyrics_from_html(page.text)
        except Exception as e:
            last_err = e
            continue
    raise LyricsNotFound("search: could not extract lyrics for {!r} — {!r} ({})".format(
        artist, title, last_err or "parse failed"))


PROVIDERS = {
    "lrclib": fetch_lrclib,
    "genius": fetch_genius,
    "lyricsovh": fetch_lyricsovh,
    "search": fetch_search,
}

# --------------------------------------------------------------------------
# tag reading / writing
# --------------------------------------------------------------------------

def get_lyrics(audio):
    """Return existing embedded lyrics string, or None."""
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None
    if isinstance(tags, ID3):
        for frame in tags.getall("USLT"):
            if frame.text and frame.text.strip():
                return frame.text.strip()
    else:
        tags_type = type(tags).__name__.lower()
        if "mp4" in tags_type:
            candidate_keys = ["\xa9lyr", "lyrics"]
        else:
            candidate_keys = ["lyrics", "unsyncedlyrics", "LYRICS", "UNSYNCEDLYRICS"]
        for key in candidate_keys:
            try:
                if key in tags:
                    v = tags[key]
                    if isinstance(v, list) and v:
                        v = v[0]
                    if v and str(v).strip():
                        return str(v).strip()
            except (KeyError, ValueError, TypeError):
                continue
    return None


GENERIC_ALBUM_ARTISTS = {"various artists", "va", "various", "compilation",
                         "soundtrack", "ost", "original soundtrack",
                         "original motion picture soundtrack"}


def resolve_artist(tags):
    """Album artist if set and meaningful, else the track artist."""
    def tag(*keys):
        for k in keys:
            if k in tags:
                v = tags[k]
                if isinstance(v, list):
                    v = v[0] if v else ""
                s = str(v).strip()
                if s:
                    return s
        return ""

    track = tag("artist", "TPE1", "\xa9ART")
    album = tag("albumartist", "album artist", "TPE2", "aART")
    if album and album.lower() not in GENERIC_ALBUM_ARTISTS:
        return album
    return track


def set_lyrics(audio, path, lyrics, save_lrc=False):
    """Write lyrics into the file's native lyric frame and optionally save companion .lrc."""
    ext = os.path.splitext(path)[1].lower()
    plain_text = str(lyrics).strip()
    synced_text = getattr(lyrics, "synced", None)

    try:
        if ext == ".mp3":
            tags = audio.tags if isinstance(audio.tags, ID3) else None
            if tags is None:
                try:
                    tags = ID3(path)
                except ID3NoHeaderError:
                    tags = ID3()
            tags.delall("USLT")
            tags.add(USLT(encoding=3, lang=USLT_LANG, desc=USLT_DESC, text=plain_text))
            tags.save(path)
        elif ext == ".wav":
            if audio.tags is None:
                audio.add_tags()
            audio.tags.delall("USLT")
            audio.tags.add(USLT(encoding=3, lang=USLT_LANG, desc=USLT_DESC, text=plain_text))
            audio.save()
        elif ext in (".m4a", ".mp4"):
            if audio.tags is None:
                audio.add_tags()
            audio.tags["\xa9lyr"] = [plain_text]
            audio.save()
        else:
            # FLAC, OGG, OPUS (VorbisComment)
            if audio.tags is None:
                audio.add_tags()
            for k in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS"):
                try:
                    if k in audio.tags:
                        del audio.tags[k]
                except (KeyError, ValueError, TypeError):
                    pass
            audio.tags["LYRICS"] = [plain_text]
            audio.tags["UNSYNCEDLYRICS"] = [plain_text]
            audio.save()

        if save_lrc:
            lrc_path = os.path.splitext(path)[0] + ".lrc"
            lrc_content = synced_text if synced_text else plain_text
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lrc_content.strip() + "\n")

        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# --show: print embedded lyrics of one file (or search a directory)
# --------------------------------------------------------------------------

def print_lyrics_of(path):
    """Print embedded lyrics of one audio file (and companion .lrc if exists)."""
    try:
        audio = MutagenFile(path)
    except Exception as e:
        print("Could not read {}: {}".format(path, e), file=sys.stderr)
        return 1
    if audio is None or audio.tags is None:
        print("No readable tags in {}".format(path), file=sys.stderr)
        return 1
    lyrics = get_lyrics(audio)
    lrc_path = os.path.splitext(path)[0] + ".lrc"
    has_lrc = os.path.isfile(lrc_path)

    if not lyrics and not has_lrc:
        print("(no embedded lyrics or .lrc in {})".format(os.path.basename(path)))
        return 0

    if has_lrc:
        print("[LRC companion file: {}]".format(os.path.basename(lrc_path)))
    if lyrics:
        print("{} — embedded lyrics:".format(os.path.basename(path)))
        print()
        print(lyrics)
    elif has_lrc:
        print("{} — .lrc file contents:".format(os.path.basename(path)))
        print()
        with open(lrc_path, "r", encoding="utf-8", errors="replace") as f:
            print(f.read())
    return 0


def run_show(query, root, exts):
    """`--show` handler: accept a file path, else search title/artist/filename."""
    if os.path.isfile(query):
        return print_lyrics_of(os.path.abspath(query))
    if not root or not os.path.isdir(root):
        print("--show needs an existing audio file path, or a music directory\n"
              "to search in as the first argument.", file=sys.stderr)
        return 1
    q = query.lower()
    matches = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            full = os.path.join(dirpath, name)
            try:
                audio = MutagenFile(full)
                if audio is None or audio.tags is None:
                    continue
                t = audio.tags
                def tag(*keys):
                    for k in keys:
                        if k in t:
                            v = t[k]
                            v = v[0] if isinstance(v, list) and v else v
                            if v:
                                return str(v).strip().lower()
                    return ""
                title = tag("title", "TIT2")
                artist = tag("artist", "TPE1")
                if q in "{} {} {}".format(title, artist, name.lower()):
                    matches.append((title, artist, full))
            except Exception:
                continue
    if len(matches) == 1:
        return print_lyrics_of(matches[0][2])
    if len(matches) > 1:
        print("Multiple matches for {!r}:".format(query))
        for i, (title, artist, full) in enumerate(matches, 1):
            print("  {}. {} — {} ({})".format(i, artist or "?", title or "?", os.path.basename(full)))
        return 0
    print("No song matching {!r} in {}".format(query, root), file=sys.stderr)
    return 1


# --------------------------------------------------------------------------
# core processor
# --------------------------------------------------------------------------

def process_file(path, args, session, stats, lock=None, index=1, total=1):
    """Process a single audio file: reads tags, fetches lyrics, writes lyrics tag."""
    pct = int((index / total) * 100) if total else 0
    prefix = "[{:>{width}}/{}] ({:3}%)".format(index, total, pct, width=len(str(total)))

    try:
        audio = MutagenFile(path)
        if audio is None or audio.tags is None:
            with lock if lock else threading.Lock():
                print("{} [skip] {} — no tags, can't identify song".format(prefix, os.path.basename(path)))
                stats["skipped_filter"] += 1
            return

        t = audio.tags
        def tag(*keys):
            for k in keys:
                if k in t:
                    v = t[k]
                    if isinstance(v, list):
                        v = v[0] if v else ""
                    s = str(v).strip()
                    if s:
                        return s
            return ""

        title = tag("title", "TIT2")
        artist = resolve_artist(t)
        album = tag("album", "TALB")
        genre = tag("genre", "TCON")
        year = tag("date", "year", "TDRC")

        # ---- filters ----
        if args.album and args.album.lower() not in album.lower():
            with lock if lock else threading.Lock():
                stats["skipped_filter"] += 1
            return
        if args.artist and args.artist.lower() not in artist.lower():
            with lock if lock else threading.Lock():
                stats["skipped_filter"] += 1
            return
        if args.title and args.title.lower() not in title.lower():
            with lock if lock else threading.Lock():
                stats["skipped_filter"] += 1
            return
        if args.year and args.year != year:
            with lock if lock else threading.Lock():
                stats["skipped_filter"] += 1
            return
        if args.genre and args.genre.lower() not in genre.lower():
            with lock if lock else threading.Lock():
                stats["skipped_filter"] += 1
            return

        existing = get_lyrics(audio)
        if existing and not args.force:
            with lock if lock else threading.Lock():
                stats["skipped_existing"] += 1
                if args.verbose:
                    print("{} [skip] {} — lyrics already present".format(prefix, os.path.basename(path)))
            return

        if not title or not artist:
            with lock if lock else threading.Lock():
                print("{} [warn] {} — missing title/artist, can't search".format(prefix, os.path.basename(path)))
                stats["errors"] += 1
            return

        # ---- fetch ----
        lyrics, prov = None, None
        if args.provider != "auto":
            provs = [args.provider]
        else:
            provs = ["genius", "lrclib", "lyricsovh", "search"]

        for p in provs:
            try:
                lyrics = PROVIDERS[p](artist, title, session)
                prov = p
                break
            except LyricsNotFound:
                # Fuzzy retry with cleaned artist & title
                c_artist, c_title = clean_song_query(artist, title)
                if (c_artist, c_title) != (artist, title):
                    try:
                        lyrics = PROVIDERS[p](c_artist, c_title, session)
                        prov = p
                        break
                    except Exception:
                        pass
                continue
            except Exception as e:
                if args.verbose:
                    with lock if lock else threading.Lock():
                        print("{}   …{} failed: {}".format(prefix, p, e))
                continue

        if not lyrics:
            with lock if lock else threading.Lock():
                print("{} [miss] {} — {} — no lyrics from any provider".format(prefix, artist, title))
                stats["no_lyrics"] += 1
            return

        lyrics = clean_lyrics(lyrics)
        is_synced = bool(getattr(lyrics, "synced", None))
        type_badge = " (synced)" if is_synced else ""

        if args.dry_run:
            with lock if lock else threading.Lock():
                print("{} [dry ] [{}] {} — {} ({} chars{})".format(
                    prefix, prov, artist, title, len(lyrics), type_badge))
        else:
            save_lrc = getattr(args, "save_lrc", False)
            if set_lyrics(audio, path, lyrics, save_lrc=save_lrc):
                with lock if lock else threading.Lock():
                    lrc_note = " + .lrc" if save_lrc else ""
                    print("{} [ok  ] [{}] {} — {} ({} chars{}{})".format(
                        prefix, prov, artist, title, len(lyrics), type_badge, lrc_note))
                    stats["written"] += 1
            else:
                with lock if lock else threading.Lock():
                    print("{} [fail] {} — could not write tags".format(prefix, path))
                    stats["errors"] += 1

    except Exception as e:
        with lock if lock else threading.Lock():
            stats["errors"] += 1
            print("{} [err ] {} — {}".format(prefix, os.path.basename(path), e))


def main():
    ap = argparse.ArgumentParser(
        description="Batch-add lyrics to audio files from their tags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Example:")[0])
    ap.add_argument("dir", nargs="?", default=None, metavar="DIR",
                    help="directory with music files (searched recursively)")
    ap.add_argument("--show", metavar="QUERY",
                    help="print embedded lyrics: give a file path, or a "
                         "title/artist/filename to search for in DIR")
    ap.add_argument("--ext", nargs="+", default=sorted(SUPPORTED_EXTS),
                    help="file extensions to process (default: all supported)")
    ap.add_argument("--provider", choices=list(PROVIDERS) + ["auto"], default="auto",
                    help="lyrics source (default: auto = genius→lrclib→lyricsovh→search)")
    ap.add_argument("--album", help="only files whose ALBUM tag contains this (case-insensitive)")
    ap.add_argument("--artist", help="only files whose ARTIST tag contains this")
    ap.add_argument("--title", help="only files whose TITLE tag contains this")
    ap.add_argument("--year", help="only files whose DATE/YEAR tag matches (exact)")
    ap.add_argument("--genre", help="only files whose GENRE tag contains this")
    ap.add_argument("--skip-existing", action="store_true", default=True,
                    help="skip files that already have lyrics (default)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing lyrics (implies --no-skip-existing)")
    ap.add_argument("--only-missing", action="store_true",
                    help="only files WITHOUT lyrics (same as --skip-existing)")
    ap.add_argument("--save-lrc", action="store_true",
                    help="also save companion .lrc file next to audio file (synced if available)")
    ap.add_argument("--workers", "-j", type=int, default=1,
                    help="number of concurrent worker threads (default: 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan + fetch but do NOT write anything")
    ap.add_argument("--verbose", action="store_true", help="show per-file details")
    args = ap.parse_args()

    root = os.path.abspath(args.dir) if args.dir else None
    if root and not os.path.isdir(root):
        sys.exit("Not a directory: " + root)

    if args.show is not None:
        sys.exit(run_show(args.show, root, args.ext))

    if not root:
        sys.exit("a directory is required (e.g. python lyrify.py \"D:/Music\", "
                 "or lyrify.py --show song.mp3)")

    # collect files
    files = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext in args.ext:
                files.append(os.path.join(dirpath, name))
    if not files:
        sys.exit("No files found with extensions {} in {}".format(args.ext, root))

    files.sort()
    total = len(files)
    print("[scan] {} files in {}".format(total, root))
    stats = {"written": 0, "skipped_existing": 0, "skipped_filter": 0,
             "no_lyrics": 0, "errors": 0}
    lock = threading.Lock()

    if args.workers > 1:
        thread_local = threading.local()
        def get_session():
            if not hasattr(thread_local, "session"):
                s = requests.Session()
                s.headers.update(HEADERS)
                thread_local.session = s
            return thread_local.session

        def worker_task(idx, item):
            s = get_session()
            process_file(item, args, s, stats, lock=lock, index=idx, total=total)
            time.sleep(0.2)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(worker_task, i, path) for i, path in enumerate(files, 1)]
            concurrent.futures.wait(futures)
    else:
        session = requests.Session()
        session.headers.update(HEADERS)
        for i, path in enumerate(files, 1):
            process_file(path, args, session, stats, lock=lock, index=i, total=total)
            time.sleep(0.3)  # polite interval

    print("\n=== done ===")
    print(json.dumps(stats, indent=2))
    sys.exit(0 if stats["errors"] == 0 else 1)


if __name__ == "__main__":
    main()
