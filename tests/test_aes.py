"""AES-128 correctness — FIPS-197 Appendix B / C.1 known-answer vector.

Run:  python tests/test_aes.py   (or)   python -m pytest tests/
Passing this means the vendored AES is correct without needing OpenSSL.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from amlx.aes import decrypt_ecb


def test_fips197_vector():
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
    ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert decrypt_ecb(ciphertext, key) == plaintext


def test_multiblock_roundlength():
    # two identical ECB blocks decrypt independently and deterministically
    ct = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a") * 2
    out = decrypt_ecb(ct, bytes.fromhex("000102030405060708090a0b0c0d0e0f"))
    assert len(out) == 32 and out[:16] == out[16:]


if __name__ == "__main__":
    test_fips197_vector()
    test_multiblock_roundlength()
    print("AES known-answer tests passed.")
