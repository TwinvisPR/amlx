# Apple Music Library Exporter (Windows)

**Get your Apple Music library out of the app — every track, playlist, love, play count, and cover image — as plain CSV files. One command, no dependencies.**

The new **Apple Music app for Windows** (Microsoft Store / UWP) has no export feature, and Apple's
*Download your data* (privacy.apple.com) only includes songs you *purchased* — **not** the songs you
*added* from the catalog. So your real library, the thousands of tracks you've curated over years,
is locked inside the app. If your subscription lapses or the app loses sync, that curation is gone.

This tool reads the library database that the app already keeps **on your own machine** and exports
it to spreadsheet-friendly CSV. It's **metadata only** — song names, albums, artists, playlists,
ratings, play counts, and the cover-art thumbnails already cached locally. **No audio is ever
touched, and no DRM is involved.** You're saving the *names* of music you already pay to listen to.

## What you get

| File | What's in it |
|------|--------------|
| `tracks.csv` | Every track: title, artist, album, album_artist, genre, year, track #, duration, date added, last played, play count, star rating, favorite (love), compilation flag, cloud/local, file path, persistent ID, **cover art file + hash** |
| `playlists.csv` | Every playlist: name, type (normal / smart / folder / system), parent folder, track count, persistent ID |
| `playlist_tracks.csv` | The **ordered** contents of every playlist (playlist → position → track persistent ID) |
| `albums.csv` | Unique albums derived from your tracks: album, album_artist, year, track count, compilation flag, cover art |
| `artwork/` | Cover images (600×600 where available), **de-duplicated by SHA-256** so shared covers are stored once |

## Providing the key (required, one-time)

The database is encrypted with a 16-character AES key, which you supply at runtime — it is not
stored in this repository. Give it to the tool any one of these ways:

- create a file **`key.txt`** next to `extract.py` containing just the key, **or**
- set the **`MUSICDB_AES_KEY`** environment variable, **or**
- a **`.env`** file next to `extract.py` with `MUSICDB_AES_KEY=...` (copy `.env.example`), **or**
- pass `--key <thekey>` on the command line.

`key.txt` and `.env` are git-ignored, so your key never ends up committed. The same key works for
every Apple Music library — it is not tied to your account.

## Usage

### No Python? Just double-click `run.bat` (Windows)

If you don't have Python installed, run **`run.bat`**. It uses Python if you have it, otherwise it
downloads a small **portable** Python (~11 MB, no install, no admin rights) into a local `.python`
folder and runs the export. Pass options after it, e.g. `run.bat --cdn-fallback`. Delete the
`.python` folder afterward to remove every trace.

### With Python (any OS)

Requires **Python 3.7+** — and nothing else. No `pip install`, no .NET, no OpenSSL.

```bash
git clone <this-repo>
cd apple-music-library-exporter
python extract.py
```

That auto-detects your library and writes everything to `./output/`. Options:

```bash
python extract.py --out my_export             # choose the output folder
python extract.py --library "D:\Music\Apple Music\Apple Music Library.musiclibrary"
python extract.py --no-artwork                # metadata only, skip covers
python extract.py --cdn-fallback              # fetch the few covers missing from the
                                              # local cache via Apple's public catalog
```

The tool **never modifies your library** — it works on a temporary copy of the database.

### Where the library lives

It's auto-detected from the usual spots:
- `%USERPROFILE%\Music\Apple Music\Apple Music Library.musiclibrary\` (default)
- `%LOCALAPPDATA%\Packages\AppleInc.AppleMusicWin_*\LocalState\`
- (WSL users: the same paths under `/mnt/c/Users/...`)

If you moved your media folder, pass `--library` with the path to your `.musiclibrary` bundle.

## Verify nothing was dropped

Two checks confirm completeness:

1. **Automatic** — the tool reads the track/playlist counts the library *declares about itself* in
   its header and cross-checks them against what was extracted. You'll see `OK` (or a `WARNING` if
   they ever disagree). Verified to match across Apple Music for Windows and macOS Monterey/Sequoia
   library versions.
2. **Manual** — compare the printed track count to the **Songs** total in the Apple Music app. They
   should match (the Songs view can be slightly lower because it excludes music videos, which the
   database still stores as tracks).

## How it works

`Library.musicdb` is Apple's proprietary `hfma` format: a small clear-text header, then an
AES-128-ECB-encrypted, zlib-compressed payload of `hsma`/`itma`/`boma`/`lpma` sections. The tool
decrypts it (using the key you supply), inflates it, and walks the section tree. See [`docs/FORMAT.md`](docs/FORMAT.md) for the full byte
layout. The AES implementation is pure-Python and checked against the FIPS-197 test vector
(`python tests/test_aes.py`).

## Credits

Format reverse-engineering builds on **Gary Vollink's** musicdb notes
(<https://home.vollink.com/gary/playlister/musicdb.html>) and the
**pitetb/AppMusicLibParser** project. This repo reimplements the read path in dependency-free
Python and adds artwork export and the standardized CSV schema.

## License

MIT — see [`LICENSE`](LICENSE).
