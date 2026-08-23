"""One verifier, every substrate.

Track A deliverable 4 and PORTFOLIO_BUILD_PLAN.md Section 10.1: a single tool
validates a chain produced by aletheia-dac, the PHRONESIS Aletheia chain, and
Proteus Loop B, and reports which format version each entry uses.

Tests needing a sibling repository skip when it is absent.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from aletheia.dac import Classification, ClaimStore, Confidence, Producer, Substrate
from aletheia.provenance import legacy, verifier

_PORTFOLIO_ENV = "ZIL_PORTFOLIO_ROOT"


def portfolio_root() -> Path:
    return Path(os.environ.get(_PORTFOLIO_ENV) or Path(__file__).resolve().parents[2])


def sibling(name: str) -> Path:
    p = portfolio_root() / name
    if not p.exists():
        pytest.skip(f"sibling repository {name} not present "
                    f"(set {_PORTFOLIO_ENV} to enable cross-repo verification)")
    return p


# --- aletheia-dac ---------------------------------------------------------- #
def _dac_store(path) -> str:
    store = ClaimStore(str(path))
    sub = Substrate(store)
    p = Producer("sensor.l0")
    sub.register(p)
    parent = sub.issue(kind="sensor_reading", payload=b"hr=88", producer=p,
                       confidence=Confidence("asserted", 0.99, 0.01),
                       classification=Classification.REGULATED, monitor_id="m")
    sub.issue(kind="policy_decision", payload=b"triage", producer=p,
              confidence=Confidence("asserted", 0.95, 0.05),
              classification=Classification.PUBLIC, parents=[parent])
    return str(path)


def test_verifies_an_aletheia_dac_chain(tmp_path):
    report = verifier.verify(_dac_store(tmp_path / "dac.db"))
    assert report["format"] == verifier.FORMAT_V1_DAC
    assert report["ok"], report["defects"]
    assert report["entry_count"] == 2


# --- PHRONESIS ------------------------------------------------------------- #
def _phronesis_chain(tmp_path):
    repo = sibling("PHRONESIS-1")
    sys.path.insert(0, str(repo / "substrate"))
    try:
        from src.aletheia.chain import AletheiaChain
    except ImportError as exc:              # pragma: no cover
        pytest.skip(f"PHRONESIS substrate not importable: {exc}")
    db, key = tmp_path / "phronesis.db", tmp_path / "key.pem"
    chain = AletheiaChain.open_or_create(db, key)
    for i in range(4):
        chain.append("GATE_DECISION", {"i": i, "o2_kpa": 19.0 + i * 0.1})
    chain.close()
    from cryptography.hazmat.primitives import serialization
    sk = serialization.load_pem_private_key(key.read_bytes(), password=None)
    return str(db), sk.public_key()


def test_verifies_a_phronesis_chain(tmp_path):
    db, pk = _phronesis_chain(tmp_path)
    report = verifier.verify(db, public_key=pk)
    assert report["format"] == verifier.FORMAT_V1_CHAIN
    assert report["ok"], report["defects"]
    assert all(e["signature"] == "VALID" for e in report["entries"])


def test_phronesis_float_telemetry_is_attested_as_opaque_bytes(tmp_path):
    """The no-float rule binds the envelope, not an attested payload blob."""
    db, pk = _phronesis_chain(tmp_path)
    con = sqlite3.connect(db)
    payload = con.execute("SELECT event_payload FROM chain LIMIT 1").fetchone()[0]
    con.close()
    assert "19.0" in payload
    assert verifier.verify(db, public_key=pk)["ok"]


def test_tampering_with_a_phronesis_payload_is_detected(tmp_path):
    db, pk = _phronesis_chain(tmp_path)
    con = sqlite3.connect(db)
    con.execute("UPDATE chain SET event_payload=? WHERE seq=1",
                (json.dumps({"i": 999}, sort_keys=True, separators=(",", ":")),))
    con.commit()
    con.close()
    report = verifier.verify(db, public_key=pk)
    assert not report["ok"]
    assert any(d["seq"] == 1 for d in report["defects"])


# --- Proteus Loop B -------------------------------------------------------- #
def _loop_b_chain(tmp_path):
    repo = sibling("Proteus")
    sys.path.insert(0, str(repo / "loop_a"))
    sys.path.insert(0, str(repo))
    try:
        from chain import StateChain, generate_test_keypair
    except ImportError as exc:              # pragma: no cover
        pytest.skip(f"Proteus loop_a not importable: {exc}")
    pub = tmp_path / "loopb.pub"
    priv = generate_test_keypair(str(pub))
    db = tmp_path / "episode.sqlite"
    chain = StateChain(str(db), priv)
    for turn in range(4):
        chain.append({"level": turn}, {"adaptation_event": turn % 2 == 0},
                     f"2026-08-23T00:00:0{turn}Z")
    chain.close()
    from cryptography.hazmat.primitives import serialization
    return str(db), serialization.load_pem_public_key(pub.read_bytes())


def test_verifies_a_proteus_loop_b_chain(tmp_path):
    """Loop B is format-pinned at v0 by a frozen benchmark auditor. The one
    verifier reads it under that tag rather than expecting v1."""
    db, pk = _loop_b_chain(tmp_path)
    report = verifier.verify(db, public_key=pk)
    assert report["format"] == legacy.TAG_LOOP_B
    assert report["ok"], report["defects"]
    assert all(e["signature"] == "VALID" for e in report["entries"])


def test_loop_b_agrees_with_the_frozen_bundle_auditor(tmp_path):
    """The shared core and the committed auditor must accept the same chain.

    This is the check that keeps a refactor from silently breaking a benchmark.
    """
    repo = sibling("Proteus")
    auditor = repo / "proteus-bench-v1.0.2" / "auditor" / "verify_chain.py"
    if not auditor.exists():                # pragma: no cover
        pytest.skip("frozen auditor not present")
    db, _ = _loop_b_chain(tmp_path)
    import importlib.util
    spec = importlib.util.spec_from_file_location("frozen_auditor", auditor)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.audit_chain(db, str(tmp_path / "loopb.pub"))
    assert result["ok"], result
    assert result["turns"] == 4


# --- Proteus release ledger ------------------------------------------------ #
def test_verifies_the_proteus_release_ledger():
    repo = sibling("Proteus")
    report = verifier.verify(
        str(repo / "LEDGER_0004.json"),
        pubkey_path=str(repo / "keys" / "visionblox-release-key-v1.pub"))
    assert report["format"] == legacy.TAG_ZIL_LEDGER
    assert report["ok"] and report["signature"] == "VALID"


# --- PHRONESIS ledger ------------------------------------------------------ #
def test_reports_the_phronesis_ledger_as_unsigned():
    repo = sibling("PHRONESIS-1")
    report = verifier.verify(str(repo / "ledger" / "VBX_ISPS_LEDGER_0005.json"))
    assert report["format"] == legacy.TAG_PHRONESIS_UNSIGNED
    assert report["signature_status"] == "ABSENT"


# --- detection ------------------------------------------------------------- #
def test_unknown_artifacts_are_reported_not_guessed(tmp_path):
    junk = tmp_path / "junk.txt"
    junk.write_text("this is not a chain")
    with pytest.raises(verifier.UnknownArtifact):
        verifier.detect(str(junk))


def test_every_report_names_the_format_of_each_entry(tmp_path):
    report = verifier.verify(_dac_store(tmp_path / "dac.db"))
    assert all("format" in e for e in report["entries"])
    assert "format" in verifier.summarize(report)
