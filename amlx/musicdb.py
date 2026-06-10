"""
Parser for Apple Music's ``Library.musicdb`` (the proprietary ``hfma`` format).

Pipeline: read the unencrypted 160-byte header, AES-128-ECB decrypt the first
``maxCryptSize`` bytes of the payload, append the unencrypted tail, zlib-inflate
the whole thing, then walk the inner ``hsma/itma/boma/lpma`` section tree.

All field offsets below were reverse-engineered and verified against a real
Windows Apple Music library (app v1.1540.23042.0, db version 1.6.4.90), and
cross-checked against the documentation referenced in docs/FORMAT.md. The decryption key is supplied by the caller at runtime; this code reads metadata only.
"""

import struct
import zlib
import datetime
from urllib.parse import unquote

from .aes import decrypt_ecb

# The 16-byte AES key for the hfma payload (supplied at runtime).
MUSICDB_AES_KEY = b"SUPPLY-KEY-AT-RUNTIME"

# Apple timestamps are seconds since 1904-01-01 00:00:00 UTC.
_APPLE_EPOCH = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)


def _apple_date(ts):
    if not ts:
        return None
    try:
        return _APPLE_EPOCH + datetime.timedelta(seconds=int(ts))
    except (OverflowError, ValueError):
        return None


class _Buf:
    """Little-endian reader over the decompressed payload."""

    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d

    def u16(self, o):
        return struct.unpack_from("<H", self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from("<I", self.d, o)[0]

    def i32(self, o):
        return struct.unpack_from("<i", self.d, o)[0]

    def u64(self, o):
        return struct.unpack_from("<Q", self.d, o)[0]

    def utf16(self, o, n):
        try:
            return self.d[o:o + n].decode("utf-16-le").rstrip("\x00") or None
        except UnicodeDecodeError:
            return None


def decrypt_and_inflate(raw):
    """Take the raw .musicdb file bytes, return the decompressed payload."""
    if raw[:4] != b"hfma":
        raise ValueError("not an hfma file (bad signature)")
    envelope = struct.unpack_from("<I", raw, 4)[0]
    max_crypt = struct.unpack_from("<I", raw, 84)[0]
    payload = raw[envelope:]
    crypt = max_crypt if 0 < max_crypt < len(payload) else (len(payload) // 16) * 16
    crypt -= crypt % 16
    decrypted = decrypt_ecb(payload[:crypt], MUSICDB_AES_KEY)
    return zlib.decompressobj().decompress(decrypted + payload[crypt:])


def _read_widechar_string(b, pos):
    """A 'boma' string atom: UTF-16LE payload begins 20 bytes after atom start."""
    length = b.u32(pos + 16 + 8)        # length field sits at dataStart+8
    if 0 < length < 1_000_000:
        return b.utf16(pos + 36, length)
    return None


def _read_file_url(b, pos, end):
    """boma 0x000B: a file:// URL (UTF-8). Returns a filesystem-ish path."""
    length = b.u32(pos + 16 + 8)
    start = pos + 16 + 20
    if not (0 < length < 4096) or start + length > end:
        return None
    try:
        url = b.d[start:start + length].decode("utf-8")
    except UnicodeDecodeError:
        return None
    url = unquote(url)
    if url.startswith("file:///"):
        url = "/" + url[8:]
    return url


def parse(payload):
    """Walk the decompressed section tree. Returns a dict with header/tracks/playlists."""
    b = _Buf(payload)
    n = len(payload)

    header = {}
    if payload[:4] == b"hfma" or True:
        # The decompressed stream opens with 'hsma' sections; the library-level
        # header values we care about (version string) live in the file header,
        # which the caller passes separately. Nothing to read here.
        pass

    tracks = {}          # persistent_id -> dict
    track_order = []
    playlists = []       # list of dicts (order preserved)
    library_id = 0

    cur = None           # 'track' | 'album' | 'artist' | 'playlist' | None
    t = None             # current track dict
    pl = None            # current playlist dict

    pos = 0
    while pos < n - 8:
        sig = payload[pos:pos + 4]
        if sig == b"\x00\x00\x00\x00":
            break

        if sig == b"boma":
            size = b.u32(pos + 8)
            sub = b.u32(pos + 12)
            nxt = pos + size
            if cur == "track" and t is not None:
                _boma_track(b, pos, nxt, sub, t)
            elif cur == "playlist" and pl is not None:
                _boma_playlist(b, pos, sub, pl)
        else:
            size = b.u32(pos + 4)
            nxt = pos + size
            if sig in (b"lama", b"lAma", b"lPma", b"ltma"):
                cur, t, pl = None, None, None
            elif sig == b"iama":
                cur, t, pl = "album", None, None
            elif sig == b"iAma":
                cur, t, pl = "artist", None, None
            elif sig == b"lpma":
                cur, t = "playlist", None
                pl = _parse_playlist(b, pos, size, library_id)
                playlists.append(pl)
            elif sig == b"itma":
                cur, pl = "track", None
                tid = b.u64(pos + 16)
                t = tracks.get(tid)
                if t is None:
                    t = _new_track(tid)
                    tracks[tid] = t
                    track_order.append(tid)
                _parse_track_fixed(b, pos, size, t)
            elif sig == b"hfma":
                library_id = b.u64(pos + 28) if size >= 36 else 0

        if nxt <= pos:
            break
        pos = nxt

    return {
        "library_id": library_id,
        "tracks": [tracks[i] for i in track_order],
        "playlists": playlists,
    }


def _new_track(tid):
    return {
        "persistent_id": "%016X" % tid, "title": None, "artist": None, "album": None,
        "album_artist": None, "genre": None, "composer": None, "comment": None,
        "kind": None, "year": None, "track_number": None, "duration_ms": None,
        "bit_rate": None, "play_count": 0, "date_added": None, "date_modified": None,
        "last_played": None, "rating": None, "like": 0, "compilation": False,
        "file_path": None,
    }


def _parse_track_fixed(b, pos, size, t):
    """Direct itma fields read at fixed byte offsets from the section start."""
    if size >= 39:
        t["compilation"] = b.d[pos + 38] == 1
    if size >= 63:
        like = b.d[pos + 62]
        if 0 <= like <= 3:
            t["like"] = like
    if size >= 66:
        r = b.d[pos + 65]
        if 0 < r <= 100:
            t["rating"] = r
    if size >= 172:
        tn = b.u16(pos + 160)
        if 0 < tn < 10000:
            t["track_number"] = tn
        year = b.i32(pos + 168)
        if 1900 < year < 2100:
            t["year"] = year


def _boma_track(b, pos, end, sub, t):
    STRINGS = {
        0x02: "title", 0x03: "album", 0x04: "artist", 0x05: "genre",
        0x06: "kind", 0x08: "comment", 0x0C: "composer", 0x1B: "album_artist",
    }
    if sub in STRINGS:
        v = _read_widechar_string(b, pos)
        if v is not None:
            t[STRINGS[sub]] = v
    elif sub == 0x01:                       # numeric block (fixed offsets)
        if end - pos >= 180:
            t["bit_rate"] = b.u32(pos + 108)
            t["date_added"] = _apple_date(b.u32(pos + 112))
            t["date_modified"] = _apple_date(b.u32(pos + 148))
            t["duration_ms"] = b.u32(pos + 176)
    elif sub == 0x17:                       # play statistics (72 bytes)
        if end - pos >= 36:
            t["last_played"] = _apple_date(b.u32(pos + 28))
            t["play_count"] = b.u32(pos + 32)
    elif sub == 0x0B:                       # local file URL
        url = _read_file_url(b, pos, end)
        if url:
            t["file_path"] = url


def _parse_playlist(b, pos, size, library_id):
    track_count = b.i32(pos + 16) if size >= 20 else 0
    playlist_id = b.u64(pos + 30) if size >= 38 else 0
    parent_id = 0
    if size >= 58:
        parent_id = b.u64(pos + 50)
        if parent_id == library_id:
            parent_id = 0
    dist_kind = 0
    if size >= 82:
        dist_kind = b.d[pos + (79 if parent_id == 0 else 80)]
    if track_count == 0 and dist_kind == 0:
        ptype = "folder"
    elif dist_kind != 0:
        ptype = "system"
    else:
        ptype = "normal"
    pl = {
        "persistent_id": "%016X" % playlist_id, "name": None, "type": ptype,
        "parent_id": "%016X" % parent_id if parent_id else "",
        "track_count": track_count, "track_ids": [], "_smart": False,
    }
    if size >= 26:
        pl["created_at"] = _apple_date(b.u32(pos + 22))
    if size >= 142:
        pl["modified_at"] = _apple_date(b.u32(pos + 138))
    return pl


def _boma_playlist(b, pos, sub, pl):
    if sub == 0xC8:                                     # playlist name
        v = _read_widechar_string(b, pos)
        if v is not None:
            pl["name"] = v
    elif sub == 0xC9:                                   # smart criteria present
        pl["_smart"] = True
        if pl["type"] == "normal":
            pl["type"] = "smart"
    elif sub == 0xCE:                                   # ipfa: one ordered track ref
        if b.d[pos + 20:pos + 24] == b"ipfa":
            tid = b.u64(pos + 40)
            if tid:
                pl["track_ids"].append("%016X" % tid)
