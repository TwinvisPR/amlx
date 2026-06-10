"""
Cover-art extraction from the on-disk Apple Music artwork cache.

Apple stores covers as plain JPEG/PNG files inside the ``.musiclibrary`` bundle's
``artwork/`` folder, indexed by ``artwork.sqlite``. We map each track's persistent
ID to its cached image, carve out the real image bytes (some builds wrap them),
de-duplicate identical covers by SHA-256, and (optionally) fall back to Apple's
public catalog for the rare track missing from the local cache.

No audio is touched — only the album-art thumbnails already cached on the machine.
"""

import os
import sqlite3
import hashlib
import json
import ssl
import urllib.request
import urllib.parse
import difflib

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"


def _carve(raw):
    """Return (image_bytes, ext) carved from the first known magic, else (None, None)."""
    for magic, ext in ((_JPEG, "jpeg"), (_PNG, "png")):
        i = raw.find(magic)
        if i != -1:
            return raw[i:], ext
    return None, None


def _load_index(musiclibrary_dir):
    """Return (item->artwork_id, artwork_id->[(size_kind,ext)], set(files))."""
    db = os.path.join(musiclibrary_dir, "artwork.sqlite")
    art_dir = os.path.join(musiclibrary_dir, "artwork")
    if not os.path.exists(db) or not os.path.isdir(art_dir):
        return None
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    item_to_art = {}
    for item_id, artwork_id in con.execute("SELECT item_id, artwork_id FROM item_to_artwork"):
        pid = "%016X" % (item_id & 0xFFFFFFFFFFFFFFFF)
        item_to_art.setdefault(pid, artwork_id)
    cache = {}
    for art, sk, ext in con.execute("SELECT artwork_id, size_kind, extension FROM cache_items"):
        cache.setdefault(art, []).append((sk, ext))
    con.close()
    return item_to_art, cache, set(os.listdir(art_dir)), art_dir


def _find_file(artwork_id, cache, files):
    for sk, ext in sorted(cache.get(artwork_id, [])):
        for cand in (f"{artwork_id}_sk{sk}.{ext}",
                     f"{artwork_id}_sk{sk}.jpeg",
                     f"{artwork_id}_sk{sk}.jpg",
                     f"{artwork_id}_sk{sk}.png"):
            if cand in files:
                return cand
    for f in files:                      # last resort: any file for this artwork id
        if f.startswith(artwork_id):
            return f
    return None


def _itunes_cover(artist, title, ctx):
    """Best-effort 600x600 cover via the public iTunes Search API."""
    headers = {"User-Agent": "Mozilla/5.0"}
    best, best_score = None, 0.0
    for country in ("us", "fr", "gb", "de"):
        for term in (f"{artist} {title}", title):
            url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
                {"term": term, "entity": "song", "limit": 15, "country": country})
            try:
                req = urllib.request.Request(url, headers=headers)
                res = json.load(urllib.request.urlopen(req, context=ctx, timeout=20)).get("results", [])
            except Exception:
                res = []
            for r in res:
                s = (difflib.SequenceMatcher(None, r.get("artistName", "").lower(), artist.lower()).ratio()
                     + difflib.SequenceMatcher(None, r.get("trackName", "").lower(), title.lower()).ratio()) / 2
                if s > best_score:
                    best_score, best = s, r
    if best and best_score > 0.6:
        art = best.get("artworkUrl100", "")
        big = art.replace("100x100bb.jpg", "600x600bb.jpg").replace("100x100bb.png", "600x600bb.png")
        try:
            req = urllib.request.Request(big, headers=headers)
            return urllib.request.urlopen(req, context=ctx, timeout=30).read()
        except Exception:
            return None
    return None


def extract(tracks, musiclibrary_dir, out_dir, cdn_fallback=False, log=print):
    """
    Save deduped covers into ``out_dir/artwork/`` and return:
      (artwork_map, stats)  where artwork_map[persistent_id] = (rel_path, sha256)
      and stats = {'cache': n, 'cdn': n, 'missing': n, 'unique_images': n}
    """
    art_out = os.path.join(out_dir, "artwork")
    os.makedirs(art_out, exist_ok=True)
    idx = _load_index(musiclibrary_dir)
    stats = {"cache": 0, "cdn": 0, "missing": 0, "unique_images": 0}
    if idx is None:
        log("  (no artwork cache found — skipping covers)")
        return {}, stats
    item_to_art, cache, files, art_dir = idx

    hash_to_rel = {}
    artwork_map = {}

    def store(img, ext, pid):
        h = hashlib.sha256(img).hexdigest()
        if h not in hash_to_rel:
            name = f"{pid}.{ext}"
            if os.path.exists(os.path.join(art_out, name)):
                name = f"{pid}_{h[:8]}.{ext}"
            with open(os.path.join(art_out, name), "wb") as fh:
                fh.write(img)
            hash_to_rel[h] = f"artwork/{name}"
            stats["unique_images"] += 1
        return hash_to_rel[h], h

    cdn_targets = []
    for t in tracks:
        pid = t["persistent_id"]
        art = item_to_art.get(pid)
        fn = _find_file(art, cache, files) if art else None
        if fn:
            img, ext = _carve(open(os.path.join(art_dir, fn), "rb").read())
            if img:
                artwork_map[pid] = store(img, ext, pid)
                stats["cache"] += 1
                continue
        cdn_targets.append(t)

    if cdn_fallback and cdn_targets:
        ctx = ssl.create_default_context()
        log(f"  fetching {len(cdn_targets)} missing cover(s) from Apple catalog...")
        for t in cdn_targets:
            img_raw = _itunes_cover(t.get("artist") or "", t.get("title") or "", ctx)
            if img_raw:
                img, ext = _carve(img_raw)
                if img:
                    artwork_map[t["persistent_id"]] = store(img, ext, t["persistent_id"])
                    stats["cdn"] += 1
                    continue
            stats["missing"] += 1
    else:
        stats["missing"] = len(cdn_targets)

    return artwork_map, stats
