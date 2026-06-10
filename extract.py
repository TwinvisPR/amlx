#!/usr/bin/env python3
"""
Apple Music (Windows) library exporter — one command, no dependencies.

Finds your Apple Music library database, decrypts and parses it, and writes your
complete library metadata + cover art to CSV files. It never modifies the
originals (it works on a temporary copy of the database).

    python extract.py                         # auto-detect, write ./output
    python extract.py --out my_export         # choose output folder
    python extract.py --library "D:\\Path\\X.musiclibrary"
    python extract.py --no-artwork            # skip cover-art extraction
    python extract.py --cdn-fallback          # fetch missing covers from Apple's catalog

Metadata only — no audio, no DRM. It reads music you already own access to.
"""

import argparse
import glob
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amlx import musicdb            # noqa: E402
from amlx import artwork as artwork_mod   # noqa: E402
from amlx import csvwrite           # noqa: E402


def _candidate_dirs():
    cands = []
    up = os.environ.get("USERPROFILE")
    la = os.environ.get("LOCALAPPDATA")
    home = os.path.expanduser("~")
    if up:
        cands.append(os.path.join(up, "Music", "Apple Music", "Apple Music Library.musiclibrary"))
    if la:
        cands += glob.glob(os.path.join(la, "Packages", "AppleInc.AppleMusicWin_*", "LocalState"))
    cands.append(os.path.join(home, "Music", "Apple Music", "Apple Music Library.musiclibrary"))
    cands.append(os.path.join(home, "Music", "Music", "Music Library.musiclibrary"))
    # WSL: reach into the Windows filesystem
    cands += glob.glob("/mnt/c/Users/*/Music/Apple Music/Apple Music Library.musiclibrary")
    cands += glob.glob("/mnt/c/Users/*/AppData/Local/Packages/AppleInc.AppleMusicWin_*/LocalState")
    return cands


def resolve_library(arg):
    """Return (musiclibrary_dir, library_musicdb_path). Picks the newest valid db."""
    if arg:
        if os.path.isfile(arg):
            return os.path.dirname(arg), arg
        db = os.path.join(arg, "Library.musicdb")
        if os.path.isfile(db):
            return arg, db
        raise SystemExit(f"No Library.musicdb found in: {arg}")
    found = []
    for d in _candidate_dirs():
        db = os.path.join(d, "Library.musicdb")
        if os.path.isfile(db):
            found.append((os.path.getmtime(db), d, db))
    if not found:
        raise SystemExit(
            "Could not find your Apple Music library automatically.\n"
            "Pass it explicitly, e.g.:\n"
            '  python extract.py --library "%USERPROFILE%\\Music\\Apple Music\\Apple Music Library.musiclibrary"')
    found.sort(reverse=True)            # newest first
    return found[0][1], found[0][2]


def header_info(raw):
    """Read the clear-text hfma header: version, envelope, and the library's own
    declared track/playlist counts (used for an integrity cross-check)."""
    info = {"version": "?", "envelope": 0, "declared_tracks": None, "declared_playlists": None}
    try:
        info["envelope"] = int.from_bytes(raw[4:8], "little")
        info["version"] = raw[16:48].split(b"\x00", 1)[0].decode("utf-8", "ignore")
        info["declared_tracks"] = int.from_bytes(raw[68:72], "little")
        info["declared_playlists"] = int.from_bytes(raw[72:76], "little")
    except Exception:
        pass
    return info


KEY_ENV = "MUSICDB_AES_KEY"
KEY_HELP = (
    "A 16-character AES key is required and supplied at runtime (it is not\n"
    "stored in this tool). Provide it in any one of these ways:\n"
    f"  - set the {KEY_ENV} environment variable, or\n"
    "  - put it in a file named 'key.txt' next to extract.py, or\n"
    "  - in a '.env' file next to extract.py as  " + KEY_ENV + "=...\n"
    "  - pass --key on the command line"
)


def load_key(cli_key):
    """Obtain the 16-byte AES key from --key, the environment, or a local
    key.txt/.env file. The key is never stored in this repository."""
    here = os.path.dirname(os.path.abspath(__file__))
    raw = cli_key or os.environ.get(KEY_ENV)
    if not raw:
        kt = os.path.join(here, "key.txt")
        env = os.path.join(here, ".env")
        if os.path.isfile(kt):
            raw = open(kt, encoding="utf-8").read()
        elif os.path.isfile(env):
            for line in open(env, encoding="utf-8"):
                if line.strip().startswith(KEY_ENV + "="):
                    raw = line.split("=", 1)[1]
                    break
    if not raw:
        raise SystemExit("ERROR: no AES key provided.\n\n" + KEY_HELP)
    key = raw.strip().strip('"').strip("'").encode("ascii", "ignore")
    if len(key) != 16:
        raise SystemExit(f"ERROR: the AES key must be exactly 16 characters (got {len(key)}).\n\n" + KEY_HELP)
    return key


def main():
    ap = argparse.ArgumentParser(description="Export Apple Music (Windows) library metadata to CSV.")
    ap.add_argument("--library", help="Path to the .musiclibrary bundle or a Library.musicdb file")
    ap.add_argument("--out", default="output", help="Output directory (default: output)")
    ap.add_argument("--key", default=None,
                    help="The 16-char AES key (supplied at runtime; see README). "
                         "Or set %s, or a key.txt/.env file." % KEY_ENV)
    ap.add_argument("--no-artwork", action="store_true", help="Skip cover-art extraction")
    ap.add_argument("--cdn-fallback", action="store_true",
                    help="Fetch covers missing from the local cache via Apple's public catalog")
    args = ap.parse_args()

    key = load_key(args.key)

    lib_dir, db_path = resolve_library(args.library)
    print(f"Library : {db_path}")

    # Work on a temporary copy so the original is never touched.
    tmp = tempfile.mkdtemp(prefix="amlx_")
    try:
        db_copy = os.path.join(tmp, "Library.musicdb")
        shutil.copy2(db_path, db_copy)
        raw = open(db_copy, "rb").read()
        hi = header_info(raw)
        print(f"Version : {hi['version']}  (envelope {hi['envelope']} bytes, {len(raw):,} bytes)")

        print("Decrypting + parsing...")
        library = musicdb.parse(musicdb.decrypt_and_inflate(raw, key))

        artwork_map, art_stats = {}, {"cache": 0, "cdn": 0, "missing": 0, "unique_images": 0}
        if not args.no_artwork:
            print("Extracting artwork...")
            artwork_map, art_stats = artwork_mod.extract(
                library["tracks"], lib_dir, args.out, cdn_fallback=args.cdn_fallback)

        summary = csvwrite.write_all(library, artwork_map, args.out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out = os.path.abspath(args.out)
    print("\n" + "=" * 60)
    print(f"  Export complete  →  {out}")
    print("=" * 60)
    print(f"  tracks.csv          : {summary['tracks']:,} tracks "
          f"({summary['local']:,} local, {summary['cloud']:,} cloud)")
    print(f"  playlists.csv       : {summary['playlists']}")
    print(f"  playlist_tracks.csv : {summary['playlist_entries']:,} ordered entries")
    print(f"  albums.csv          : {summary['albums']:,} unique albums")
    if not args.no_artwork:
        covered = art_stats["cache"] + art_stats["cdn"]
        print(f"  artwork/            : {covered:,}/{summary['tracks']:,} tracks covered "
              f"({art_stats['unique_images']:,} unique images; "
              f"{art_stats['cache']:,} cache, {art_stats['cdn']:,} catalog, "
              f"{art_stats['missing']:,} missing)")
    print(f"  compilations        : {summary['compilations']:,}")
    print(f"  loved tracks        : {summary['loved']:,}")
    print(f"  star-rated tracks   : {summary['rated']:,}")
    if summary["missing_core"]:
        print(f"  rows missing core metadata: {summary['missing_core']}")

    # Integrity cross-check: the library declares its own counts in the header.
    print("\nIntegrity check (extracted vs. the count the library declares):")
    for label, got, declared in (
        ("tracks", summary["tracks"], hi["declared_tracks"]),
        ("playlists", summary["playlists"], hi["declared_playlists"]),
    ):
        if declared is None:
            print(f"  {label:9}: {got:,} (no declared count in header)")
        elif declared == got:
            print(f"  {label:9}: {got:,}  ==  {declared:,} declared   OK")
        else:
            print(f"  {label:9}: {got:,}  !=  {declared:,} declared   WARNING: mismatch")
    print("\nAlso compare the track count against the Songs view in the Apple Music app")
    print("(the Songs view may be slightly lower — it excludes music videos).")


if __name__ == "__main__":
    main()
