"""Deterministic CBOR codec — RFC 8949 Section 4.2.1 core rules.

Falsification target: an encoder that produces two different byte strings for
the same value, or a decoder that accepts a non-canonical encoding and
re-canonicalizes it. Either breaks byte-for-byte cross-language agreement, which
is the entire point of the format.
"""
import pytest

from aletheia.provenance import cbor


# --- R3: map key ordering -------------------------------------------------- #
def test_map_key_order_is_by_encoded_bytes_not_by_string():
    """Length dominates for short text keys, because the head byte carries it.

    Sorting the Python strings instead of the encodings is the most common way
    to get RFC 8949 4.2.1 wrong: it would put "cls" before "v".
    """
    encoded = cbor.encode({"cls": 3, "id": 1, "v": 1, "conf": 2})
    # 0xa4 = map(4), then "v", "id", "cls", "conf" in that order
    assert encoded.hex() == "a46176016269640163636c730364636f6e6602"
    # positions confirm the ordering independently of the literal above
    assert encoded.index(b"v") < encoded.index(b"id") < encoded.index(b"cls")


def test_input_order_does_not_affect_output():
    a = cbor.encode({"conf": 2, "v": 1, "id": 1, "cls": 3})
    b = cbor.encode({"cls": 3, "id": 1, "v": 1, "conf": 2})
    assert a == b


def test_decoder_rejects_out_of_order_map_keys():
    # {"id": 1, "v": 1} written in the wrong order
    bad = bytes.fromhex("a262696401617601")
    with pytest.raises(cbor.CBORError, match="deterministic order"):
        cbor.decode(bad)


def test_decoder_rejects_duplicate_map_keys():
    with pytest.raises(cbor.CBORError, match="duplicate"):
        cbor.decode(bytes.fromhex("a2617601617602"))


# --- R1/R2: definite length, shortest form --------------------------------- #
@pytest.mark.parametrize("hexstr,why", [
    ("9f01ff", "indefinite array"),
    ("bf616101ff", "indefinite map"),
    ("1817", "23 in a 1-byte argument"),
    ("1900ff", "255 in a 2-byte argument"),
    ("1a0000ffff", "65535 in a 4-byte argument"),
    ("1b00000000ffffffff", "u32max in an 8-byte argument"),
])
def test_decoder_rejects_non_shortest_and_indefinite(hexstr, why):
    with pytest.raises(cbor.CBORError):
        cbor.decode(bytes.fromhex(hexstr))


@pytest.mark.parametrize("value,expected", [
    (0, "00"), (23, "17"), (24, "1818"), (255, "18ff"),
    (256, "190100"), (65535, "19ffff"), (65536, "1a00010000"),
    (4294967295, "1affffffff"), (4294967296, "1b0000000100000000"),
    (-1, "20"),
])
def test_shortest_form_boundaries(value, expected):
    assert cbor.encode(value).hex() == expected


# --- R6: no floats --------------------------------------------------------- #
def test_encoder_refuses_floats():
    with pytest.raises(cbor.CBORError, match="floats are not permitted"):
        cbor.encode({"v": 0.92})


def test_encoder_refuses_nan_and_inf():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(cbor.CBORError):
            cbor.encode(bad)


@pytest.mark.parametrize("hexstr", ["f93c00", "fa3f800000", "fb3ff0000000000000"])
def test_decoder_rejects_float_encodings(hexstr):
    with pytest.raises(cbor.CBORError, match="floating-point"):
        cbor.decode(bytes.fromhex(hexstr))


# --- subset restrictions --------------------------------------------------- #
def test_decoder_rejects_tags():
    with pytest.raises(cbor.CBORError, match="tags"):
        cbor.decode(bytes.fromhex("c07818323032362d30382d32335430303a30303a30305a"))


def test_decoder_rejects_trailing_bytes():
    with pytest.raises(cbor.CBORError, match="trailing"):
        cbor.decode(bytes.fromhex("0101"))


def test_encoder_refuses_oversize_integers():
    with pytest.raises(cbor.CBORError):
        cbor.encode(1 << 64)


# --- round trip ------------------------------------------------------------ #
@pytest.mark.parametrize("value", [
    0, 1, -1, (1 << 64) - 1, True, False, None, b"", b"\x00\xff",
    "", "Café — Mañana", "🛰", [], {}, [1, [2, {"b": None}]],
    {"a": [1, 2], "zz": {"q": b"\x01"}}, "z" * 300, bytes(range(256)),
])
def test_round_trip_is_exact(value):
    assert cbor.decode(cbor.encode(value)) == value


def test_encoding_is_canonical_under_round_trip():
    """encode(decode(x)) == x for every accepted x: the decoder never accepts
    a form its own encoder would not produce."""
    for value in [{"b": 1, "a": 2}, [1, "x", None], {"k": b"\x00" * 40}]:
        data = cbor.encode(value)
        assert cbor.encode(cbor.decode(data)) == data
