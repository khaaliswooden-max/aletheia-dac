"""The aletheia-dac adapter — v1 underneath, unchanged public API on top.

Falsification targets:
  * a public call signature or attribute that moved
  * a quantized value that drifts across a store round-trip
  * a claim whose signature survives being re-linked to a different predecessor
  * a store whose chain check passes on a tampered row
"""
import json
import sqlite3

import pytest

from aletheia.dac import (
    Classification, ClaimStore, Confidence, DAC, Producer, Substrate, Validity,
    _dac_from_dict,
)
from aletheia.provenance import Keystore, quantize, verifier


def pipeline(store):
    sub = Substrate(store)
    sensor, policy = Producer("sensor.l0"), Producer("policy.l5")
    for p in (sensor, policy):
        sub.register(p)
    s = sub.issue(kind="sensor_reading", payload=b"vitals:hr=88", producer=sensor,
                  confidence=Confidence("asserted", 0.99, 0.01),
                  classification=Classification.REGULATED,
                  monitor_id="stream_A", ttl_s=600)
    d = sub.issue(kind="policy_decision", payload=b"triage", producer=policy,
                  confidence=Confidence("asserted", 0.95, 0.05),
                  classification=Classification.PUBLIC, parents=[s])
    return sub, s, d


# --- the public surface did not move --------------------------------------- #
def test_legacy_attribute_names_still_read():
    _, s, d = pipeline(ClaimStore())
    for attr in ("id", "kind", "payload_hash", "producer_id", "producer_fpr",
                 "parents", "confidence", "validity", "classification",
                 "requires_hitl", "prev_hash", "sig"):
        assert hasattr(d, attr), attr
    assert isinstance(d.confidence.value, float)
    assert isinstance(d.validity.issued_at, float)
    assert isinstance(d.payload_hash, str) and len(d.payload_hash) == 64
    assert d.parents == [s.id]


def test_store_get_returns_the_legacy_shape():
    store = ClaimStore()
    _, s, d = pipeline(store)
    view = store.get(d.id)
    for key in ("kind", "payload_hash", "producer_id", "producer_fpr",
                "parents", "confidence", "validity", "classification",
                "requires_hitl", "id", "prev_hash", "sig"):
        assert key in view, key
    assert set(view["confidence"]) >= {"method", "value", "alpha", "interval"}
    assert set(view["validity"]) >= {"monitor_id", "issued_at", "expires_at", "status"}


# --- quantization is stable across the store ------------------------------- #
def test_ppm_survives_store_round_trip():
    """The integer is authoritative; a float rendering is a one-way view.

    Quantization is NOT idempotent through a float: for roughly half of all ppm
    values n, floor(exact(n / 1e6) * 1e6) != n. A store that re-derived the
    integer from a float on every read would drift downward one ppm at a time.
    """
    store = ClaimStore()
    _, s, d = pipeline(store)
    before = d.confidence.value_ppm
    for _ in range(5):
        rebuilt = _dac_from_dict(store.get(d.id))
        assert rebuilt.confidence.value_ppm == before
        assert rebuilt.validity.issued_at_us == d.validity.issued_at_us
        assert rebuilt.record_hash() == d.record_hash()


def test_the_naive_reduction_would_have_drifted():
    """Guard on the reason the design is the way it is."""
    import math
    drifted = sum(1 for n in range(900_000, 900_200)
                  if math.floor(quantize.exact(n / 1_000_000) * 1_000_000) != n)
    assert drifted > 0, "if this is ever 0, re-examine the float-view design"


def test_exact_rational_reduction_is_what_the_api_applies():
    c = Confidence("asserted", 0.99, 0.05)
    assert c.value_ppm == 989999      # the double is below 0.99
    assert c.alpha_ppm == 50001       # the double is above 0.05; alpha ceils
    assert Confidence("asserted", "0.99", "0.05").value_ppm == 990000


# --- prev is signed -------------------------------------------------------- #
def test_relinking_a_claim_breaks_its_signature():
    store = ClaimStore()
    sub, s, d = pipeline(store)
    assert sub.verify(d)
    d.prev_hash = "ab" * 32
    assert not sub.verify(d)


def test_issue_reads_the_head_before_signing():
    store = ClaimStore()
    sub, s, d = pipeline(store)
    assert s.prev_hash == "00" * 32                 # genesis
    assert d.prev_hash == s.record_hash()           # links to its predecessor
    assert store.verify_chain()


# --- tamper detection ------------------------------------------------------ #
@pytest.mark.parametrize("mutation", [
    '{"tampered": true}',
    "not json at all",
])
def test_chain_check_fails_on_a_corrupted_row(mutation):
    store = ClaimStore()
    _, s, d = pipeline(store)
    assert store.verify_chain()
    store.db.execute("UPDATE claims SET json=? WHERE id=?", (mutation, d.id))
    assert not store.verify_chain()


def test_chain_check_fails_when_a_field_is_edited_in_place():
    """A projection edit that stays schema-valid must still break the hash."""
    store = ClaimStore()
    _, s, d = pipeline(store)
    proj = json.loads(store.db.execute(
        "SELECT json FROM claims WHERE id=?", (d.id,)).fetchone()[0])
    proj["conf"]["v"] = 1_000_000            # inflate the coverage claim
    store.db.execute("UPDATE claims SET json=? WHERE id=?",
                     (json.dumps(proj), d.id))
    assert not store.verify_chain()


def test_cascade_stale_touches_only_the_status_column():
    """Audit integrity: the signed content is never mutated in place."""
    store = ClaimStore()
    _, s, d = pipeline(store)
    before = {r[0]: r[1] for r in store.db.execute("SELECT id, json FROM claims")}
    n = store.cascade_stale("stream_A")
    assert n == 2
    after = {r[0]: r[1] for r in store.db.execute("SELECT id, json FROM claims")}
    assert before == after, "cascade_stale must not rewrite stored claims"
    assert store.get(d.id)["validity"]["status"] == "STALE"
    assert store.verify_chain(), "chain must survive a legitimate status change"


# --- persistent keys ------------------------------------------------------- #
def test_a_keystore_backed_producer_survives_the_process(tmp_path):
    ks = Keystore(tmp_path / "ks")
    store = ClaimStore(str(tmp_path / "s.db"))
    sub = Substrate(store)
    p = Producer("sensor.l0", keystore=ks)
    sub.register(p)
    sub.issue(kind="k", payload=b"x", producer=p,
              confidence=Confidence("asserted", 0.9, 0.1),
              classification=Classification.PUBLIC)
    fpr = p.fingerprint

    # a "new process": fresh objects, same keystore directory
    ks2 = Keystore(tmp_path / "ks")
    p2 = Producer("sensor.l0", keystore=ks2)
    assert p2.fingerprint == fpr
    store2 = ClaimStore(str(tmp_path / "s.db"))
    assert store2.verify_chain()


def test_verifier_detects_and_validates_the_v1_store(tmp_path):
    store = ClaimStore(str(tmp_path / "s.db"))
    pipeline(store)
    report = verifier.verify(str(tmp_path / "s.db"))
    assert report["format"] == verifier.FORMAT_V1_DAC
    assert report["ok"], report["defects"]
    assert all(e["signature"] == "VALID" for e in report["entries"])


def test_verifier_reports_an_untrusted_producer_key(tmp_path):
    """Verifying an envelope proves consistency; authority is the trust check."""
    store = ClaimStore(str(tmp_path / "s.db"))
    pipeline(store)
    empty_trust = Keystore(tmp_path / "ks")
    report = verifier.verify(str(tmp_path / "s.db"), keystore=empty_trust)
    assert not report["ok"]
    assert any(d["defect"] == "producer_key_not_in_trust_root"
               for d in report["defects"])
