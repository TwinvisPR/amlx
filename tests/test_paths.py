"""
Verify the Windows library auto-detection without needing a Windows machine.

We can't run native Windows here, but Python's ``ntpath`` module *is* the exact
path engine Python uses on Windows, and it runs on any OS. So we swap it in,
fake the Windows environment variables and a Windows filesystem layout, and
assert that ``resolve_library`` builds the right ``C:\\Users\\...`` paths and
picks the newest valid library.

Run:  python tests/test_paths.py   (or)   python -m pytest tests/
"""

import os
import sys
import ntpath
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import extract  # noqa: E402

WIN_ENV = {
    "USERPROFILE": r"C:\Users\TestUser",
    "LOCALAPPDATA": r"C:\Users\TestUser\AppData\Local",
}
EXPECTED_DEFAULT = r"C:\Users\TestUser\Music\Apple Music\Apple Music Library.musiclibrary"
EXPECTED_UWP = (r"C:\Users\TestUser\AppData\Local\Packages"
                r"\AppleInc.AppleMusicWin_nzyj5cx40ttqa\LocalState")


def _fake_glob(pattern):
    # Emulate the UWP package directory existing on a Windows box.
    if "AppleInc.AppleMusicWin_" in pattern and "Packages" in pattern:
        return [EXPECTED_UWP]
    return []


def test_windows_candidate_paths():
    with mock.patch.object(extract.os, "path", ntpath), \
         mock.patch.dict(os.environ, WIN_ENV, clear=True), \
         mock.patch.object(extract.glob, "glob", _fake_glob):
        cands = extract._candidate_dirs()
    assert EXPECTED_DEFAULT in cands, f"default Music path missing; got {cands}"
    assert EXPECTED_UWP in cands, f"UWP LocalState path missing; got {cands}"


def test_windows_resolution_picks_newest():
    """Two candidate libraries exist; the newer Library.musicdb must win."""
    default_db = ntpath.join(EXPECTED_DEFAULT, "Library.musicdb")
    uwp_db = ntpath.join(EXPECTED_UWP, "Library.musicdb")
    mtimes = {default_db: 2000.0, uwp_db: 1000.0}      # default bundle is newer

    with mock.patch.object(extract.os, "path", ntpath), \
         mock.patch.dict(os.environ, WIN_ENV, clear=True), \
         mock.patch.object(extract.glob, "glob", _fake_glob), \
         mock.patch.object(ntpath, "isfile", lambda p: p in mtimes), \
         mock.patch.object(ntpath, "getmtime", lambda p: mtimes[p]):
        lib_dir, db = extract.resolve_library(None)

    assert db == default_db, f"expected newest db {default_db}, got {db}"
    assert lib_dir == EXPECTED_DEFAULT


def test_explicit_library_arg_file_and_dir():
    """--library accepts either a .musiclibrary dir or a direct .musicdb file."""
    bundle = r"D:\stuff\My Library.musiclibrary"
    db = ntpath.join(bundle, "Library.musicdb")
    with mock.patch.object(extract.os, "path", ntpath), \
         mock.patch.object(ntpath, "isfile", lambda p: p in (db,)), \
         mock.patch.object(ntpath, "isdir", lambda p: p == bundle):
        assert extract.resolve_library(db) == (bundle, db)            # file given
        assert extract.resolve_library(bundle) == (bundle, db)        # dir given


if __name__ == "__main__":
    test_windows_candidate_paths()
    test_windows_resolution_picks_newest()
    test_explicit_library_arg_file_and_dir()
    print("Windows path-resolution tests passed.")
