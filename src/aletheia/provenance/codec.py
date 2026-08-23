"""
codec.py — domain-separated signing, verification and record hashing.

One construction, shared by every zil-provenance structure and every substrate.
It fixes the three things the four legacy implementations each did differently
(docs/WIRE_FORMAT.md §5): what bytes are signed, what the chain hash covers, and
what separates one kind of signature from another.

Construction
    msg          = DOMAIN || deterministic_cbor(struct)
    signature    = Ed25519(sk, msg)                       -- over the bytes, not a digest
    record_hash  = SHA-256(msg || signature)

Why sign the message and not a digest
    Ed25519 already hashes internally. Signing a SHA-256 output with plain
    Ed25519 is not Ed25519ph; it adds a step and gives up the collision-
    resilience argument. PHRONESIS signed ``bytes.fromhex(entry_hash)`` and
    Proteus Loop B signed ``entry_hash.encode()`` (the ASCII hex!) — two
    different pre-hashing conventions, neither of which bought anything.

Why domain separation
    None of the four legacy implementations had any. A signature over a DAC
    envelope and a signature over a chain entry were drawn from the same key
    with no context tag, so one could in principle be presented as the other.
    The prefix makes the two signature spaces disjoint by construction.

VERIFIED: cross-domain replay is rejected; covered by
tests/test_provenance_codec.py::test_domain_separation_blocks_cross_replay.
"""
from __future__ import annotations

import hashlib

from . import cbor

#: Domain-separation tags. The trailing NUL keeps any tag from being a prefix of
#: another, so the tag boundary is unambiguous even if tags are added later.
DOMAIN_DAC = b"zil-provenance/v1/dac\x00"
DOMAIN_CHAIN = b"zil-provenance/v1/chain\x00"

#: Genesis predecessor: 32 zero bytes. In hex this is "0" * 64, which is exactly
#: the sentinel PHRONESIS already uses, so that chain's public constant is
#: unchanged by the migration. aletheia-dac used "" and Proteus used "GENESIS";
#: both are normalized to this value in v1.
GENESIS_PREV = b"\x00" * 32

SIGNATURE_LEN = 64
HASH_LEN = 32
FORMAT_VERSION = 1


class VerificationError(Exception):
    """Raised when a signature or a chain link fails to verify."""


def signing_bytes(domain: bytes, struct: dict) -> bytes:
    """The exact byte string that gets signed.

    Inputs:  a domain tag and the structure map, without its signature field.
    Outputs: DOMAIN || deterministic CBOR of the structure.
    Precondition:  ``struct`` contains no float and no signature field.
    Postcondition: byte-identical for equal structures in any implementation.
    """
    return domain + cbor.encode(struct)


def record_hash(domain: bytes, struct: dict, signature: bytes) -> bytes:
    """SHA-256 over the signed bytes and the signature.

    This is the value a successor entry carries as its ``prev``, so the chain
    binds both the content and the attestation of every predecessor.
    """
    if len(signature) != SIGNATURE_LEN:
        raise VerificationError(
            f"signature must be {SIGNATURE_LEN} bytes, got {len(signature)}"
        )
    return hashlib.sha256(signing_bytes(domain, struct) + signature).digest()


def sign(private_key, domain: bytes, struct: dict) -> bytes:
    """Sign a structure under a domain tag.

    Inputs:  an Ed25519PrivateKey, a domain tag, the structure map.
    Outputs: a 64-byte Ed25519 signature.
    """
    return private_key.sign(signing_bytes(domain, struct))


def verify(public_key, domain: bytes, struct: dict, signature: bytes) -> bool:
    """Verify a structure's signature under a domain tag.

    Postcondition: returns True only if ``signature`` was produced by the holder
    of ``public_key`` over exactly these bytes and this domain. Returns False —
    never raises — on an invalid signature, so callers can branch.
    """
    from cryptography.exceptions import InvalidSignature

    try:
        public_key.verify(signature, signing_bytes(domain, struct))
        return True
    except InvalidSignature:
        return False


def public_key_bytes(public_key) -> bytes:
    """Raw 32-byte Ed25519 public key."""
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def public_key_from_bytes(raw: bytes):
    """Rebuild an Ed25519 public key from its raw 32 bytes.

    This is what makes a v1 envelope self-verifiable: the envelope carries the
    key, so a peer holding only the envelope and a trust root can check it. The
    legacy 16-hex-character ``producer_fpr`` could identify a producer but never
    verify one.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(raw) != 32:
        raise VerificationError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


def fingerprint(public_key) -> str:
    """16 hex characters of SHA-256 over the raw public key.

    Retained only because aletheia-dac's ``Producer.fingerprint`` is part of its
    public API and appears in stored v0 envelopes. It identifies; it does not
    verify.
    """
    return hashlib.sha256(public_key_bytes(public_key)).hexdigest()[:16]


def verify_raw_ok(public_key, message: bytes, signature: bytes) -> bool:
    """Verify a signature over already-assembled signing bytes.

    Used by the conformance suite, where a vector supplies the exact message and
    a near-miss signature. Returns False for any malformed signature rather than
    raising, so a 63-byte or 65-byte near-miss is a rejection, not a crash.
    """
    from cryptography.exceptions import InvalidSignature

    try:
        public_key.verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False
