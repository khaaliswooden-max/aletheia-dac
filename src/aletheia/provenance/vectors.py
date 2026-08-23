"""
vectors.py — the zil-provenance v1 conformance test-vector suite.

These vectors are the contract between implementations. The Rust crate
`caduceus-attest` (Caduceus M2) and the embedded-C peer (EPHEMERIS v0.3) are
validated against exactly these bytes; neither is in scope for this session, and
neither needs to read the Python to implement the format.

THE SIGNING KEY IN THIS MODULE IS A TEST KEY.
It is derived deterministically from a published constant so that anyone can
regenerate the fixtures and get identical bytes. It has no custody, no
provenance weight, and must never sign anything real. No AI collaborator holds
or handles production key material, and this module is the only place in the
core that constructs a private key at all.

Vector categories:
  cbor          value -> expected encoding
  cbor-reject   byte string that a conforming decoder MUST reject
  quantize      real input -> expected signed integer, per rounding direction
  dac           envelope -> signing bytes, signature, record hash
  entry         chain entry -> signing bytes, signature, record hash
  schema-reject envelope map that a conforming decoder MUST reject
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import attest, cbor, codec, quantize
from .entry import EntryV1
from .envelope import ConfidenceV1, DacV1, SchemaError, ValidityV1

#: Published derivation of the conformance test key. Regenerate with:
#:     sha256(TEST_KEY_DERIVATION)  ->  Ed25519 private scalar
TEST_KEY_DERIVATION = (
    b"zil-provenance/v1/conformance-test-key/DO-NOT-USE-IN-PRODUCTION"
)
TEST_KEY_LABEL = "ZIL-PROVENANCE-V1-CONFORMANCE-TEST-KEY-DO-NOT-USE-IN-PRODUCTION"

SUITE_VERSION = 1


def conformance_private_key():
    """The conformance test signing key. NOT a production key. See module docs."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = hashlib.sha256(TEST_KEY_DERIVATION).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


TEST_ATTESTOR_DERIVATION = b"zil-provenance/v1/conformance-test-attestor/DO-NOT-USE-IN-PRODUCTION/"


def _test_attestor(n: int):
    """A conformance TEST attestor key. Not a real attestor, not a real key.

    Recruitment of independent attestors is open and is the principal
    investigator's to do (PORTFOLIO_BUILD_PLAN.md §7.6.5). No AI collaborator
    holds attestor key material, and nothing signed with these keys is an
    attestation of anything.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = hashlib.sha256(TEST_ATTESTOR_DERIVATION + str(n).encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _fixed_id(n: int) -> bytes:
    """Deterministic 16-byte claim id, so vectors are reproducible."""
    return hashlib.sha256(f"zil-provenance/v1/vector-id/{n}".encode()).digest()[:16]


def _fixed_hash(tag: str) -> bytes:
    return hashlib.sha256(f"zil-provenance/v1/vector-payload/{tag}".encode()).digest()


# --------------------------------------------------------------------------- #
# CBOR vectors                                                                 #
# --------------------------------------------------------------------------- #
def _cbor_vectors() -> list:
    max_len_text = "z" * 300          # forces a 2-byte length argument
    max_len_bytes = bytes(range(256)) * 2
    return [
        {"name": "uint-zero", "value": 0, "hex": cbor.encode(0).hex()},
        {"name": "uint-23-boundary", "value": 23, "hex": cbor.encode(23).hex()},
        {"name": "uint-24-boundary", "value": 24, "hex": cbor.encode(24).hex()},
        {"name": "uint-255-boundary", "value": 255, "hex": cbor.encode(255).hex()},
        {"name": "uint-256-boundary", "value": 256, "hex": cbor.encode(256).hex()},
        {"name": "uint-65535-boundary", "value": 65535, "hex": cbor.encode(65535).hex()},
        {"name": "uint-65536-boundary", "value": 65536, "hex": cbor.encode(65536).hex()},
        {"name": "uint-u32-max", "value": 4294967295, "hex": cbor.encode(4294967295).hex()},
        {"name": "uint-u32-max-plus-one", "value": 4294967296,
         "hex": cbor.encode(4294967296).hex()},
        {"name": "uint-u64-max", "value": (1 << 64) - 1, "hex": cbor.encode((1 << 64) - 1).hex()},
        {"name": "negint-minus-one", "value": -1, "hex": cbor.encode(-1).hex()},
        {"name": "bool-true", "value": True, "hex": cbor.encode(True).hex()},
        {"name": "bool-false", "value": False, "hex": cbor.encode(False).hex()},
        {"name": "null", "value": None, "hex": cbor.encode(None).hex()},
        {"name": "empty-array", "value": [], "hex": cbor.encode([]).hex()},
        {"name": "empty-map", "value": {}, "hex": cbor.encode({}).hex()},
        {"name": "empty-bytes", "value": "", "hex": cbor.encode(b"").hex(),
         "note": "empty byte string"},
        # ADVERSARIAL: the input map is written out of order; the encoding must
        # be identical to the in-order one. This is the field-reordering vector.
        {"name": "map-key-order-length-first",
         "value": {"cls": 3, "id": 1, "v": 1, "conf": 2},
         "hex": cbor.encode({"cls": 3, "id": 1, "v": 1, "conf": 2}).hex(),
         "note": "keys sort by ENCODED bytes: v < id < cls < conf (length first)"},
        {"name": "map-key-order-reversed-input",
         "value": {"conf": 2, "v": 1, "id": 1, "cls": 3},
         "hex": cbor.encode({"conf": 2, "v": 1, "id": 1, "cls": 3}).hex(),
         "note": "same bytes as map-key-order-length-first despite reversed input"},
        # ADVERSARIAL: non-ASCII must be raw UTF-8, never \\uXXXX escaped. Two of
        # the four legacy JSON implementations escaped and one did not.
        {"name": "text-non-ascii", "value": "Café — Mañana",
         "hex": cbor.encode("Café — Mañana").hex(),
         "note": "raw UTF-8; no escaping"},
        {"name": "text-astral-plane", "value": "🛰\U0001F6F0",
         "hex": cbor.encode("🛰\U0001F6F0").hex()},
        # ADVERSARIAL: maximum-length fields exercise the 2-byte length argument.
        {"name": "text-300-bytes", "value": max_len_text,
         "hex": cbor.encode(max_len_text).hex()},
        {"name": "bytes-512", "value": max_len_bytes.hex(),
         "hex": cbor.encode(max_len_bytes).hex(), "note": "value is hex-encoded"},
        {"name": "nested", "value": {"a": [1, [2, {"b": None}]], "z": {}},
         "hex": cbor.encode({"a": [1, [2, {"b": None}]], "z": {}}).hex()},
    ]


def _cbor_reject_vectors() -> list:
    """Byte strings a conforming decoder MUST reject (rule R5)."""
    return [
        {"name": "indefinite-length-array", "hex": "9f01ff",
         "reason": "indefinite-length item (R1)"},
        {"name": "indefinite-length-map", "hex": "bf616101ff",
         "reason": "indefinite-length item (R1)"},
        {"name": "non-shortest-uint-1-byte", "hex": "1817",
         "reason": "23 encoded in a 1-byte argument (R2)"},
        {"name": "non-shortest-uint-2-byte", "hex": "1900ff",
         "reason": "255 encoded in a 2-byte argument (R2)"},
        {"name": "non-shortest-uint-4-byte", "hex": "1a0000ffff",
         "reason": "65535 encoded in a 4-byte argument (R2)"},
        {"name": "non-shortest-uint-8-byte", "hex": "1b00000000ffffffff",
         "reason": "4294967295 encoded in an 8-byte argument (R2)"},
        {"name": "map-keys-out-of-order", "hex": "a2626964016176 01".replace(" ", ""),
         "reason": "'id' before 'v' violates encoded-bytes ordering (R3)"},
        {"name": "map-duplicate-keys", "hex": "a2617601617602",
         "reason": "duplicate key 'v' (R4)"},
        {"name": "float-half", "hex": "f93c00", "reason": "floating-point value (R6)"},
        {"name": "float-single", "hex": "fa3f800000", "reason": "floating-point value (R6)"},
        {"name": "float-double", "hex": "fb3ff0000000000000",
         "reason": "floating-point value (R6)"},
        {"name": "tag-datetime", "hex": "c07818323032362d30382d32335430303a30303a30305a",
         "reason": "CBOR tags are outside the subset"},
        {"name": "simple-undefined", "hex": "f7", "reason": "undefined is outside the subset"},
        {"name": "trailing-bytes", "hex": "0101", "reason": "trailing byte after top-level item"},
        {"name": "truncated-string", "hex": "6261", "reason": "truncated text string"},
        {"name": "reserved-additional-info", "hex": "1c", "reason": "reserved value 28"},
    ]


# --------------------------------------------------------------------------- #
# Quantization vectors                                                         #
# --------------------------------------------------------------------------- #
def _quantize_vectors() -> list:
    """Each rounding direction pinned at a boundary value.

    The float-vs-decimal pairs are the important ones: they pin that the
    reduction is exact-rational, so a double that is fractionally below its
    decimal literal quantizes DOWN and never silently inflates the claim.
    """
    return [
        {"name": "value-floor-exact-decimal", "op": "ratio_to_ppm_floor",
         "input": "0.99", "input_type": "decimal", "expected": 990000},
        {"name": "value-floor-double-below-literal", "op": "ratio_to_ppm_floor",
         "input": "0.99", "input_type": "float", "expected": 989999,
         "note": "the double nearest 0.99 is strictly below it; floor is 989999. "
                 "floor(0.99 * 1e6) returns 990000 and inflates the claim."},
        {"name": "value-floor-double-exact", "op": "ratio_to_ppm_floor",
         "input": "0.92", "input_type": "float", "expected": 920000,
         "note": "this double quantizes exactly; no divergence"},
        {"name": "value-floor-double-0.95", "op": "ratio_to_ppm_floor",
         "input": "0.95", "input_type": "float", "expected": 949999},
        {"name": "value-floor-zero", "op": "ratio_to_ppm_floor",
         "input": "0", "input_type": "int", "expected": 0},
        {"name": "value-floor-one", "op": "ratio_to_ppm_floor",
         "input": "1", "input_type": "int", "expected": 1000000},
        {"name": "alpha-ceil-exact-decimal", "op": "ratio_to_ppm_ceil",
         "input": "0.05", "input_type": "decimal", "expected": 50000},
        {"name": "alpha-ceil-double-above", "op": "ratio_to_ppm_ceil",
         "input": "0.05", "input_type": "float", "expected": 50001,
         "note": "the double nearest 0.05 is above it; ceil is 50001, which "
                 "never understates the miscoverage rate"},
        {"name": "alpha-ceil-double-0.1", "op": "ratio_to_ppm_ceil",
         "input": "0.1", "input_type": "float", "expected": 100001},
        {"name": "issued-at-ceil", "op": "seconds_to_us_ceil",
         "input": "1787471306.4185935", "input_type": "float",
         "expected": quantize.seconds_to_us_ceil(1787471306.4185935),
         "note": "window start never earlier than truth"},
        {"name": "expires-at-floor", "op": "seconds_to_us_floor",
         "input": "1787471306.4185935", "input_type": "float",
         "expected": quantize.seconds_to_us_floor(1787471306.4185935),
         "note": "window end never later than truth"},
        {"name": "us-max-boundary", "op": "seconds_to_us_floor",
         "input": str(quantize.US_MAX // 1_000_000), "input_type": "int",
         "expected": (quantize.US_MAX // 1_000_000) * 1_000_000},
    ]


def _quantize_reject_vectors() -> list:
    return [
        {"name": "ppm-above-one", "op": "ratio_to_ppm_floor", "input": "1.5",
         "input_type": "decimal", "reason": "coverage above 1.0"},
        {"name": "ppm-negative", "op": "ratio_to_ppm_floor", "input": "-0.1",
         "input_type": "decimal", "reason": "negative coverage"},
        {"name": "nan", "op": "ratio_to_ppm_floor", "input": "nan",
         "input_type": "float", "reason": "non-finite"},
        {"name": "inf", "op": "ratio_to_ppm_floor", "input": "inf",
         "input_type": "float", "reason": "non-finite"},
        {"name": "us-above-max", "op": "seconds_to_us_floor",
         "input": str(quantize.US_MAX // 1_000_000 + 1), "input_type": "int",
         "reason": "beyond year 9999"},
        {"name": "us-negative", "op": "seconds_to_us_floor", "input": "-1",
         "input_type": "int", "reason": "before the Unix epoch"},
    ]


# --------------------------------------------------------------------------- #
# Envelope and entry vectors                                                   #
# --------------------------------------------------------------------------- #
def _sample_envelopes() -> list:
    sk = conformance_private_key()
    pk_raw = codec.public_key_bytes(sk.public_key())
    out = []

    def emit(name, env, note=None):
        env.sign(sk)
        v = {"name": name,
             "projection": _projection_for_vector(env),
             "signing_bytes_hex": env.signing_bytes().hex(),
             "signature_set_hex": env.signatures.encode().hex(),
             "record_hash_hex": env.record_hash().hex(),
             "wire_hex": env.encode().hex()}
        if note:
            v["note"] = note
        out.append(v)

    # ADVERSARIAL: an empty parent set is a genesis claim, not an error.
    emit("dac-genesis-no-parents", DacV1(
        kind="sensor_reading", payload_hash=_fixed_hash("vitals"),
        producer_id="sensor.l0", producer_pk=pk_raw, parents=[],
        confidence=ConfidenceV1("asserted", 990000, 10000),
        validity=ValidityV1("stream_A", 1_787_471_306_000_000, 1_787_471_906_000_000),
        classification=3, requires_hitl=True,
        prev=codec.GENESIS_PREV, claim_id=_fixed_id(1)),
        "empty parent set; REGULATED so hitl is forced true")

    emit("dac-derived-two-parents", DacV1(
        kind="policy_decision", payload_hash=_fixed_hash("triage"),
        producer_id="policy.l5", producer_pk=pk_raw,
        parents=sorted([_fixed_id(1), _fixed_id(2)]),
        confidence=ConfidenceV1("split_conformal", 920000, 80000),
        validity=ValidityV1(None, 1_787_471_306_000_000, 1_787_471_906_000_000),
        classification=1, requires_hitl=False,
        prev=bytes.fromhex("11" * 32), claim_id=_fixed_id(3)),
        "parents sorted bytewise; no monitor")

    emit("dac-with-interval", DacV1(
        kind="regression", payload_hash=_fixed_hash("reg"),
        producer_id="model.l3", producer_pk=pk_raw, parents=[],
        confidence=ConfidenceV1("split_conformal", 900000, 100000,
                                interval=[[-1_500_000_000, -9], [1_500_000_000, -9]]),
        validity=ValidityV1(None, 0, quantize.US_MAX),
        classification=0, requires_hitl=False,
        claim_id=_fixed_id(4)),
        "decimal-pair interval; validity spans the full representable range")

    # ADVERSARIAL: non-ASCII in every text field.
    emit("dac-non-ascii-fields", DacV1(
        kind="mesure_température", payload_hash=_fixed_hash("temp"),
        producer_id="capteur.l0", producer_pk=pk_raw, parents=[],
        confidence=ConfidenceV1("asserté", 500000, 500000),
        validity=ValidityV1("flux_Ā", 1_000_000, 2_000_000),
        classification=2, requires_hitl=True, claim_id=_fixed_id(5)),
        "non-ASCII in kind, method and monitor id; raw UTF-8 throughout")

    # ADVERSARIAL: maximum-length text and a large parent set.
    emit("dac-max-length-fields", DacV1(
        kind="k" * 1024, payload_hash=_fixed_hash("big"),
        producer_id="p" * 512, producer_pk=pk_raw,
        parents=sorted(_fixed_id(i) for i in range(64)),
        confidence=ConfidenceV1("m" * 256, 0, 1000000),
        validity=ValidityV1("mon" * 200, 0, 0),
        classification=0, requires_hitl=False, claim_id=_fixed_id(6)),
        "2-byte length arguments throughout; 64 parents; zero-width validity")

    # ADVERSARIAL: a declared, signed extension map.
    emit("dac-with-ext", DacV1(
        kind="ephemeris_update", payload_hash=_fixed_hash("eph"),
        producer_id="ephemeris.peer", producer_pk=pk_raw, parents=[],
        confidence=ConfidenceV1("asserted", 1000000, 0),
        validity=ValidityV1(None, 1_787_471_306_000_000, 1_787_471_906_000_000),
        classification=0, requires_hitl=False, claim_id=_fixed_id(7),
        ext={"tt_j2000_us": 869_616_069_184_065, "body_urn": "urn:vbx-body:mars"}),
        "ext carries EPHEMERIS domain fields; the envelope timestamp stays UTC")
    return out


def _projection_for_vector(env: DacV1) -> dict:
    from .envelope import to_projection
    return to_projection(env)


def _sample_entries() -> list:
    sk = conformance_private_key()
    out = []

    def emit(name, entry, note=None):
        entry.sign(sk)
        v = {"name": name,
             "seq": entry.seq, "ts_us": entry.ts_us,
             "event_type": entry.event_type, "payload_hex": entry.payload.hex(),
             "prev_hex": entry.prev.hex(), "ext": entry.ext,
             "signing_bytes_hex": entry.signing_bytes().hex(),
             "signature_set_hex": entry.signatures.encode().hex(),
             "attestor_count": len(entry.signatures.attestors),
             "threshold_required": (entry.signatures.policy.required
                                    if entry.signatures.policy else 0),
             "record_hash_hex": entry.record_hash().hex(),
             "wire_hex": entry.encode().hex()}
        if note:
            v["note"] = note
        out.append(v)

    emit("entry-genesis", EntryV1.from_json_payload(
        seq=0, ts_us=1_787_471_306_000_000, event_type="GATE_DECISION",
        payload_obj={"outcome": "AUTONOMOUS"}, prev=codec.GENESIS_PREV),
         "genesis prev is 32 zero bytes, which is '0'*64 in hex")
    emit("entry-with-ext-ns", EntryV1.from_json_payload(
        seq=1, ts_us=1_787_471_306_123_456, event_type="INFERENCE_RECOMMENDATION",
        payload_obj={"model_version": "v0.2-alpha"}, prev=bytes.fromhex("22" * 32),
        ext={"ts_ns": 1_787_471_306_123_456_789}),
         "nanosecond precision preserved in the signed ext map")
    emit("entry-empty-payload", EntryV1(seq=2, ts_us=0, event_type="",
                                        payload=b"",
                                        prev=bytes.fromhex("33" * 32)),
         "empty event type, empty payload, zero timestamp")
    emit("entry-non-ascii", EntryV1.from_json_payload(
        seq=3, ts_us=1_000_000, event_type="ALERTE_CRITIQUE",
        payload_obj={"état": "dégradé", "n": -1}, prev=bytes.fromhex("44" * 32)),
         "non-ASCII event type; payload bytes are attested, not interpreted")
    emit("entry-float-payload", EntryV1.from_json_payload(
        seq=4, ts_us=2_000_000, event_type="BIOMEDICAL_ALERT",
        payload_obj={"o2_partial_pressure_kpa": 19.0, "latency_s": 0.031},
        prev=bytes.fromhex("55" * 32)),
         "application floats are fine INSIDE an opaque payload; the no-float "
         "rule binds the envelope and the ext map, not attested blobs")

    # --- n-of-m attestation: the two cases the work order requires --------- #
    # AUTHOR-ONLY, zero attestors. This is what every substrate emits today and
    # it is a valid instance of the set model, not a case outside it.
    author_only_entry = EntryV1.from_json_payload(
        seq=5, ts_us=3_000_000, event_type="BENCHMARK_FREEZE",
        payload_obj={"bench": "caduceus-bench", "version": "v1.2.1"},
        prev=bytes.fromhex("66" * 32))
    author_only_entry.sign(sk, policy=attest.POLICY_AUTHOR_ONLY)
    out.append({"name": "entry-attest-author-only",
                "seq": author_only_entry.seq, "ts_us": author_only_entry.ts_us,
                "event_type": author_only_entry.event_type,
                "payload_hex": author_only_entry.payload.hex(),
                "prev_hex": author_only_entry.prev.hex(), "ext": None,
                "signing_bytes_hex": author_only_entry.signing_bytes().hex(),
                "signature_set_hex": author_only_entry.signatures.encode().hex(),
                "attestor_count": 0, "threshold_required": 0,
                "record_hash_hex": author_only_entry.record_hash().hex(),
                "wire_hex": author_only_entry.encode().hex(),
                "note": "author signature, zero attestors, threshold 0 — the "
                        "shape every substrate emits today"})

    # AUTHOR PLUS TWO ATTESTORS under a 2-of-3 policy. The attestor keys are
    # derived from published constants and are TEST KEYS; no real attestation is
    # produced by this session and no attestor has been recruited.
    attested = EntryV1.from_json_payload(
        seq=6, ts_us=4_000_000, event_type="BENCHMARK_FREEZE",
        payload_obj={"bench": "caduceus-bench", "version": "v1.2.1"},
        prev=bytes.fromhex("77" * 32))
    attested.sign(sk, policy=attest.POLICY_2_OF_3)
    attested.attest_with(_test_attestor(1), role=attest.ROLE_PROCESS)
    attested.attest_with(_test_attestor(2), role=attest.ROLE_METHODOLOGY)
    out.append({"name": "entry-attest-author-plus-two",
                "seq": attested.seq, "ts_us": attested.ts_us,
                "event_type": attested.event_type,
                "payload_hex": attested.payload.hex(),
                "prev_hex": attested.prev.hex(), "ext": None,
                "signing_bytes_hex": attested.signing_bytes().hex(),
                "signature_set_hex": attested.signatures.encode().hex(),
                "attestor_count": 2, "threshold_required": 2,
                "record_hash_hex": attested.record_hash().hex(),
                "wire_hex": attested.encode().hex(),
                "note": "author + 2-of-3 independent attestors; the author "
                        "signature does NOT count toward the threshold. "
                        "Attestor keys are TEST KEYS."})
    return out


def _near_miss_vectors() -> list:
    """Signatures that are one bit, one byte or one field away from valid.

    A conforming verifier MUST reject every one. These catch implementations
    that compare a prefix, that truncate, or that verify the wrong bytes.
    """
    sk = conformance_private_key()
    pk_raw = codec.public_key_bytes(sk.public_key())
    env = DacV1(kind="sensor_reading", payload_hash=_fixed_hash("nm"),
                producer_id="sensor.l0", producer_pk=pk_raw, parents=[],
                confidence=ConfidenceV1("asserted", 990000, 10000),
                validity=ValidityV1(None, 1_000_000, 2_000_000),
                classification=0, requires_hitl=False, claim_id=_fixed_id(8))
    env.sign(sk)
    good = env.signature
    good_bytes = env.signing_bytes()

    flipped = bytearray(good); flipped[0] ^= 0x01
    last_flipped = bytearray(good); last_flipped[-1] ^= 0x80

    # A signature that is valid -- but for the chain domain, not the DAC domain.
    cross = codec.sign(sk, codec.DOMAIN_CHAIN, env.to_map())

    # A signature over the same map with prev advanced by one bit: this is the
    # vector that would pass under the legacy format, where prev was outside the
    # signature, and must fail under v1.
    moved = DacV1(**{**env.__dict__, "prev": bytes([1]) + b"\x00" * 31})
    moved_sig = codec.sign(sk, codec.DOMAIN_DAC, moved.to_map())

    return [
        {"name": "near-miss-first-byte-flipped", "signature_hex": bytes(flipped).hex(),
         "reason": "one bit flipped in the first signature byte"},
        {"name": "near-miss-last-byte-flipped", "signature_hex": bytes(last_flipped).hex(),
         "reason": "one bit flipped in the last signature byte"},
        {"name": "near-miss-truncated", "signature_hex": good[:-1].hex(),
         "reason": "63-byte signature"},
        {"name": "near-miss-zero-extended", "signature_hex": (good + b"\x00").hex(),
         "reason": "65-byte signature"},
        {"name": "near-miss-all-zero", "signature_hex": ("00" * 64),
         "reason": "all-zero signature"},
        {"name": "near-miss-wrong-domain", "signature_hex": cross.hex(),
         "reason": "valid signature over the same map under DOMAIN_CHAIN; "
                   "domain separation must reject it"},
        {"name": "near-miss-different-prev", "signature_hex": moved_sig.hex(),
         "reason": "valid signature over the same claim with a different prev; "
                   "rejected only because prev is inside the v1 signature"},
        {"name": "target-signing-bytes-hex", "signing_bytes_hex": good_bytes.hex(),
         "signature_hex": good.hex(), "reason": "the one signature that must verify",
         "must_verify": True},
    ]


def _attest_reject_vectors() -> list:
    """Signature sets a conforming verifier MUST reject or mark not-met.

    Adversarial cases specific to the n-of-m model. Each one is a way an
    attested artifact could be made to look better than it is.
    """
    sk = conformance_private_key()
    a1, a2 = _test_attestor(1), _test_attestor(2)
    author_pk = codec.public_key_bytes(sk.public_key())

    def entry():
        e = EntryV1.from_json_payload(
            seq=9, ts_us=5_000_000, event_type="BENCHMARK_FREEZE",
            payload_obj={"bench": "x"}, prev=bytes.fromhex("88" * 32))
        e.sign(sk, policy=attest.POLICY_2_OF_3)
        return e

    out = []

    # The author signing twice must not satisfy a 2-of-3 threshold.
    e = entry()
    forged = attest.SignatureSet(
        author=e.signatures.author,
        attestors=[attest.Attestation(public_key=author_pk,
                                      signature=e.signatures.author.signature)],
        policy=attest.POLICY_2_OF_3)
    out.append({"name": "attest-author-counted-as-attestor",
                "signature_set_hex": cbor.encode(
                    {"a": forged.author.to_map(),
                     "at": [forged.attestors[0].to_map()],
                     "th": attest.POLICY_2_OF_3.to_map()}).hex(),
                "reason": "an attestor key equal to the author key must be "
                          "rejected; otherwise 2-of-3 degrades to one signer"})

    # One attestor under a 2-of-3 policy: valid signatures, threshold not met.
    e = entry(); e.attest_with(a1, role=attest.ROLE_PROCESS)
    out.append({"name": "attest-threshold-not-reached",
                "signature_set_hex": e.signatures.encode().hex(),
                "signing_bytes_hex": e.signing_bytes().hex(),
                "reason": "one independent attestor under a 2-of-3 policy; "
                          "the entry must report threshold_not_reached, never "
                          "pass with a footnote"})

    # Attestors present but out of canonical order.
    e = entry(); e.attest_with(a1); e.attest_with(a2)
    ordered = sorted(e.signatures.attestors, key=lambda x: bytes(x.public_key))
    out.append({"name": "attest-attestors-out-of-order",
                "signature_set_hex": cbor.encode(
                    {"a": e.signatures.author.to_map(),
                     "at": [ordered[1].to_map(), ordered[0].to_map()],
                     "th": attest.POLICY_2_OF_3.to_map()}).hex(),
                "reason": "attestor signatures must be sorted by key, bytewise"})

    # The same attestor twice must not count as two.
    e = entry(); e.attest_with(a1)
    dup = e.signatures.attestors[0].to_map()
    out.append({"name": "attest-duplicate-attestor",
                "signature_set_hex": cbor.encode(
                    {"a": e.signatures.author.to_map(),
                     "at": [dup, dup],
                     "th": attest.POLICY_2_OF_3.to_map()}).hex(),
                "reason": "a duplicated attestor must not count twice toward "
                          "the threshold"})

    # A threshold larger than the roster it is drawn from is incoherent.
    out.append({"name": "attest-threshold-exceeds-roster",
                "signature_set_hex": cbor.encode(
                    {"a": entry().signatures.author.to_map(),
                     "th": {"n": 4, "m": 3}}).hex(),
                "reason": "requiring 4 of a roster of 3 can never be met"})
    return out


def _schema_reject_vectors() -> list:
    """Envelope maps a conforming decoder MUST reject."""
    sk = conformance_private_key()
    pk_raw = codec.public_key_bytes(sk.public_key())
    base = DacV1(kind="k", payload_hash=_fixed_hash("s"), producer_id="p",
                 producer_pk=pk_raw, parents=[],
                 confidence=ConfidenceV1("asserted", 900000, 100000),
                 validity=ValidityV1(None, 1_000_000, 2_000_000),
                 classification=0, requires_hitl=False,
                 claim_id=_fixed_id(9)).to_map()

    def mutate(**kw):
        m = json.loads(json.dumps(base, default=lambda b: b.hex()))
        m.update(kw)
        return m

    return [
        # ADVERSARIAL: an unknown field must be REJECTED, not ignored. A verifier
        # that ignores it verifies a signature over bytes it did not understand.
        {"name": "unknown-top-level-key", "mutation": {"add": {"surprise": 1}},
         "reason": "unknown envelope key (strict rejection, docs/WIRE_FORMAT.md 7)"},
        {"name": "unknown-conf-key", "mutation": {"conf_add": {"zzz": 1}},
         "reason": "unknown conf key"},
        {"name": "unknown-val-key", "mutation": {"val_add": {"zzz": 1}},
         "reason": "unknown val key"},
        {"name": "missing-required-key", "mutation": {"remove": "cls"},
         "reason": "envelope.cls is required"},
        {"name": "wrong-version", "mutation": {"set": {"v": 2}},
         "reason": "unsupported format version"},
        {"name": "id-wrong-length", "mutation": {"set_bytes": {"id": "00" * 15}},
         "reason": "claim id must be 16 bytes"},
        {"name": "pk-wrong-length", "mutation": {"set_bytes": {"pk": "00" * 31}},
         "reason": "public key must be 32 bytes"},
        {"name": "ppm-out-of-range", "mutation": {"conf_set": {"v": 1000001}},
         "reason": "coverage above 1_000_000 ppm"},
        {"name": "expiry-before-issue", "mutation": {"val_set": {"exp": 0}},
         "reason": "validity window ends before it starts"},
        {"name": "bad-status", "mutation": {"val_set": {"st": "PROBABLY_FINE"}},
         "reason": "status outside the enumeration"},
        {"name": "cls-out-of-range", "mutation": {"set": {"cls": 4}},
         "reason": "classification outside [0, 3]"},
        {"name": "regulated-without-hitl",
         "mutation": {"set": {"cls": 3, "hitl": False}},
         "reason": "REGULATED requires requires_hitl = true"},
        {"name": "parents-unsorted",
         "mutation": {"set_parents": [_fixed_id(2).hex(), _fixed_id(1).hex()]},
         "reason": "parent ids must be sorted bytewise"},
        {"name": "parents-duplicate",
         "mutation": {"set_parents": [_fixed_id(1).hex(), _fixed_id(1).hex()]},
         "reason": "duplicate parent id"},
    ]


# --------------------------------------------------------------------------- #
# Suite build and check                                                        #
# --------------------------------------------------------------------------- #
def build() -> dict:
    """Construct the full conformance suite."""
    sk = conformance_private_key()
    return {
        "suite": "zil-provenance",
        "format_version": 1,
        "suite_version": SUITE_VERSION,
        "test_key": {
            "WARNING": "TEST KEY. Derived from a published constant. "
                       "No custody, no provenance weight. Never use in production.",
            "label": TEST_KEY_LABEL,
            "derivation": "Ed25519 private scalar = SHA-256(derivation_input)",
            "derivation_input_utf8": TEST_KEY_DERIVATION.decode(),
            "public_key_hex": codec.public_key_bytes(sk.public_key()).hex(),
        },
        "domains": {
            "dac": codec.DOMAIN_DAC.decode("latin-1"),
            "chain": codec.DOMAIN_CHAIN.decode("latin-1"),
            "dac_hex": codec.DOMAIN_DAC.hex(),
            "chain_hex": codec.DOMAIN_CHAIN.hex(),
        },
        "genesis_prev_hex": codec.GENESIS_PREV.hex(),
        "test_attestor_keys": {
            "WARNING": "TEST KEYS. No attestor has been recruited; no real "
                       "attestation exists. See PORTFOLIO_BUILD_PLAN.md 7.6.",
            "derivation": "Ed25519 private scalar = SHA-256(derivation_input || str(n))",
            "derivation_input_utf8": TEST_ATTESTOR_DERIVATION.decode(),
            "public_keys_hex": [
                codec.public_key_bytes(_test_attestor(n).public_key()).hex()
                for n in (1, 2)],
        },
        "cbor": _cbor_vectors(),
        "cbor_reject": _cbor_reject_vectors(),
        "quantize": _quantize_vectors(),
        "quantize_reject": _quantize_reject_vectors(),
        "dac": _sample_envelopes(),
        "entry": _sample_entries(),
        "near_miss": _near_miss_vectors(),
        "attest_reject": _attest_reject_vectors(),
        "schema_reject": _schema_reject_vectors(),
    }


def write(path) -> Path:
    """Write the suite to disk as sorted, indented JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return p


def load(path) -> dict:
    return json.loads(Path(path).read_text())
