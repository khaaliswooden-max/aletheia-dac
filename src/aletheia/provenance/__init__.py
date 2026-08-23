"""
zil-provenance — the shared provenance core for the Visionblox/Zuup portfolio.

One wire format, one signing construction, one verifier, shared by aletheia-dac,
PHRONESIS-1, Proteus, EPHEMERIS-1 and Caduceus-1. See docs/WIRE_FORMAT.md for
the normative specification and docs/zil-provenance-v1.cddl for the schema.

Layering, so the zero-budget rule holds:
  cbor, quantize          stdlib only -- importable anywhere, including the CLI
  codec, envelope, entry  add 'cryptography' for Ed25519 only
  keystore, verifier      filesystem and SQLite

VERIFIED: the conformance vectors in tests/vectors/ pin the byte-level output of
this implementation. Any Rust or embedded-C implementation must reproduce them
byte-for-byte; that is how the three are held to one format.
"""
from __future__ import annotations

from . import cbor, quantize
from .codec import (
    DOMAIN_CHAIN, DOMAIN_DAC, GENESIS_PREV, VerificationError,
    fingerprint, public_key_bytes, public_key_from_bytes, record_hash, sign,
    signing_bytes, verify,
)
from .entry import EntryV1
from .envelope import (
    CLS_CONFIDENTIAL, CLS_INTERNAL, CLS_PUBLIC, CLS_REGULATED,
    STATUS_REVOKED, STATUS_STALE, STATUS_VALID,
    ConfidenceV1, DacV1, SchemaError, ValidityV1, from_projection, propagate,
    to_projection,
)
from .keystore import Keystore, KeystoreError

FORMAT_VERSION = 1

__all__ = [
    "FORMAT_VERSION",
    "cbor", "quantize",
    "DOMAIN_DAC", "DOMAIN_CHAIN", "GENESIS_PREV", "VerificationError",
    "signing_bytes", "record_hash", "sign", "verify",
    "public_key_bytes", "public_key_from_bytes", "fingerprint",
    "DacV1", "ConfidenceV1", "ValidityV1", "SchemaError", "propagate",
    "to_projection", "from_projection",
    "CLS_PUBLIC", "CLS_INTERNAL", "CLS_CONFIDENTIAL", "CLS_REGULATED",
    "STATUS_VALID", "STATUS_STALE", "STATUS_REVOKED",
    "EntryV1",
    "Keystore", "KeystoreError",
]
