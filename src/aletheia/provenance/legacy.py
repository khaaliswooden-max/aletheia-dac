"""
legacy.py — read-only verifiers for the five pre-v1 formats.

Chains are append-only across this portfolio. Historical entries are VERIFIED
under a v0 tag and are never re-signed, migrated, or rewritten. Nothing in this
module writes; every function reads and reports.

The five tags:

  v0-dac-json            aletheia-dac DAC envelopes (src/aletheia/dac.py)
  v0-phronesis-chain     PHRONESIS AletheiaChain rows (substrate/src/aletheia/chain.py)
  v0-zil-ledger          Proteus release ledger entries (zil_sign.py)
  v0-loop-b              Proteus Loop B state-chain rows (loop_a/chain.py)
  v0-phronesis-unsigned  PHRONESIS VBX_ISPS_LEDGER_*.json

A finding on the last tag, recorded here because it contradicts a stated
premise of the Track A brief and of ALETHEIA-PORTFOLIO-001 Section 4:

    VERIFIED, by direct inspection 2026-08-23 -- VBX_ISPS_LEDGER_0001 through
    0005 are NOT signed. Every one carries
    "signing_key": "PLACEHOLDER - production key custody required ...",
    no signature field, and no public key exists anywhere in that repository.
    They also use two incompatible schemas: 0001-0003 carry commit_id /
    artifacts[] / commit_root_sha256, while 0004-0005 carry ledger_number /
    manifest_sha256{} / commit_root.

    They therefore cannot be cryptographically verified under any tag. This
    module verifies what is actually there -- predecessor linkage and manifest
    integrity -- and reports signature status as ABSENT rather than passing
    them silently. PHRONESIS-1 GOVERNANCE Section 7.3 ("no ceremony exists
    anywhere") is the accurate description; the "signed history" claim is not.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

TAG_DAC_JSON = "v0-dac-json"
TAG_PHRONESIS_CHAIN = "v0-phronesis-chain"
TAG_ZIL_LEDGER = "v0-zil-ledger"
TAG_LOOP_B = "v0-loop-b"
TAG_PHRONESIS_UNSIGNED = "v0-phronesis-unsigned"

TAGS = (TAG_DAC_JSON, TAG_PHRONESIS_CHAIN, TAG_ZIL_LEDGER,
        TAG_LOOP_B, TAG_PHRONESIS_UNSIGNED)


def _ed25519_ok(public_key, signature: bytes, message: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


# --------------------------------------------------------------------------- #
# v0-dac-json                                                                  #
# --------------------------------------------------------------------------- #
def dac_json_signing_bytes(d: dict) -> bytes:
    """Reproduce the legacy DAC signing bytes exactly.

    The legacy envelope signed ``asdict(dac)`` minus ``sig`` and ``prev_hash``,
    as compact JSON with sorted keys and ensure_ascii=True. ``prev_hash`` was
    deliberately excluded so the store could link records after signing; v1
    moves it inside the signature.
    """
    d = dict(d)
    d.pop("sig", None)
    d.pop("prev_hash", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def dac_json_record_hash(d: dict) -> str:
    return hashlib.sha256(
        dac_json_signing_bytes(d) + d.get("sig", "").encode()
        + d.get("prev_hash", "").encode()
    ).hexdigest()


def verify_dac_json_store(db_path: str, public_keys: dict | None = None) -> dict:
    """Verify a legacy aletheia-dac ClaimStore: hash chain, and signatures if keys given.

    Inputs:  path to the SQLite store; optional {producer_id: Ed25519PublicKey}.
    Outputs: a report dict with per-entry results and an overall verdict.
    """
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT json, rec_hash, prev_hash FROM claims ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    entries, defects = [], []
    prev = ""
    for i, (j, rec, ph) in enumerate(rows):
        item = {"index": i, "format": TAG_DAC_JSON}
        try:
            d = json.loads(j)
        except json.JSONDecodeError as exc:
            defects.append({"index": i, "defect": f"unparseable_json:{exc}"})
            entries.append({**item, "ok": False})
            continue
        item["id"] = d.get("id")
        if d.get("prev_hash", "") != prev:
            defects.append({"index": i, "defect": "prev_hash_mismatch"})
        if dac_json_record_hash(d) != rec:
            defects.append({"index": i, "defect": "record_hash_mismatch"})
        if public_keys and d.get("producer_id") in public_keys:
            ok = _ed25519_ok(public_keys[d["producer_id"]],
                             bytes.fromhex(d.get("sig", "")),
                             dac_json_signing_bytes(d))
            item["signature"] = "VALID" if ok else "INVALID"
            if not ok:
                defects.append({"index": i, "defect": "signature_invalid"})
        else:
            # Legacy producer keys were ephemeral per process, so a stored
            # envelope usually has no recoverable key. That is a property of the
            # format, not a verification failure.
            item["signature"] = "UNCHECKED_NO_KEY"
        item["ok"] = not any(x["index"] == i for x in defects)
        entries.append(item)
        prev = rec
    return {"format": TAG_DAC_JSON, "entry_count": len(rows),
            "entries": entries, "defects": defects, "ok": not defects}


# --------------------------------------------------------------------------- #
# v0-phronesis-chain                                                           #
# --------------------------------------------------------------------------- #
def phronesis_entry_hash(seq, timestamp_ns, event_type, event_payload, prev_hash) -> str:
    body = {"seq": seq, "timestamp_ns": timestamp_ns, "event_type": event_type,
            "event_payload": event_payload, "prev_hash": prev_hash}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_phronesis_chain(db_path: str, public_key=None) -> dict:
    """Verify a legacy PHRONESIS AletheiaChain database."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT seq, timestamp_ns, event_type, event_payload, prev_hash, "
            "entry_hash, signature_hex FROM chain ORDER BY seq ASC"
        ).fetchall()
    finally:
        con.close()

    entries, defects = [], []
    expected_prev, expected_seq = "0" * 64, 0
    for (seq, ts, et, ep_json, ph, eh, sig) in rows:
        idx = len(entries)
        if seq != expected_seq:
            defects.append({"index": idx, "seq": seq, "defect": "sequence_break"})
        if ph != expected_prev:
            defects.append({"index": idx, "seq": seq, "defect": "prev_hash_mismatch"})
        try:
            ep = json.loads(ep_json)
        except json.JSONDecodeError:
            defects.append({"index": idx, "seq": seq, "defect": "unparseable_payload"})
            ep = None
        if ep is not None and phronesis_entry_hash(seq, ts, et, ep, ph) != eh:
            defects.append({"index": idx, "seq": seq, "defect": "entry_hash_mismatch"})
        item = {"index": idx, "seq": seq, "format": TAG_PHRONESIS_CHAIN,
                "event_type": et}
        if public_key is not None:
            ok = _ed25519_ok(public_key, bytes.fromhex(sig), bytes.fromhex(eh))
            item["signature"] = "VALID" if ok else "INVALID"
            if not ok:
                defects.append({"index": idx, "seq": seq, "defect": "signature_invalid"})
        else:
            item["signature"] = "UNCHECKED_NO_KEY"
        item["ok"] = not any(x["index"] == idx for x in defects)
        entries.append(item)
        expected_prev, expected_seq = eh, seq + 1
    return {"format": TAG_PHRONESIS_CHAIN, "entry_count": len(rows),
            "entries": entries, "defects": defects, "ok": not defects}


# --------------------------------------------------------------------------- #
# v0-zil-ledger                                                                #
# --------------------------------------------------------------------------- #
def zil_canonical(payload: dict) -> bytes:
    """The Proteus release-ledger canonical form.

    Note ensure_ascii=False: this is raw UTF-8, where aletheia-dac and PHRONESIS
    both emit \\uXXXX escapes. Three implementations called their form
    "canonical JSON" and two of them produced different bytes for the same
    non-ASCII input. VERIFIED by tests/test_provenance_legacy.py.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def verify_zil_ledger(entry_path: str, pubkey_path: str) -> dict:
    """Verify one Proteus LEDGER_NNNN.json against its published public key."""
    from cryptography.hazmat.primitives import serialization

    entry = json.loads(Path(entry_path).read_text())
    pub = serialization.load_pem_public_key(Path(pubkey_path).read_bytes())
    cbytes = zil_canonical(entry["payload"])

    defects = []
    computed = hashlib.sha256(cbytes).hexdigest()
    if computed != entry.get("payload_sha256"):
        defects.append({"defect": "payload_sha256_mismatch",
                        "computed": computed,
                        "recorded": entry.get("payload_sha256")})
    sig_ok = _ed25519_ok(pub, bytes.fromhex(entry["signature_ed25519_hex"]), cbytes)
    if not sig_ok:
        defects.append({"defect": "signature_invalid"})
    return {
        "format": TAG_ZIL_LEDGER,
        "path": str(entry_path),
        "entry_count": 1,
        "ledger_entry_number": entry["payload"].get("ledger_entry_number"),
        "prev_ledger_hash": entry["payload"].get("prev_ledger_hash"),
        "payload_sha256": entry.get("payload_sha256"),
        "signature": "VALID" if sig_ok else "INVALID",
        "defects": defects,
        "ok": not defects,
    }


# --------------------------------------------------------------------------- #
# v0-loop-b                                                                    #
# --------------------------------------------------------------------------- #
def loop_b_row_hash(prev_hash: str, state_json: str, signals_json: str, ts: str) -> str:
    """The Proteus Loop B preimage, reproduced byte-for-byte.

    FINDING, recorded rather than fixed: this preimage is unframed. There are no
    length prefixes and no separators between the four components, so the field
    boundaries are ambiguous and distinct (state, signals, ts) triples can in
    principle collide. It cannot be changed -- the auditor inside the frozen
    bundle proteus-bench-v1.0.2/auditor/verify_chain.py computes exactly this,
    and the benchmark is not editable. Recorded as a back-edge candidate in
    docs/BACK_EDGE_CANDIDATES.md; v1 removes the class by using a
    length-delimited encoding.
    """
    return hashlib.sha256((prev_hash + state_json + signals_json + ts).encode()).hexdigest()


def verify_loop_b_chain(db_path: str, public_key=None) -> dict:
    """Verify a Proteus Loop B state chain, matching the frozen bundle auditor."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT turn_id, ts, state_json, signals_json, prev_hash, hash, sig "
            "FROM state_chain ORDER BY turn_id ASC"
        ).fetchall()
    finally:
        con.close()

    entries, defects = [], []
    prev = "GENESIS"
    for (turn_id, ts, sj, gj, ph, h, sig) in rows:
        idx = len(entries)
        if ph != prev:
            defects.append({"index": idx, "turn_id": turn_id, "defect": "linkage_break"})
        if loop_b_row_hash(ph, sj, gj, ts) != h:
            defects.append({"index": idx, "turn_id": turn_id, "defect": "hash_mismatch"})
        item = {"index": idx, "turn_id": turn_id, "format": TAG_LOOP_B}
        if public_key is not None:
            ok = _ed25519_ok(public_key, bytes.fromhex(sig), h.encode())
            item["signature"] = "VALID" if ok else "INVALID"
            if not ok:
                defects.append({"index": idx, "turn_id": turn_id,
                                "defect": "signature_invalid"})
        else:
            item["signature"] = "UNCHECKED_NO_KEY"
        item["ok"] = not any(x["index"] == idx for x in defects)
        entries.append(item)
        prev = h
    return {"format": TAG_LOOP_B, "entry_count": len(rows),
            "entries": entries, "defects": defects, "ok": not defects}


# --------------------------------------------------------------------------- #
# v0-phronesis-unsigned                                                        #
# --------------------------------------------------------------------------- #
def _phronesis_ledger_fields(d: dict) -> dict:
    """Normalize the two incompatible PHRONESIS ledger schemas to one shape."""
    if "commit_root_sha256" in d:          # 0001-0003
        return {"schema": "A",
                "number": d.get("commit_id"),
                "root": d.get("commit_root_sha256"),
                "predecessor_root": d.get("chain_predecessor_root_sha256"),
                "manifest": None}
    return {"schema": "B",                 # 0004-0005
            "number": d.get("ledger_number"),
            "root": d.get("commit_root"),
            "predecessor_root": d.get("predecessor_root"),
            "manifest": d.get("manifest_sha256")}


def verify_phronesis_ledger(paths: list, repo_root: str | None = None) -> dict:
    """Verify the PHRONESIS ledger for what it actually carries.

    Inputs:  ledger JSON paths in ascending entry order; optionally the repo
             root, so manifest_sha256 entries can be checked against real files.
    Outputs: a report with per-entry linkage and manifest results, and
             ``signature: "ABSENT"`` on every entry.

    Postcondition: this function never reports a cryptographic verification.
    These entries carry no signature to verify.
    """
    entries, defects = [], []
    expected_prev = None
    for i, p in enumerate(paths):
        d = json.loads(Path(p).read_text())
        f = _phronesis_ledger_fields(d)
        item = {"index": i, "path": str(p), "format": TAG_PHRONESIS_UNSIGNED,
                "schema_variant": f["schema"], "entry": f["number"],
                "commit_root": f["root"], "signature": "ABSENT",
                "signing_key_field": d.get("signing_key", "<absent>")}
        if expected_prev is not None and f["predecessor_root"] != expected_prev:
            defects.append({"index": i, "defect": "predecessor_root_mismatch",
                            "expected": expected_prev,
                            "recorded": f["predecessor_root"]})
        checked = mismatched = missing = 0
        if f["manifest"] and repo_root:
            for rel, want in sorted(f["manifest"].items()):
                fp = Path(repo_root) / rel
                if not fp.exists():
                    missing += 1
                    continue
                checked += 1
                if hashlib.sha256(fp.read_bytes()).hexdigest() != want:
                    mismatched += 1
                    defects.append({"index": i, "defect": "manifest_hash_mismatch",
                                    "file": rel})
        item["manifest_files_checked"] = checked
        item["manifest_files_missing"] = missing
        item["manifest_files_mismatched"] = mismatched
        item["ok"] = not any(x["index"] == i for x in defects)
        entries.append(item)
        expected_prev = f["root"]
    return {"format": TAG_PHRONESIS_UNSIGNED, "entry_count": len(entries),
            "entries": entries, "defects": defects, "ok": not defects,
            "signature_status": "ABSENT",
            "note": "These entries carry no signature. Linkage and manifest "
                    "integrity only; no cryptographic claim is made."}
