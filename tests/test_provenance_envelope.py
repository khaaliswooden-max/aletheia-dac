"""v1 DAC envelope — signing construction, strict schema, monotone propagation.

Falsification targets:
  * a signature that survives a change to the claim's chain position
  * a DAC signature accepted as a chain-entry signature
  * an envelope that verifies with an unknown field silently ignored
  * a derivation that produces a claim stronger than one of its parents
"""
import pytest

from aletheia.provenance import (
    CLS_INTERNAL, CLS_PUBLIC, CLS_REGULATED, ConfidenceV1, DacV1, SchemaError,
    STATUS_STALE, STATUS_VALID, ValidityV1, codec, from_projection, propagate,
    to_projection,
)
from aletheia.provenance.vectors import conformance_private_key

SK = conformance_private_key()
PK_RAW = codec.public_key_bytes(SK.public_key())


def make(**kw) -> DacV1:
    base = dict(
        kind="sensor_reading", payload_hash=b"\x11" * 32, producer_id="sensor.l0",
        producer_pk=PK_RAW, parents=[],
        confidence=ConfidenceV1("asserted", 990000, 10000),
        validity=ValidityV1(None, 1_000_000, 2_000_000),
        classification=CLS_PUBLIC, requires_hitl=False,
        claim_id=b"\x01" * 16,
    )
    base.update(kw)
    return DacV1(**base)


# --- prev is inside the signature (approved change C1) --------------------- #
def test_signature_covers_prev():
    """A producer attests to its own position in the chain.

    The legacy envelope excluded prev_hash from the signature, so an attacker
    who could re-link a record kept a valid producer signature. CADUCEUS-004 T1
    and EPHEMERIS A7(3) both require the predecessor hash to be signed.
    """
    env = make(prev=codec.GENESIS_PREV).sign(SK)
    assert env.verify()
    relinked = make(prev=b"\x02" + b"\x00" * 31)
    relinked.signature = env.signature          # replay the signature verbatim
    assert not relinked.verify()


def test_prev_appears_in_signing_bytes():
    a = make(prev=b"\x00" * 32).signing_bytes()
    b = make(prev=b"\x01" * 32).signing_bytes()
    assert a != b


# --- domain separation ----------------------------------------------------- #
def test_domain_separation_blocks_cross_replay():
    """A signature made under the chain domain must not verify a DAC."""
    env = make()
    env.signature = codec.sign(SK, codec.DOMAIN_CHAIN, env.to_map())
    assert not env.verify()
    env.signature = codec.sign(SK, codec.DOMAIN_DAC, env.to_map())
    assert env.verify()


def test_signing_bytes_start_with_the_domain_tag():
    assert make().signing_bytes().startswith(codec.DOMAIN_DAC)


# --- the envelope is self-verifiable --------------------------------------- #
def test_envelope_carries_a_usable_public_key():
    """A peer holding only the envelope can check the signature.

    The legacy 16-hex-character producer_fpr identified a producer but could
    never verify one.
    """
    env = make().sign(SK)
    rebuilt = DacV1.decode(env.encode())
    assert rebuilt.verify()                       # no key supplied
    assert rebuilt.producer_pk == PK_RAW


# --- strict schema --------------------------------------------------------- #
def test_unknown_top_level_key_is_rejected_not_ignored():
    m = make().to_map()
    m["surprise"] = 1
    with pytest.raises(SchemaError, match="unknown key"):
        DacV1.from_map(m)


def test_unknown_nested_keys_are_rejected():
    m = make().to_map()
    m["conf"]["zzz"] = 1
    with pytest.raises(SchemaError, match="unknown key"):
        DacV1.from_map(m)


def test_regulated_without_hitl_is_rejected_at_schema_level():
    m = make(classification=CLS_REGULATED, requires_hitl=True).to_map()
    m["hitl"] = False
    with pytest.raises(SchemaError, match="REGULATED"):
        DacV1.from_map(m)


def test_expiry_before_issue_is_rejected():
    m = make().to_map()
    m["val"]["exp"] = 0
    with pytest.raises(SchemaError, match="precedes"):
        DacV1.from_map(m)


def test_ppm_out_of_range_is_rejected():
    m = make().to_map()
    m["conf"]["v"] = 1_000_001
    with pytest.raises(SchemaError, match="ppm"):
        DacV1.from_map(m)


def test_parents_must_be_sorted_and_unique():
    a, b = b"\x01" * 16, b"\x02" * 16
    m = make().to_map()
    m["par"] = [b, a]
    with pytest.raises(SchemaError, match="sorted"):
        DacV1.from_map(m)
    m["par"] = [a, a]
    with pytest.raises(SchemaError, match="duplicate"):
        DacV1.from_map(m)


def test_empty_parent_set_is_valid():
    env = make(parents=[]).sign(SK)
    assert env.verify()
    assert DacV1.decode(env.encode()).parents == []


# --- projection is lossless ------------------------------------------------ #
def test_projection_round_trip_preserves_the_record_hash():
    env = make(parents=[b"\x01" * 16, b"\x02" * 16],
               confidence=ConfidenceV1("split_conformal", 920000, 80000,
                                       interval=[[-1, -9], [1, -9]]),
               ext={"note": "x"}).sign(SK)
    rebuilt = from_projection(to_projection(env))
    assert rebuilt.record_hash() == env.record_hash()
    assert rebuilt.signing_bytes() == env.signing_bytes()
    assert rebuilt.verify()


# --- monotone propagation, exact on integers ------------------------------- #
def _parent(value_ppm, alpha_ppm, iat, exp, cls, hitl, status=STATUS_VALID):
    return make(confidence=ConfidenceV1("asserted", value_ppm, alpha_ppm),
                validity=ValidityV1(None, iat, exp, status),
                classification=cls, requires_hitl=hitl)


def test_confidence_is_the_weakest_link():
    r = propagate(value_ppm=950000, alpha_ppm=50000, issued_at_us=0,
                  expires_at_us=10, classification=0, requires_hitl=False,
                  parents=[_parent(920000, 80000, 0, 10, 0, False)])
    assert r["value_ppm"] == 920000


def test_alpha_is_the_loosest_link():
    """Coverage taking the min while alpha kept the child's own value was
    incoherent: a derived claim could report value=0.92 with alpha=0.05."""
    r = propagate(value_ppm=950000, alpha_ppm=50000, issued_at_us=0,
                  expires_at_us=10, classification=0, requires_hitl=False,
                  parents=[_parent(920000, 80000, 0, 10, 0, False)])
    assert r["alpha_ppm"] == 80000


def test_validity_is_the_intersection():
    r = propagate(value_ppm=1000000, alpha_ppm=0, issued_at_us=100,
                  expires_at_us=900, classification=0, requires_hitl=False,
                  parents=[_parent(1000000, 0, 200, 800, 0, False),
                           _parent(1000000, 0, 150, 700, 0, False)])
    assert (r["issued_at_us"], r["expires_at_us"]) == (200, 700)


def test_classification_takes_the_maximum_and_forces_hitl():
    r = propagate(value_ppm=1000000, alpha_ppm=0, issued_at_us=0,
                  expires_at_us=10, classification=CLS_PUBLIC, requires_hitl=False,
                  parents=[_parent(1000000, 0, 0, 10, CLS_REGULATED, False)])
    assert r["classification"] == CLS_REGULATED
    assert r["requires_hitl"] is True


def test_a_stale_parent_makes_the_child_stale():
    r = propagate(value_ppm=1000000, alpha_ppm=0, issued_at_us=0,
                  expires_at_us=10, classification=0, requires_hitl=False,
                  parents=[_parent(1000000, 0, 0, 10, 0, False, status=STATUS_STALE)])
    assert r["status"] == STATUS_STALE


def test_disjoint_parent_windows_produce_a_stale_claim_not_an_error():
    r = propagate(value_ppm=1000000, alpha_ppm=0, issued_at_us=0,
                  expires_at_us=1000, classification=0, requires_hitl=False,
                  parents=[_parent(1000000, 0, 0, 100, 0, False),
                           _parent(1000000, 0, 500, 900, 0, False)])
    assert r["expires_at_us"] == r["issued_at_us"] == 500
    assert r["status"] == STATUS_STALE


def test_propagation_is_exact_on_integers():
    """min/max/intersection on ints have none of the float comparison edge
    cases; the invariant holds exactly rather than to within a tolerance."""
    r = propagate(value_ppm=920001, alpha_ppm=79999, issued_at_us=0,
                  expires_at_us=10, classification=0, requires_hitl=False,
                  parents=[_parent(920000, 80000, 0, 10, 0, False)])
    assert r["value_ppm"] == 920000 and r["alpha_ppm"] == 80000
