"""
amlx — Apple Music (Windows) library metadata exporter.

Standard-library only. Reads your locally-cached Apple Music library database,
decrypts and parses it, and writes your full library metadata + cover art to CSV.
"""

__version__ = "1.0.0"

from .musicdb import decrypt_and_inflate, parse, MUSICDB_AES_KEY

__all__ = ["decrypt_and_inflate", "parse", "MUSICDB_AES_KEY", "__version__"]
