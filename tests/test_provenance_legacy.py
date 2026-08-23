"""Legacy v0 formats — historical artifacts must keep verifying, unmodified.

Chains are append-only across this portfolio. Nothing here re-signs, migrates,
or rewrites a historical entry; every function under test is read-only.

Tests that need a sibling repository skip when it is absent, so this suite runs
standalone in aletheia-dac CI and does full cross-repo verification locally.
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from aletheia.provenance import legacy

# --- sibling repository discovery ------------------------------------------ #
_PORTFOLIO_ENV = "ZIL_PORTFOLIO_ROOT"


def portfolio_root() -> Path:
    """Directory holding the five repositories, if it can be located."""
    env = os.environ.get(_PORTFOLIO_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def sibling(name: str) -> Path:
    p = portfolio_root() / name
    if not p.exists():
        pytest.skip(f"sibling repository {name} not present "
                    f"(set {_PORTFOLIO_ENV} to enable cross-repo verification)")
    return p


# --- v0-zil-ledger: real signed history ------------------------------------ #
def test_proteus_ledger_0004_still_verifies_unmodified():
    """The one genuinely signed historical artifact in the portfolio.

    Falsification target: a shared-core change that breaks a signature made
    before the core existed.
    """
    repo = sibling("Proteus")
    report = legacy.verify_zil_ledger(
        str(repo / "LEDGER_0004.json"),
        str(repo / "keys" / "visionblox-release-key-v1.pub"))
    assert report["ok"], report["defects"]
    assert report["signature"] == "VALID"
    assert report["format"] == legacy.TAG_ZIL_LEDGER
    assert report["ledger_entry_number"] == 4


def test_zil_canonical_form_differs_from_the_other_two():
    """Three implementations called their form "canonical JSON"; two of them
    produced different bytes for the same non-ASCII input.

    zil_sign.py uses ensure_ascii=False (raw UTF-8); aletheia-dac and PHRONESIS
    use the default (\\uXXXX escapes). This is a real, latent signing divergence
    in the legacy formats and is why v1 fixes the encoding by specification.
    """
    payload = {"title": "Café — Mañana"}
    zil = legacy.zil_canonical(payload)
    other = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert zil != other
    assert "Café".encode("utf-8") in zil
    assert b"\\u00e9" in other


# --- v0-phronesis-unsigned: the premise that did not hold ------------------ #
def test_phronesis_ledger_carries_no_signature():
    """VERIFIED finding, recorded rather than papered over.

    The Track A brief and ALETHEIA-PORTFOLIO-001 Section 4 both describe
    VBX_ISPS_LEDGER_0001-0005 as "signed history". They are not signed. This
    test pins the actual state so the claim cannot drift back.
    """
    repo = sibling("PHRONESIS-1")
    paths = sorted((repo / "ledger").glob("VBX_ISPS_LEDGER_*.json"))
    assert len(paths) == 5
    report = legacy.verify_phronesis_ledger([str(p) for p in paths],
                                            repo_root=str(repo / "substrate"))
    assert report["signature_status"] == "ABSENT"
    for entry in report["entries"]:
        assert entry["signature"] == "ABSENT"
        assert "PLACEHOLDER" in str(entry["signing_key_field"]) or \
               entry["signing_key_field"] == "<absent>"


def test_phronesis_ledger_linkage_holds():
    """What CAN be verified: each entry names its predecessor's commit root."""
    repo = sibling("PHRONESIS-1")
    paths = sorted((repo / "ledger").glob("VBX_ISPS_LEDGER_*.json"))
    report = legacy.verify_phronesis_ledger([str(p) for p in paths],
                                            repo_root=str(repo / "substrate"))
    linkage = [d for d in report["defects"] if d["defect"] == "predecessor_root_mismatch"]
    assert not linkage, linkage


def test_phronesis_ledger_has_two_incompatible_schemas():
    """0001-0003 and 0004-0005 do not share a schema; the reader normalizes."""
    repo = sibling("PHRONESIS-1")
    paths = sorted((repo / "ledger").glob("VBX_ISPS_LEDGER_*.json"))
    report = legacy.verify_phronesis_ledger([str(p) for p in paths])
    variants = [e["schema_variant"] for e in report["entries"]]
    assert variants == ["A", "A", "A", "B", "B"]


# --- v0-loop-b: format-pinned by a frozen auditor -------------------------- #
def test_loop_b_hash_matches_the_frozen_bundle_auditor():
    """The preimage must stay byte-identical to the committed auditor.

    proteus-bench-v1.0.2/auditor/verify_chain.py is inside a hash-committed
    benchmark bundle and cannot be edited, so Loop B stays on v0 forever. The
    shared core reproduces its construction rather than replacing it.
    """
    prev, state, signals, ts = "GENESIS", '{"a":1}', '{"b":2}', "2026-08-23T00:00:00Z"
    import hashlib
    expected = hashlib.sha256((prev + state + signals + ts).encode()).hexdigest()
    assert legacy.loop_b_row_hash(prev, state, signals, ts) == expected


def test_loop_b_preimage_is_unframed_and_ambiguous():
    """FINDING, recorded as a back-edge candidate rather than fixed.

    The four components are concatenated with no length prefixes and no
    separators, so distinct (state, signals) pairs produce the same preimage.
    v1 removes the class by using a length-delimited encoding; the frozen
    auditor means v0 cannot be repaired in place.
    """
    ts = "2026-08-23T00:00:00Z"
    a = legacy.loop_b_row_hash("GENESIS", '{"ab":1}', '{}', ts)
    b = legacy.loop_b_row_hash("GENESIS", '{"ab"', ':1}{}', ts)
    assert a == b, "the collision this test documents should exist in v0"


# --- v0 store readers ------------------------------------------------------ #
def test_dac_json_signing_bytes_exclude_sig_and_prev():
    """The legacy envelope deliberately left prev_hash outside the signature."""
    d = {"kind": "k", "sig": "aa", "prev_hash": "bb", "id": "x"}
    b = legacy.dac_json_signing_bytes(d)
    assert b == b'{"id":"x","kind":"k"}'


def test_phronesis_entry_hash_matches_the_legacy_construction():
    import hashlib
    body = {"seq": 0, "timestamp_ns": 1, "event_type": "E",
            "event_payload": {"i": 1}, "prev_hash": "0" * 64}
    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert legacy.phronesis_entry_hash(0, 1, "E", {"i": 1}, "0" * 64) == expected


def test_legacy_readers_never_write(tmp_path):
    """Read-only by construction: verifying must not modify the artifact."""
    db = tmp_path / "state.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE state_chain (turn_id INTEGER PRIMARY KEY, ts TEXT,"
                " state_json TEXT, signals_json TEXT, prev_hash TEXT,"
                " hash TEXT, sig TEXT)")
    h = legacy.loop_b_row_hash("GENESIS", "{}", "{}", "t")
    con.execute("INSERT INTO state_chain VALUES (0,'t','{}','{}','GENESIS',?,'00')", (h,))
    con.commit()
    con.close()
    before = db.read_bytes()
    legacy.verify_loop_b_chain(str(db))
    assert db.read_bytes() == before
