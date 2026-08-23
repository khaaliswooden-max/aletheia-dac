"""
verifier.py — one verifier for every chain in the portfolio.

Track A deliverable 4 and Wave 1 definition-of-done item 1: a single tool that
validates a chain produced by any of the five substrates and reports which
format version each entry uses.

It detects the format from the artifact itself rather than being told:

    SQLite table 'claims'      -> aletheia-dac DAC store (v1, or v0-dac-json)
    SQLite table 'chain'       -> PHRONESIS Aletheia chain (v1, or v0-phronesis-chain)
    SQLite table 'state_chain' -> Proteus Loop B (v0-loop-b; format-pinned)
    JSON with payload+signature_ed25519_hex -> Proteus release ledger (v0-zil-ledger)
    JSON with commit_root[_sha256]          -> PHRONESIS ledger (v0-phronesis-unsigned)

Every report carries the format tag per entry, so a mixed-format chain reads
honestly instead of being flattened to a single verdict.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import attest, cbor, codec, legacy
from .envelope import DacV1, from_projection
from .entry import EntryV1

FORMAT_V1_DAC = "v1-dac"
FORMAT_V1_CHAIN = "v1-chain"


class UnknownArtifact(ValueError):
    """Raised when an artifact matches no known chain format."""


def _sqlite_tables(path: str) -> set:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def detect(path: str) -> str:
    """Identify an artifact's chain format.

    Postcondition: the returned tag is one of the v1 tags or legacy.TAGS.
    Raises UnknownArtifact when nothing matches.
    """
    p = Path(path)
    if not p.exists():
        raise UnknownArtifact(f"no such artifact: {path}")

    tables = _sqlite_tables(str(p))
    if "claims" in tables:
        return FORMAT_V1_DAC if _claims_is_v1(str(p)) else legacy.TAG_DAC_JSON
    if "chain" in tables:
        return FORMAT_V1_CHAIN if _chain_is_v1(str(p)) else legacy.TAG_PHRONESIS_CHAIN
    if "state_chain" in tables:
        return legacy.TAG_LOOP_B

    try:
        d = json.loads(p.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnknownArtifact(f"{path}: not a recognized chain artifact ({exc})") from exc
    if isinstance(d, dict):
        if "payload" in d and "signature_ed25519_hex" in d:
            return legacy.TAG_ZIL_LEDGER
        if "commit_root" in d or "commit_root_sha256" in d:
            return legacy.TAG_PHRONESIS_UNSIGNED
    raise UnknownArtifact(f"{path}: not a recognized chain artifact")


def _column_names(path: str, table: str) -> list:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    finally:
        con.close()


def _claims_is_v1(path: str) -> bool:
    return "fmt" in _column_names(path, "claims")


def _chain_is_v1(path: str) -> bool:
    """The PHRONESIS chain table's column count is fixed by its own HF-8
    red-team test, which inserts positionally with seven values. The format
    version therefore lives in a `chain_meta` side table rather than a column."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT value FROM chain_meta WHERE key='format'").fetchone()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return bool(row) and row[0] == "zil-provenance-v1"


# --------------------------------------------------------------------------- #
# v1 readers                                                                   #
# --------------------------------------------------------------------------- #
def verify_v1_dac_store(db_path: str, keystore=None) -> dict:
    """Verify a v1 DAC store: signatures, record hashes, and chain linkage.

    With a keystore, each envelope's embedded public key is additionally checked
    against the trust root, because a self-carried key proves consistency but
    not authority.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT json, rec_hash, prev_hash FROM claims ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    entries, defects = [], []
    prev = codec.GENESIS_PREV
    for i, (j, rec_hex, prev_hex) in enumerate(rows):
        item = {"index": i, "format": FORMAT_V1_DAC}
        try:
            env = from_projection(json.loads(j))
        except Exception as exc:  # unparseable or schema-invalid == tampered
            defects.append({"index": i, "defect": f"invalid_envelope:{exc}"})
            entries.append({**item, "ok": False})
            prev = bytes.fromhex(rec_hex) if rec_hex else prev
            continue
        item["id"] = env.claim_id.hex()
        item["kind"] = env.kind
        item["producer"] = env.producer_id
        if env.prev != prev:
            defects.append({"index": i, "defect": "prev_mismatch"})
        computed = env.record_hash()
        if computed.hex() != rec_hex:
            defects.append({"index": i, "defect": "record_hash_mismatch"})
        report = env.verify_signatures()
        item["signature"] = report["author_signature"]
        item["attestors"] = len(report["attestors_valid"])
        if report["author_signature"] != "VALID":
            defects.append({"index": i, "defect": "signature_invalid"})
        for problem in report["problems"]:
            if problem != "author_signature_invalid":
                defects.append({"index": i, "defect": problem})
        if keystore is not None:
            trusted = keystore.is_trusted(env.producer_id, env.producer_pk)
            item["trust"] = "TRUSTED" if trusted else "UNTRUSTED_KEY"
            if not trusted:
                defects.append({"index": i, "defect": "producer_key_not_in_trust_root"})
        item["ok"] = not any(x["index"] == i for x in defects)
        entries.append(item)
        prev = computed
    return {"format": FORMAT_V1_DAC, "entry_count": len(rows),
            "entries": entries, "defects": defects, "ok": not defects}


def verify_v1_chain(db_path: str, public_key=None) -> dict:
    """Verify a v1 chain-entry database (PHRONESIS storage schema)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT seq, timestamp_ns, event_type, event_payload, prev_hash, "
            "entry_hash, signature_hex FROM chain ORDER BY seq ASC"
        ).fetchall()
    finally:
        con.close()

    entries, defects = [], []
    expected_prev, expected_seq = codec.GENESIS_PREV, 0
    for (seq, ts_ns, et, ep_json, prev_hex, eh_hex, sig_hex) in rows:
        idx = len(entries)
        item = {"index": idx, "seq": seq, "format": FORMAT_V1_CHAIN, "event_type": et}
        if seq != expected_seq:
            defects.append({"index": idx, "seq": seq, "defect": "sequence_break"})
        # The payload column IS the attested bytes; it is never re-serialized.
        entry = EntryV1(seq=seq, ts_us=ts_ns // 1000, event_type=et,
                        payload=ep_json.encode("utf-8") if isinstance(ep_json, str)
                        else bytes(ep_json),
                        prev=bytes.fromhex(prev_hex), ext={"ts_ns": ts_ns})
        try:
            entry.signatures = attest.SignatureSet.from_map(
                cbor.decode(bytes.fromhex(sig_hex)))
        except Exception as exc:
            defects.append({"index": idx, "seq": seq,
                            "defect": f"invalid_signature_set:{type(exc).__name__}"})
            entries.append({**item, "ok": False})
            expected_prev = bytes.fromhex(eh_hex)
            expected_seq = seq + 1
            continue
        if entry.prev != expected_prev:
            defects.append({"index": idx, "seq": seq, "defect": "prev_hash_mismatch"})
        computed = entry.record_hash()
        if computed.hex() != eh_hex:
            defects.append({"index": idx, "seq": seq, "defect": "entry_hash_mismatch"})
        report = entry.verify_signatures()
        item["signature"] = report["author_signature"]
        item["attestors"] = len(report["attestors_valid"])
        item["threshold_required"] = report["threshold_required"]
        if report["author_signature"] != "VALID":
            defects.append({"index": idx, "seq": seq, "defect": "signature_invalid"})
        for problem in report["problems"]:
            if problem != "author_signature_invalid":
                defects.append({"index": idx, "seq": seq, "defect": problem})
        if public_key is not None and not entry.verify(public_key):
            # The set verifies against the key it carries; this checks the
            # author signature against the key the CALLER expects.
            defects.append({"index": idx, "seq": seq,
                            "defect": "author_key_mismatch"})
        item["ok"] = not any(x["index"] == idx for x in defects)
        entries.append(item)
        expected_prev, expected_seq = computed, seq + 1
    return {"format": FORMAT_V1_CHAIN, "entry_count": len(rows),
            "entries": entries, "defects": defects, "ok": not defects}


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #
def verify(path: str, *, public_key=None, public_keys=None, keystore=None,
           pubkey_path=None, repo_root=None) -> dict:
    """Verify any portfolio chain artifact, detecting its format.

    Inputs:
      path         the artifact (SQLite database or JSON ledger entry)
      public_key   an Ed25519PublicKey, for the single-key chain formats
      public_keys  {producer_id: Ed25519PublicKey}, for legacy DAC stores
      keystore     a Keystore, to check v1 producer keys against a trust root
      pubkey_path  PEM public key path, for the Proteus release ledger
      repo_root    repository root, to check PHRONESIS manifest hashes

    Outputs: a report dict; ``report["format"]`` names the detected format and
    every entry carries its own format tag.
    """
    fmt = detect(path)
    if fmt == FORMAT_V1_DAC:
        return verify_v1_dac_store(path, keystore=keystore)
    if fmt == FORMAT_V1_CHAIN:
        return verify_v1_chain(path, public_key=public_key)
    if fmt == legacy.TAG_DAC_JSON:
        return legacy.verify_dac_json_store(path, public_keys=public_keys)
    if fmt == legacy.TAG_PHRONESIS_CHAIN:
        return legacy.verify_phronesis_chain(path, public_key=public_key)
    if fmt == legacy.TAG_LOOP_B:
        return legacy.verify_loop_b_chain(path, public_key=public_key)
    if fmt == legacy.TAG_ZIL_LEDGER:
        if not pubkey_path:
            raise UnknownArtifact(
                "the Proteus release ledger needs --pubkey to verify its signature")
        return legacy.verify_zil_ledger(path, pubkey_path)
    if fmt == legacy.TAG_PHRONESIS_UNSIGNED:
        return legacy.verify_phronesis_ledger([path], repo_root=repo_root)
    raise UnknownArtifact(f"no verifier for format {fmt}")


def summarize(report: dict) -> str:
    """One-line human summary of a verification report."""
    formats = sorted({e.get("format", report["format"]) for e in report.get("entries", [])}) \
        or [report["format"]]
    sigs = sorted({e.get("signature") for e in report.get("entries", [])
                   if e.get("signature")}) or [report.get("signature", "n/a")]
    verdict = "OK" if report["ok"] else f"{len(report['defects'])} DEFECT(S)"
    return (f"{report['entry_count']} entr{'y' if report['entry_count'] == 1 else 'ies'} · "
            f"format {'+'.join(formats)} · signature {'+'.join(str(s) for s in sigs)} · {verdict}")
