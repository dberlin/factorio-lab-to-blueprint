"""MD5F: DSP's tweaked MD5.

The authority for these expectations is the game itself: every fixture carries
the hash the game computed, appended after the closing quote.  If our MD5F
reproduces all eleven, it is the game's function.
"""

from __future__ import annotations

import hashlib

import pytest

from flab2bp.dsp.md5f import md5f

from .conftest import fixture_texts


def test_differs_from_standard_md5() -> None:
    """Guards against someone 'fixing' the altered constants back to RFC 1321."""
    data = b"dyson sphere program"
    assert md5f(data) != hashlib.md5(data).hexdigest().upper()


def test_returns_uppercase_hex() -> None:
    digest = md5f(b"")
    assert len(digest) == 32
    assert digest == digest.upper()
    assert all(c in "0123456789ABCDEF" for c in digest)


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_matches_embedded_fixture_hash(name: str, text: str) -> None:
    """The hash covers everything up to but excluding the closing quote."""
    last_quote = text.rindex('"')
    expected = text[last_quote + 1 :].strip().upper()
    assert md5f(text[:last_quote].encode("utf-8")) == expected


def test_multi_block_input() -> None:
    """Exercises the padding path across several 64-byte blocks."""
    for length in (0, 1, 55, 56, 63, 64, 65, 119, 120, 128, 1000):
        assert len(md5f(b"x" * length)) == 32
