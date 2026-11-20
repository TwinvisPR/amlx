"""CSV writers — the exact output schema the project standardized on."""

import csv
import os
import re
from collections import defaultdict, Counter


def _dt(d):
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""


def _safe_filename(name, default="playlist"):
    if not name:
        return default
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip().rstrip(". ")
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
                "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if cleaned.upper() in reserved or not cleaned:
        cleaned = f"_{cleaned}" if cleaned else default
    return cleaned


def write_all(library, artwork_map, out_dir):
    """Write tracks/playlists/playlist_tracks/albums CSVs. Returns a summary dict."""
    os.makedirs(out_dir, exist_ok=True)
    tracks = library["tracks"]
    playlists = library["playlists"]
    am = artwork_map or {}

    # ---- tracks.csv ----
    local = 0
    missing_core = 0
    with open(os.path.join(out_dir, "tracks.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "artist", "album", "album_artist", "genre", "year",
                    "track_number", "duration_sec", "date_added", "last_played",
                    "play_count", "rating_stars", "favorite_flag", "compilation_flag",
                    "cloud_or_local", "local_file_path", "persistent_id",
                    "artwork_file", "artwork_hash"])
        for t in tracks:
            is_local = bool(t["file_path"])
            local += is_local
            if not t["title"] or (not t["artist"] and not t["album"]):
                missing_core += 1
            af, ah = am.get(t["persistent_id"], ("", ""))
            w.writerow([
                t["title"] or "", t["artist"] or "", t["album"] or "", t["album_artist"] or "",
                t["genre"] or "", t["year"] or "", t["track_number"] or "",
                t["duration_ms"] // 1000 if t["duration_ms"] else "",
                _dt(t["date_added"]), _dt(t["last_played"]), t["play_count"] or 0,
                (t["rating"] // 20) if t["rating"] else "",
                "true" if t["like"] == 2 else "false",
                "true" if t["compilation"] else "false",
                "local" if is_local else "cloud", t["file_path"] or "",
                t["persistent_id"], af, ah,
            ])

    # ---- playlists.csv + playlist_tracks.csv + playlists/ folder ----
    track_by_id = {t["persistent_id"]: t for t in tracks}
    name_by_id = {}
    for p in playlists:
        pid = p["persistent_id"]
        if pid != "0000000000000000" and p["name"] and pid not in name_by_id:
            name_by_id[pid] = p["name"]

    playlists_dir = os.path.join(out_dir, "playlists")
    os.makedirs(playlists_dir, exist_ok=True)
    used_filenames = set()
    playlist_files_count = 0

    with open(os.path.join(out_dir, "playlists.csv"), "w", newline="", encoding="utf-8") as f, \
         open(os.path.join(out_dir, "playlist_tracks.csv"), "w", newline="", encoding="utf-8") as g:
        pw = csv.writer(f)
        tw = csv.writer(g)
        pw.writerow(["playlist_index", "name", "type", "parent_folder", "track_count", "persistent_id"])
        tw.writerow(["playlist_index", "playlist_name", "position", "track_persistent_id",
                     "title", "artist", "album", "genre", "year", "duration_sec"])
        for i, p in enumerate(playlists):
            pname = p["name"] or ""
            parent = name_by_id.get(p["parent_id"], "") if p["parent_id"] else ""
            pw.writerow([i, pname, p["type"], parent, p["track_count"], p["persistent_id"]])

            pl_csv_writer = None
            pl_file = None
            if p["track_ids"]:
                base_name = _safe_filename(pname, default=f"playlist_{i}")
                fname = base_name
                counter = 1
                while fname.lower() in used_filenames:
                    fname = f"{base_name}_{counter}"
                    counter += 1
                used_filenames.add(fname.lower())
                pl_file = open(os.path.join(playlists_dir, f"{fname}.csv"), "w", newline="", encoding="utf-8")
                pl_csv_writer = csv.writer(pl_file)
                pl_csv_writer.writerow(["position", "title", "artist", "album", "genre", "year", "duration_sec", "track_persistent_id"])
                playlist_files_count += 1

            try:
                for pos, tid in enumerate(p["track_ids"], 1):
                    tr = track_by_id.get(tid)
                    title = tr["title"] if tr and tr["title"] else ""
                    artist = tr["artist"] if tr and tr["artist"] else ""
                    album = tr["album"] if tr and tr["album"] else ""
                    genre = tr["genre"] if tr and tr["genre"] else ""
                    year = tr["year"] if tr and tr["year"] else ""
                    dur = (tr["duration_ms"] // 1000) if tr and tr["duration_ms"] else ""
                    tw.writerow([i, pname, pos, tid, title, artist, album, genre, year, dur])
                    if pl_csv_writer:
                        pl_csv_writer.writerow([pos, title, artist, album, genre, year, dur, tid])
            finally:
                if pl_file:
                    pl_file.close()

    # ---- albums.csv (derived) ----
    agg = {}
    for t in tracks:
        aa = t["album_artist"] or t["artist"] or ""
        key = (t["album"] or "", aa)
        if key not in agg:
            agg[key] = {"count": 0, "years": Counter(), "comp": False, "art": Counter()}
        a = agg[key]
        a["count"] += 1
        if t["year"]:
            a["years"][t["year"]] += 1
        a["comp"] |= t["compilation"]
        if t["persistent_id"] in am:
            a["art"][am[t["persistent_id"]]] += 1
    albums_with_art = 0
    with open(os.path.join(out_dir, "albums.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["album", "album_artist", "year", "track_count", "compilation_flag",
                    "artwork_file", "artwork_hash"])
        for (album, aa), a in sorted(agg.items(), key=lambda kv: -kv[1]["count"]):
            year = a["years"].most_common(1)[0][0] if a["years"] else ""
            af, ah = a["art"].most_common(1)[0][0] if a["art"] else ("", "")
            albums_with_art += bool(ah)
            w.writerow([album, aa, year, a["count"], "true" if a["comp"] else "false", af, ah])

    return {
        "tracks": len(tracks), "local": local, "cloud": len(tracks) - local,
        "playlists": len(playlists),
        "playlist_entries": sum(len(p["track_ids"]) for p in playlists),
        "playlist_files": playlist_files_count,
        "albums": len(agg), "albums_with_art": albums_with_art,
        "compilations": sum(1 for t in tracks if t["compilation"]),
        "loved": sum(1 for t in tracks if t["like"] == 2),
        "rated": sum(1 for t in tracks if t["rating"]),
        "missing_core": missing_core,
    }
