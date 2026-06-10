# `Library.musicdb` format notes (Apple Music for Windows)

Reverse-engineered and verified against Apple Music for Windows **v1.1540.23042.0**,
database version string **1.6.4.90**. Offsets are little-endian byte offsets unless noted.
These notes match what `amlx/musicdb.py` implements.

## 1. File envelope (`hfma`)

| Offset | Type | Field |
|-------:|------|-------|
| 0 | char[4] | `"hfma"` signature |
| 4 | u32 | envelope length (header size, typically **160**) |
| 8 | u32 | total file size |
| 16 | char[32] | version string (e.g. `1.6.4.90`), NUL-terminated |
| 28 | u64 | library persistent ID |
| 84 | u32 | `maxCryptSize` (bytes of the payload that are encrypted, typically **102400**) |

**Payload** = bytes from `envelope` to EOF. The first `maxCryptSize` bytes (rounded down to a
16-byte multiple) are **AES-128-ECB** encrypted; the remainder is clear. Concatenate
`decrypt(payload[:crypt]) + payload[crypt:]` and **zlib-inflate** to get the section tree.

- **AES key** (16 ASCII bytes): `SUPPLY-KEY-AT-RUNTIME` — supplied at runtime.
- **Dates**: u32 seconds since **1904-01-01 00:00:00 UTC**.

## 2. Section tree

Decompressed data is a flat stream of sections. Each non-`boma` section: `char[4]` signature +
`u32` size; advance by `size`. `boma` sections: signature + `u32` marker (`0x14`) + `u32` size +
`u32` subtype, then data; advance by `size`.

| Sig | Meaning | Context effect |
|-----|---------|----------------|
| `hsma` | container/header section | (skipped generically) |
| `ltma` / `itma` | track list / **track item** | `itma` starts a track |
| `lama` / `iama` | album list / album item | `iama` starts an album |
| `lAma` / `iAma` | artist list / artist item | `iAma` starts an artist |
| `lPma` / `lpma` | playlist list / **playlist** | `lpma` starts a playlist |
| `boma` | a metadata atom attached to the current item | — |

A `boma` belongs to whatever item (`itma`/`iama`/`iAma`/`lpma`) most recently opened; list
headers (`ltma`/`lama`/`lAma`/`lPma`) reset the current item.

## 3. `itma` track — direct fields (offset from section start)

| Offset | Type | Field |
|-------:|------|-------|
| 16 | u64 | persistent ID |
| 38 | u8  | **compilation flag** (1 = part of a compilation) — found empirically for this variant |
| 62 | u8  | like status (0 none, 2 loved, 3 disliked) |
| 65 | u8  | star rating (0–100, ÷20 = stars) |
| 160 | u16 | track number |
| 168 | i32 | year |
| 172 | u64 | album reference ID |
| 180 | u64 | artist reference ID |

## 4. `boma` subtypes

**Strings** (UTF-16LE; payload begins 20 bytes after the atom start, length is the u32 at
dataStart+8): `0x02` title, `0x03` album, `0x04` artist, `0x05` genre, `0x06` kind, `0x08`
comment, `0x0C` composer, `0x1B` album artist (also `0x1E–0x22` sort fields).

**`0x01` numeric block** (fixed offsets from atom start): `+108` u32 bitrate, `+112` u32 date
added, `+148` u32 date modified, `+176` u32 duration (ms), `+316` u32 file size.

**`0x17` play statistics** (from atom start): `+28` u32 last-played date, `+32` u32 play count.

**`0x0B` file URL**: UTF-8 `file://` URL at dataStart+20 (present only for locally-imported
files; absent for cloud/added tracks).

**Album items (`iama`)**: `0x12C` album title, `0x12D` album artist, `0x12E` artist.

## 5. `lpma` playlist (offset from section start)

| Offset | Type | Field |
|-------:|------|-------|
| 16 | i32 | track count |
| 30 | u64 | playlist persistent ID |
| 50 | u64 | parent ID (== library ID means "root", treated as none) |
| 79 or 80 | u8 | distinguished kind (79 if no parent, else 80) |
| 22 | u32 | created date |
| 138 | u32 | modified date |

Type: `folder` if track_count==0 and distinguished_kind==0; `system` if distinguished_kind!=0;
`smart` if a `0x00C9` (smart criteria) boma is present; else `normal`. Name comes from a
`0x00C8` boma.

**Ordered tracks**: each `0x00CE` boma contains an `ipfa` record; the track persistent ID is the
u64 at offset **40** of the atom. Their order in the stream is the playlist order.

## 6. Artwork (`artwork.sqlite` + `artwork/`)

SQLite cache index (no audio, just thumbnails):
- `item_to_artwork(item_id INTEGER, artwork_id TEXT)` — `item_id` is the **signed** int64 of the
  track persistent ID (mask with `0xFFFFFFFFFFFFFFFF` and format as 16-hex to join `tracks.csv`).
- `cache_items(artwork_id, size_kind, extension, image_hash, width, height, status)`.
- `artwork_source(artwork_id, location)` — an mzstatic CDN URL or relative path.

Cached image files live in `artwork/{artwork_id}_sk{size_kind}.{ext}` (plain JPEG/PNG). Some
builds wrap images, so carve from the first JPEG (`FF D8 FF`) or PNG (`89 50 4E 47`) magic.

## Credits

Gary Vollink's musicdb notes (<https://home.vollink.com/gary/playlister/musicdb.html>) and
pitetb/AppMusicLibParser. The compilation-flag offset (itma +38) was determined here by
correlating candidate flag bytes with known compilation albums.
