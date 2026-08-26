"""Tests for the low-level FactorioLab query-parameter codec.

Every expectation here is traceable to FactorioLab `main`:
`src/state/router/{constants,compression,zip,router-sync}.ts`.
"""

from __future__ import annotations

import zlib
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from flab2bp.lab import params as P


class TestSeparators:
    def test_match_factoriolab_constants(self) -> None:
        # src/state/router/constants.ts
        assert P.ZEMPTY == "_"
        assert P.ZARRAYSEP == "~"
        assert P.ZFIELDSEP == "*"
        assert P.ZTRUE == "1"
        assert P.ZFALSE == "0"

    def test_base64_alphabet(self) -> None:
        # src/state/router/compression.ts ZBASE64ABC
        assert P.ZBASE64ABC == ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.")
        assert len(P.ZBASE64ABC) == 64
        # Positions 0..61 are identical to standard base64; only 62/63 differ.
        assert P.ZBASE64ABC[62:] == "-."


class TestIdCodec:
    """`Compression.nToId` / `idToN` -- base-64 integer ids."""

    @pytest.mark.parametrize(
        ("n", "expected"),
        [
            (0, "A"),
            (1, "B"),
            (25, "Z"),
            (26, "a"),
            (51, "z"),
            (52, "0"),
            (61, "9"),
            (62, "-"),
            (63, "."),
            (64, "BA"),
            (65, "BB"),
            (128, "CA"),
            (4096, "BAA"),
        ],
    )
    def test_n_to_id(self, n: int, expected: str) -> None:
        assert P.n_to_id(n) == expected

    @pytest.mark.parametrize("n", [0, 1, 7, 63, 64, 100, 495, 4095, 4096, 99999])
    def test_round_trip(self, n: int) -> None:
        assert P.id_to_n(P.n_to_id(n)) == n

    def test_id_to_n_known_values(self) -> None:
        assert P.id_to_n("A") == 0
        assert P.id_to_n("BA") == 64
        assert P.id_to_n(".") == 63


class TestBase64:
    def test_translates_standard_base64(self) -> None:
        # 0xFB 0xFF encodes to '+/8=' in standard base64 -> '-.8_' here.
        raw = bytes([0xFB, 0xFF, 0xC0])
        encoded = P.bytes_to_base64(raw)
        assert set(encoded) <= set(P.ZBASE64ABC) | {"_"}
        assert "+" not in encoded and "/" not in encoded and "=" not in encoded
        assert P.base64_to_bytes(encoded) == raw

    @pytest.mark.parametrize("length", [0, 1, 2, 3, 4, 5, 17, 64, 255])
    def test_round_trip(self, length: int) -> None:
        raw = bytes(range(256))[:length]
        assert P.base64_to_bytes(P.bytes_to_base64(raw)) == raw

    def test_padding_uses_underscore(self) -> None:
        assert P.bytes_to_base64(b"a").endswith("__")
        assert P.bytes_to_base64(b"ab").endswith("_")
        assert not P.bytes_to_base64(b"abc").endswith("_")

    def test_rejects_bad_length(self) -> None:
        with pytest.raises(P.LabUrlError):
            P.base64_to_bytes("ABC")

    def test_rejects_misplaced_padding(self) -> None:
        # '_' may only appear in the final two positions.
        with pytest.raises(P.LabUrlError):
            P.base64_to_bytes("A_AAAAAA")


class TestDeflateInflate:
    def test_round_trip(self) -> None:
        text = "o=super-magnetic-ring*60&ibe=conveyor-belt-2&v=11"
        assert P.inflate(P.deflate(text)) == text

    def test_uses_zlib_wrapper_not_raw_deflate(self) -> None:
        """Browser `CompressionStream('deflate')` emits RFC 1950 zlib."""
        raw = P.base64_to_bytes(P.deflate("test=test"))
        assert raw[0] == 0x78  # zlib CMF
        assert zlib.decompress(raw).decode() == "test=test"

    def test_accepts_legacy_query_unsafe_characters(self) -> None:
        """V0 payloads may contain raw '+', '/', '='."""
        payload = P.deflate("test=test")
        legacy = payload.replace("-", "+").replace(".", "/").replace("_", "=")
        assert P.inflate_query_value(legacy) == "test=test"

    @staticmethod
    def _payload_ending_in(suffix: str) -> tuple[str, str]:
        """Find a text whose deflated payload ends in exactly *suffix* padding."""
        for i in range(1, 2000):
            text = f"o=iron-ingot*{i}&v=11"
            payload = P.deflate(text)
            pad = len(payload) - len(payload.rstrip(P.ZEMPTY))
            if pad == len(suffix):
                return text, payload
        raise AssertionError(f"no payload with {len(suffix)} pad char(s) found")

    def test_mends_payload_with_stripped_padding(self) -> None:
        """Chat clients eat the trailing pad; FactorioLab re-appends it."""
        text, payload = self._payload_ending_in("_")
        assert payload.endswith("_")
        assert P.inflate(payload[:-1]) == text

    def test_mends_payload_with_one_of_two_pads_stripped(self) -> None:
        text, payload = self._payload_ending_in("__")
        assert P.inflate(payload[:-1]) == text

    def test_intact_payload_needs_no_mending(self) -> None:
        text, payload = self._payload_ending_in("_")
        assert P.inflate(payload) == text

    def test_raises_on_unrecoverable_payload(self) -> None:
        with pytest.raises(P.LabUrlError):
            P.inflate("....")


class TestToParams:
    def test_splits_key_value_pairs(self) -> None:
        assert P.to_params("a=1&b=2") == {"a": "1", "b": "2"}

    def test_collects_repeated_keys_into_list(self) -> None:
        assert P.to_params("o=a&o=b&o=c") == {"o": ["a", "b", "c"]}

    def test_pre_v11_hashed_form_without_delimiter(self) -> None:
        """`RouterSync.toParams`: if any section lacks '=', key is first char."""
        assert P.to_params("pAAA&qBBB") == {"p": "AAA", "q": "BBB"}

    def test_to_string_round_trip(self) -> None:
        params = {"o": ["a", "b"], "v": "11"}
        assert P.to_params(P.to_string(params)) == params

    def test_to_string_accepts_general_string_sequences(self) -> None:
        assert P.to_string({"o": ("a", "b"), "v": "11"}) == "o=a&o=b&v=11"

    def test_to_string_drops_empty_values(self) -> None:
        assert P.to_string({"a": "1", "b": "", "c": None}) == "a=1"


class TestFieldParsers:
    def test_zip_fields_strips_trailing_separators(self) -> None:
        assert P.zip_fields(["a", "b", "", ""]) == "a*b"
        assert P.zip_fields(["a", "", "b"]) == "a**b"

    def test_parse_string(self) -> None:
        assert P.parse_string("iron") == "iron"
        assert P.parse_string(P.ZEMPTY) == ""
        assert P.parse_string("") is None
        assert P.parse_string(None) is None

    def test_parse_bool(self) -> None:
        assert P.parse_bool(P.ZTRUE) is True
        assert P.parse_bool(P.ZFALSE) is False
        assert P.parse_bool("") is None
        assert P.parse_bool(None) is None

    def test_parse_number(self) -> None:
        assert P.parse_number("0") == 0
        assert P.parse_number("3") == 3
        assert P.parse_number("") is None

    def test_parse_rational_exact(self) -> None:
        assert P.parse_rational("60") == Fraction(60)
        assert P.parse_rational("1/3") == Fraction(1, 3)
        assert P.parse_rational("1.5") == Fraction(3, 2)
        assert P.parse_rational("") is None

    def test_parse_array(self) -> None:
        assert P.parse_array("a~b~c") == ["a", "b", "c"]
        assert P.parse_array(P.ZEMPTY) == []
        assert P.parse_array("") is None

    def test_parse_indices(self) -> None:
        arr = [{"id": "x"}, {"id": "y"}]

        def empty_entry() -> dict[str, str]:
            return {}

        assert P.parse_indices("0~1", arr, empty=empty_entry) == [
            {"id": "x"},
            {"id": "y"},
        ]
        assert P.parse_indices(P.ZEMPTY, arr, empty=empty_entry) == []
        assert P.parse_indices("", arr, empty=empty_entry) is None

    def test_parse_indices_out_of_range_yields_empty_entry(self) -> None:
        def empty_entry() -> dict[str, str]:
            return {}

        assert P.parse_indices("5", [{"id": "x"}], empty=empty_entry) == [{}]


class TestParseSubset:
    """`Zip.parseSubset` -- ranges of base-64 indices into a ModHash array."""

    HASH = ["a", "b", "c", "d", "e", "f"]

    def test_single_index(self) -> None:
        assert P.parse_subset("A", self.HASH) == {"a"}

    def test_inclusive_range(self) -> None:
        # 'A'..'C' -> indices 0..2 inclusive
        assert P.parse_subset("A~C", self.HASH) == {"a", "b", "c"}

    def test_multiple_ranges_joined_by_fieldsep(self) -> None:
        assert P.parse_subset("A*E", self.HASH) == {"a", "e"}
        assert P.parse_subset("A~B*E~F", self.HASH) == {"a", "b", "e", "f"}

    def test_empty_marker_is_empty_set(self) -> None:
        assert P.parse_subset(P.ZEMPTY, self.HASH) == set()

    def test_absent_is_none(self) -> None:
        assert P.parse_subset("", self.HASH) is None
        assert P.parse_subset(None, self.HASH) is None

    def test_skips_null_holes(self) -> None:
        assert P.parse_subset("A~C", ["a", None, "c"]) == {"a", "c"}


class TestNStringParsers:
    HASH = ["alpha", "beta", "gamma"]

    def test_parse_n_string(self) -> None:
        assert P.parse_n_string("A", self.HASH) == "alpha"
        assert P.parse_n_string("C", self.HASH) == "gamma"
        assert P.parse_n_string(P.ZEMPTY, self.HASH) == ""

    def test_parse_n_array(self) -> None:
        assert P.parse_n_array("A~C", self.HASH) == ["alpha", "gamma"]

    def test_out_of_range_is_dropped(self) -> None:
        assert P.parse_n_array("A~z", self.HASH) == ["alpha"]


class TestModHash:
    def test_loads_vendored_dsp_hash(self) -> None:
        mh = P.load_mod_hash("dsp")
        assert mh.items[0] == "holo-beacon"
        assert mh.belts[:3] == ["conveyor-belt-1", "conveyor-belt-2", "conveyor-belt-3"]
        assert "assembling-machine-2" in mh.machines
        assert "proliferator-1-products" in mh.modules
        assert len(mh.recipes) > 400

    def test_holes_are_preserved_as_none(self) -> None:
        """Index positions matter, so JSON nulls must not be filtered out."""
        mh = P.load_mod_hash("dsp")
        assert mh.items[2] is None

    def test_validates_raw_hash_shape(self, tmp_path: Path) -> None:
        source = tmp_path / "hash.json"
        source.write_text('{"items": ["iron-ingot", 7]}')

        with pytest.raises(ValidationError):
            P.load_mod_hash(path=source)

    def test_unknown_mod_raises(self) -> None:
        with pytest.raises(P.LabUrlError):
            P.load_mod_hash("no-such-mod")
