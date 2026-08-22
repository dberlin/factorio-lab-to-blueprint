"""The acceptance test for the whole codec.

If ``encode(decode(x)) == x`` for real blueprints the game produced -- byte for
byte, hash included -- then our writer emits exactly what the game emits.  That
is a far stronger claim than "our reader agrees with our writer", which any two
mutually consistent bugs would also satisfy.
"""

from __future__ import annotations

import pytest

from flab2bp.dsp.codec import decode, encode_blueprint
from flab2bp.dsp.envelope import BlueprintFormatError

from .conftest import DYSON_FIXTURE, fixture_text, fixture_texts


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_roundtrip_is_byte_identical(name: str, text: str) -> None:
    assert encode_blueprint(decode(text)) == text


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_decoded_hash_validates(name: str, text: str) -> None:
    assert decode(text).hash_valid


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_decode_reports_plausible_contents(name: str, text: str) -> None:
    bp = decode(text)
    assert bp.buildings, "every fixture has at least one building"
    assert len(bp.areas) >= 1
    # Building indices are what connection fields reference; they must be unique.
    indices = [b.index for b in bp.buildings]
    assert len(set(indices)) == len(indices)


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_connection_targets_resolve(name: str, text: str) -> None:
    """Every non-null connection names a building that exists."""
    bp = decode(text)
    known = {b.index for b in bp.buildings}
    for b in bp.buildings:
        for ref in (b.output_obj_idx, b.input_obj_idx):
            assert ref < 0 or ref in known


@pytest.mark.parametrize("name,text", fixture_texts(include_dyson=False))
def test_timestamp_is_exact(name: str, text: str) -> None:
    """.NET tick counts exceed float precision; they must be parsed as ints."""
    cells = text[len("BLUEPRINT:") : text.index('"')].split(",")
    assert decode(text).header.timestamp == int(cells[8])


def test_dyson_blueprint_is_rejected() -> None:
    with pytest.raises(BlueprintFormatError, match="Dyson sphere"):
        decode(fixture_text(DYSON_FIXTURE))


def test_non_blueprint_is_rejected() -> None:
    with pytest.raises(BlueprintFormatError, match="BLUEPRINT:"):
        decode("not a blueprint at all")


def test_truncated_payload_is_rejected() -> None:
    with pytest.raises(BlueprintFormatError):
        decode('BLUEPRINT:0,10,0,0,0,0,0,0,0,0.10.34,x,y"not-base64!!"DEADBEEF')
