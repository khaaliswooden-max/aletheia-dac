"""
cbor.py — deterministic CBOR codec for the zil-provenance wire format.

Implements RFC 8949 Section 4.2.1 "Core Deterministic Encoding Requirements",
restricted to the subset the portfolio's signed structures need. Stdlib only:
this module must stay importable on any machine with a bare Python, because it
is the one piece every substrate — including the zero-dependency CLI — shares.

Purpose
    Produce, from a Python value, exactly one byte string, such that an
    independent implementation in Rust or embedded C produces the same bytes.

Inputs
    Python int, bytes, str, list/tuple, dict, bool, None.

Outputs
    ``bytes`` (encode) or the corresponding Python value (decode).

Precondition
    The value contains no float, no tag, and no integer outside
    [-2**64, 2**64 - 1]. Map keys are hashable and encodable.

Postcondition
    ``decode(encode(v)) == v`` for every accepted ``v``, and ``encode`` is
    injective on accepted values. ``decode`` rejects any byte string that is not
    the deterministic encoding of its own value — it never accepts a
    non-canonical form and silently re-canonicalizes it.

VERIFIED: round-trip and rejection behaviour are covered by
tests/test_provenance_cbor.py.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# The five deterministic-encoding rules, restated (see docs/WIRE_FORMAT.md §3)  #
#                                                                              #
#   R1  Definite-length encoding only. No indefinite-length items.             #
#   R2  Shortest-form argument for every major type's length/value.            #
#   R3  Map keys sorted by bytewise lexicographic order of their ENCODED bytes. #
#   R4  No duplicate map keys, on encode or on decode.                         #
#   R5  Decoders reject non-deterministic input rather than accepting it.      #
#                                                                              #
# Plus one portfolio restriction beyond RFC 8949:                              #
#   R6  No floating-point values anywhere in a signed payload.                 #
# --------------------------------------------------------------------------- #

MT_UINT = 0
MT_NEGINT = 1
MT_BSTR = 2
MT_TSTR = 3
MT_ARRAY = 4
MT_MAP = 5
MT_TAG = 6
MT_SIMPLE = 7

SIMPLE_FALSE = 20
SIMPLE_TRUE = 21
SIMPLE_NULL = 22

UINT64_MAX = (1 << 64) - 1


class CBORError(ValueError):
    """Raised for any encoding or decoding rule violation."""


# --------------------------------------------------------------------------- #
# Encoding                                                                     #
# --------------------------------------------------------------------------- #
def _head(major: int, arg: int) -> bytes:
    """Shortest-form head byte(s) for a major type and its argument (R2)."""
    if arg < 0 or arg > UINT64_MAX:
        raise CBORError(f"argument out of range for deterministic CBOR: {arg}")
    m = major << 5
    if arg < 24:
        return bytes([m | arg])
    if arg < 0x100:
        return bytes([m | 24, arg])
    if arg < 0x10000:
        return bytes([m | 25]) + arg.to_bytes(2, "big")
    if arg < 0x100000000:
        return bytes([m | 26]) + arg.to_bytes(4, "big")
    return bytes([m | 27]) + arg.to_bytes(8, "big")


def encode(value) -> bytes:
    """Encode a value to its unique deterministic CBOR byte string.

    Raises CBORError on floats (R6), tags, out-of-range integers, duplicate map
    keys (R4), or any unsupported type.
    """
    out = bytearray()
    _encode_into(value, out)
    return bytes(out)


def _encode_into(value, out: bytearray) -> None:
    # bool must precede int: bool is a subclass of int in Python.
    if value is True:
        out.append(0xE0 | SIMPLE_TRUE)
        return
    if value is False:
        out.append(0xE0 | SIMPLE_FALSE)
        return
    if value is None:
        out.append(0xE0 | SIMPLE_NULL)
        return
    if isinstance(value, float):
        # R6. The rounding of a float to its shortest round-tripping form is
        # exactly the cross-language agreement the portfolio cannot rely on
        # (many Cortex-M parts have single-precision or no FPU). Callers scale
        # to integers via provenance.quantize instead.
        raise CBORError(
            "floats are not permitted in a signed payload; "
            "scale to an integer via aletheia.provenance.quantize"
        )
    if isinstance(value, int):
        if value >= 0:
            if value > UINT64_MAX:
                raise CBORError(f"uint out of 64-bit range: {value}")
            out += _head(MT_UINT, value)
        else:
            n = -1 - value
            if n > UINT64_MAX:
                raise CBORError(f"negint out of 64-bit range: {value}")
            out += _head(MT_NEGINT, n)
        return
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
        out += _head(MT_BSTR, len(b))
        out += b
        return
    if isinstance(value, str):
        b = value.encode("utf-8")
        out += _head(MT_TSTR, len(b))
        out += b
        return
    if isinstance(value, (list, tuple)):
        out += _head(MT_ARRAY, len(value))
        for item in value:
            _encode_into(item, out)
        return
    if isinstance(value, dict):
        # R3: sort by the bytewise order of the ENCODED key, not of the key
        # itself. For text keys shorter than 24 bytes the head byte is
        # 0x60 + len, so length dominates the comparison: "v" < "id" < "cls".
        # Sorting the Python strings instead is the single most common way to
        # get this wrong, so the encoded form is what we sort.
        items = []
        seen = set()
        for k, v in value.items():
            ek = encode(k)
            if ek in seen:  # R4
                raise CBORError(f"duplicate map key: {k!r}")
            seen.add(ek)
            items.append((ek, v))
        items.sort(key=lambda kv: kv[0])
        out += _head(MT_MAP, len(items))
        for ek, v in items:
            out += ek
            _encode_into(v, out)
        return
    raise CBORError(f"type not encodable in the zil-provenance subset: {type(value).__name__}")


# --------------------------------------------------------------------------- #
# Decoding — strict (R5)                                                       #
# --------------------------------------------------------------------------- #
def decode(data: bytes):
    """Decode deterministic CBOR. Rejects any non-deterministic encoding.

    Precondition: ``data`` is the complete encoding of exactly one item.
    Postcondition: ``encode(decode(data)) == data`` for every accepted input.
    """
    value, offset = _decode_at(data, 0)
    if offset != len(data):
        raise CBORError(f"{len(data) - offset} trailing byte(s) after top-level item")
    return value


def _read_arg(data: bytes, offset: int, ai: int) -> tuple[int, int]:
    """Read a shortest-form argument. Enforces R1 and R2."""
    if ai < 24:
        return ai, offset
    if ai == 24:
        if offset + 1 > len(data):
            raise CBORError("truncated 1-byte argument")
        arg = data[offset]
        if arg < 24:  # R2: should have been encoded in the head byte
            raise CBORError(f"non-shortest-form argument: {arg} encoded in 1 byte")
        return arg, offset + 1
    if ai == 25:
        if offset + 2 > len(data):
            raise CBORError("truncated 2-byte argument")
        arg = int.from_bytes(data[offset:offset + 2], "big")
        if arg < 0x100:
            raise CBORError(f"non-shortest-form argument: {arg} encoded in 2 bytes")
        return arg, offset + 2
    if ai == 26:
        if offset + 4 > len(data):
            raise CBORError("truncated 4-byte argument")
        arg = int.from_bytes(data[offset:offset + 4], "big")
        if arg < 0x10000:
            raise CBORError(f"non-shortest-form argument: {arg} encoded in 4 bytes")
        return arg, offset + 4
    if ai == 27:
        if offset + 8 > len(data):
            raise CBORError("truncated 8-byte argument")
        arg = int.from_bytes(data[offset:offset + 8], "big")
        if arg < 0x100000000:
            raise CBORError(f"non-shortest-form argument: {arg} encoded in 8 bytes")
        return arg, offset + 8
    if ai == 31:
        raise CBORError("indefinite-length item rejected (R1)")
    raise CBORError(f"reserved additional-information value {ai}")


def _decode_at(data: bytes, offset: int):
    if offset >= len(data):
        raise CBORError("unexpected end of input")
    ib = data[offset]
    major = ib >> 5
    ai = ib & 0x1F
    offset += 1

    if major in (MT_UINT, MT_NEGINT):
        arg, offset = _read_arg(data, offset, ai)
        return (arg if major == MT_UINT else -1 - arg), offset

    if major in (MT_BSTR, MT_TSTR):
        n, offset = _read_arg(data, offset, ai)
        if offset + n > len(data):
            raise CBORError("truncated string")
        raw = data[offset:offset + n]
        offset += n
        if major == MT_BSTR:
            return raw, offset
        try:
            return raw.decode("utf-8"), offset
        except UnicodeDecodeError as exc:
            raise CBORError(f"invalid UTF-8 in text string: {exc}") from exc

    if major == MT_ARRAY:
        n, offset = _read_arg(data, offset, ai)
        items = []
        for _ in range(n):
            item, offset = _decode_at(data, offset)
            items.append(item)
        return items, offset

    if major == MT_MAP:
        n, offset = _read_arg(data, offset, ai)
        result = {}
        prev_key_bytes = None
        for _ in range(n):
            key_start = offset
            key, offset = _decode_at(data, offset)
            key_bytes = data[key_start:offset]
            if prev_key_bytes is not None:
                if key_bytes == prev_key_bytes:
                    raise CBORError(f"duplicate map key: {key!r} (R4)")
                if key_bytes < prev_key_bytes:
                    raise CBORError(
                        f"map keys not in deterministic order at key {key!r} (R3)"
                    )
            prev_key_bytes = key_bytes
            try:
                hash(key)
            except TypeError as exc:
                raise CBORError(f"unhashable map key: {key!r}") from exc
            result[key] = None
            value, offset = _decode_at(data, offset)
            result[key] = value
        return result, offset

    if major == MT_TAG:
        raise CBORError("CBOR tags are not part of the zil-provenance subset")

    # major == MT_SIMPLE
    if ai == SIMPLE_FALSE:
        return False, offset
    if ai == SIMPLE_TRUE:
        return True, offset
    if ai == SIMPLE_NULL:
        return None, offset
    if ai in (25, 26, 27):
        raise CBORError("floating-point values are not permitted (R6)")
    raise CBORError(f"simple value {ai} is not part of the zil-provenance subset")
