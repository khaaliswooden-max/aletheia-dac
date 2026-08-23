"""The committed conformance vectors.

These are the contract between implementations. The Rust crate caduceus-attest
(Caduceus M2) and the embedded-C peer (EPHEMERIS v0.3) must reproduce every
byte here without reading the Python. This test asserts that THIS implementation
still does, so a refactor cannot silently move the format.

If a vector fails, the implementation changed. Regenerating the fixture to make
the test pass is a format change and needs a version bump, not an edit.
"""
import json
import math
from pathlib import Path

import pytest

from aletheia.provenance import attest, cbor, codec, quantize, vectors
from aletheia.provenance.entry import EntryV1
from aletheia.provenance.envelope import DacV1, SchemaError, from_projection

VECTOR_PATH = Path(__file__).parent / "vectors" / "zil_provenance_v1.json"
SUITE = json.loads(VECTOR_PATH.read_text())


def _ids(section):
    return [v["name"] for v in SUITE[section]]


def test_vector_file_is_committed_and_current():
    """The committed fixture matches what this implementation generates.

    Falsification target: a code change that alters the wire format without
    anyone noticing, because the fixture was never regenerated.
    """
    assert SUITE == vectors.build()


def test_test_key_is_labelled_as_a_test_key():
    tk = SUITE["test_key"]
    assert "DO-NOT-USE" in tk["label"]
    assert "Never use in production" in tk["WARNING"]
    # Anyone can rederive it from the published constant.
    import hashlib
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = hashlib.sha256(tk["derivation_input_utf8"].encode()).digest()
    rederived = Ed25519PrivateKey.from_private_bytes(seed)
    assert codec.public_key_bytes(rederived.public_key()).hex() == tk["public_key_hex"]


def test_genesis_prev_is_thirty_two_zero_bytes():
    """PHRONESIS already used "0"*64; aletheia-dac used "" and Proteus
    "GENESIS". v1 normalizes to the one that was already correct."""
    assert SUITE["genesis_prev_hex"] == "00" * 32
    assert codec.GENESIS_PREV.hex() == SUITE["genesis_prev_hex"]


# --- CBOR ------------------------------------------------------------------ #
@pytest.mark.parametrize("v", SUITE["cbor"], ids=_ids("cbor"))
def test_cbor_vector(v):
    value = v["value"]
    if v["name"] == "bytes-512":
        value = bytes.fromhex(value)
    elif v["name"] == "empty-bytes":
        value = b""
    assert cbor.encode(value).hex() == v["hex"]
    assert cbor.decode(bytes.fromhex(v["hex"])) == value


@pytest.mark.parametrize("v", SUITE["cbor_reject"], ids=_ids("cbor_reject"))
def test_cbor_reject_vector(v):
    with pytest.raises(cbor.CBORError):
        cbor.decode(bytes.fromhex(v["hex"]))


# --- quantization ---------------------------------------------------------- #
def _coerce(raw, kind):
    return {"float": float, "int": int, "decimal": str}[kind](raw)


@pytest.mark.parametrize("v", SUITE["quantize"], ids=_ids("quantize"))
def test_quantize_vector(v):
    fn = getattr(quantize, v["op"])
    assert fn(_coerce(v["input"], v["input_type"])) == v["expected"]


@pytest.mark.parametrize("v", SUITE["quantize_reject"], ids=_ids("quantize_reject"))
def test_quantize_reject_vector(v):
    fn = getattr(quantize, v["op"])
    with pytest.raises(quantize.QuantizationError):
        fn(_coerce(v["input"], v["input_type"]))


# --- envelopes ------------------------------------------------------------- #
@pytest.mark.parametrize("v", SUITE["dac"], ids=_ids("dac"))
def test_dac_vector(v):
    env = from_projection(v["projection"])
    assert env.signing_bytes().hex() == v["signing_bytes_hex"]
    assert env.signatures.encode().hex() == v["signature_set_hex"]
    assert env.record_hash().hex() == v["record_hash_hex"]
    assert env.encode().hex() == v["wire_hex"]
    assert env.verify(), "vector signature must verify against the embedded key"
    # decode(encode(x)) is byte-stable
    assert DacV1.decode(env.encode()).encode() == env.encode()


@pytest.mark.parametrize("v", SUITE["entry"], ids=_ids("entry"))
def test_entry_vector(v):
    entry = EntryV1(seq=v["seq"], ts_us=v["ts_us"], event_type=v["event_type"],
                    payload=bytes.fromhex(v["payload_hex"]),
                    prev=bytes.fromhex(v["prev_hex"]), ext=v["ext"])
    entry.signatures = attest.SignatureSet.from_map(
        cbor.decode(bytes.fromhex(v["signature_set_hex"])))
    assert entry.signing_bytes().hex() == v["signing_bytes_hex"]
    assert entry.record_hash().hex() == v["record_hash_hex"]
    assert entry.encode().hex() == v["wire_hex"]
    assert entry.verify(vectors.conformance_private_key().public_key())
    report = entry.verify_signatures()
    assert report["ok"], report["problems"]
    assert len(report["attestors_valid"]) == v["attestor_count"]
    assert report["threshold_required"] == v["threshold_required"]


# --- near-miss signatures -------------------------------------------------- #
@pytest.mark.parametrize("v", SUITE["near_miss"], ids=_ids("near_miss"))
def test_near_miss_vector(v):
    """Every near-miss must be rejected; exactly one target must verify."""
    pk = vectors.conformance_private_key().public_key()
    if v.get("must_verify"):
        assert codec.verify_raw_ok(pk, bytes.fromhex(v["signing_bytes_hex"]),
                                   bytes.fromhex(v["signature_hex"]))
        return
    target = next(x for x in SUITE["near_miss"] if x.get("must_verify"))
    msg = bytes.fromhex(target["signing_bytes_hex"])
    assert not codec.verify_raw_ok(pk, msg, bytes.fromhex(v["signature_hex"])), \
        f"near-miss {v['name']} must not verify: {v['reason']}"


# --- n-of-m attestation ---------------------------------------------------- #
def test_the_two_required_attestation_cases_exist():
    """Work order deliverable 3 / DoD item 7: a vector for the author-only case
    (zero attestors) and for an author-plus-two-attestor case."""
    names = {v["name"] for v in SUITE["entry"]}
    assert "entry-attest-author-only" in names
    assert "entry-attest-author-plus-two" in names


def test_attestor_keys_are_labelled_as_test_keys():
    tk = SUITE["test_attestor_keys"]
    assert "TEST KEYS" in tk["WARNING"]
    assert "no real attestation exists" in tk["WARNING"]


@pytest.mark.parametrize("v", SUITE["attest_reject"], ids=_ids("attest_reject"))
def test_attest_reject_vector(v):
    """Each vector is either structurally rejected, or verifies but reports the
    threshold as not met. Neither may quietly pass."""
    raw = bytes.fromhex(v["signature_set_hex"])
    try:
        sigset = attest.SignatureSet.from_map(cbor.decode(raw))
    except (attest.AttestationError, cbor.CBORError):
        return                      # structurally rejected: correct
    msg = bytes.fromhex(v["signing_bytes_hex"]) if "signing_bytes_hex" in v else b""
    report = sigset.verify(msg)
    assert not report["ok"], f"{v['name']} must not pass: {v['reason']}"


def test_author_signature_never_counts_toward_the_threshold():
    """Section 7.6.2 — otherwise 2-of-3 degrades to one independent signer."""
    entry = EntryV1.from_json_payload(seq=0, ts_us=1, event_type="X",
                                      payload_obj={"a": 1})
    sk = vectors.conformance_private_key()
    entry.sign(sk, policy=attest.POLICY_2_OF_3)
    report = entry.verify_signatures()
    assert report["author_signature"] == "VALID"
    assert report["threshold_required"] == 2
    assert not report["threshold_met"]
    assert "threshold_not_reached" in report["problems"]
    assert not report["ok"]


def test_attestation_is_bound_into_the_record_hash():
    """Stripping an attestor must break the chain, not silently downgrade it."""
    sk = vectors.conformance_private_key()
    entry = EntryV1.from_json_payload(seq=0, ts_us=1, event_type="X",
                                      payload_obj={"a": 1})
    entry.sign(sk, policy=attest.POLICY_2_OF_3)
    author_only_hash = entry.record_hash()
    entry.attest_with(vectors._test_attestor(1))
    assert entry.record_hash() != author_only_hash


def test_roster_resolves_attestor_fingerprints():
    sk = vectors.conformance_private_key()
    a1 = vectors._test_attestor(1)
    entry = EntryV1.from_json_payload(seq=0, ts_us=1, event_type="X",
                                      payload_obj={"a": 1})
    entry.sign(sk, policy=attest.ThresholdPolicy(required=1, roster_size=1))
    entry.attest_with(a1, role=attest.ROLE_PROCESS)

    empty = attest.Roster(entries=[])
    assert "attestor_not_in_roster" in entry.verify_signatures(empty)["problems"]

    known = attest.Roster(entries=[{
        "id": "attestor-1",
        "k": codec.public_key_bytes(a1.public_key()),
        "roles": [attest.ROLE_PROCESS]}])
    assert entry.verify_signatures(known)["ok"]


def test_roster_changes_are_chain_entries():
    """Section 7.6.7 — a roster change is recorded on the chain like anything else."""
    a1 = vectors._test_attestor(1)
    roster = attest.Roster(entries=[{
        "id": "attestor-1",
        "k": codec.public_key_bytes(a1.public_key()),
        "roles": [attest.ROLE_PROCESS]}])
    entry = EntryV1(seq=0, ts_us=1, event_type=attest.ROSTER_EVENT_TYPE,
                    payload=attest.roster_event_payload(roster))
    entry.sign(vectors.conformance_private_key())
    assert entry.verify_signatures()["ok"]
    assert entry.payload == roster.encode()


# --- schema rejection ------------------------------------------------------ #
def _apply_mutation(base_map, mutation):
    m = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base_map.items()}
    if "add" in mutation:
        m.update(mutation["add"])
    if "set" in mutation:
        m.update(mutation["set"])
    if "remove" in mutation:
        m.pop(mutation["remove"])
    if "conf_add" in mutation:
        m["conf"] = {**m["conf"], **mutation["conf_add"]}
    if "conf_set" in mutation:
        m["conf"] = {**m["conf"], **mutation["conf_set"]}
    if "val_add" in mutation:
        m["val"] = {**m["val"], **mutation["val_add"]}
    if "val_set" in mutation:
        m["val"] = {**m["val"], **mutation["val_set"]}
    if "set_bytes" in mutation:
        for k, hexval in mutation["set_bytes"].items():
            m[k] = bytes.fromhex(hexval)
    if "set_parents" in mutation:
        m["par"] = [bytes.fromhex(p) for p in mutation["set_parents"]]
    return m


@pytest.mark.parametrize("v", SUITE["schema_reject"], ids=_ids("schema_reject"))
def test_schema_reject_vector(v):
    base = from_projection(SUITE["dac"][1]["projection"]).to_map()
    base["cls"], base["hitl"] = 0, False       # neutral starting point
    mutated = _apply_mutation(base, v["mutation"])
    with pytest.raises(SchemaError):
        DacV1.from_map(mutated)


def test_adversarial_categories_are_all_represented():
    """The brief names six adversarial categories; none may quietly disappear."""
    names = " ".join(
        v["name"] + " " + v.get("note", "")
        for section in ("cbor", "cbor_reject", "dac", "entry",
                        "near_miss", "schema_reject")
        for v in SUITE[section]
    )
    for category in ("order", "unknown", "no-parents", "max-length",
                     "non-ascii", "near-miss"):
        assert category in names, f"no vector covers {category}"


def test_vendored_copies_match_this_canonical_core():
    """The copies in PHRONESIS-1 and Proteus must be byte-identical.

    Each of those repositories also guards itself locally (source digest +
    conformance suite). This is the check from the other direction, run when the
    siblings are present.
    """
    import hashlib
    import os

    canonical = Path(vectors.__file__).resolve().parent
    # Discovered, not hardcoded: a fixed list goes stale the moment a module is
    # added, which is how attest.py briefly escaped this check.
    names = sorted(p.name for p in canonical.glob("*.py"))
    root = Path(os.environ.get("ZIL_PORTFOLIO_ROOT")
                or Path(__file__).resolve().parents[2])
    copies = {
        "PHRONESIS-1": root / "PHRONESIS-1/substrate/src/aletheia/provenance",
        "Proteus": root / "Proteus/zil_provenance",
    }
    checked = 0
    for repo, path in copies.items():
        if not path.exists():
            continue
        checked += 1
        for name in names:
            want = hashlib.sha256((canonical / name).read_bytes()).hexdigest()
            got = hashlib.sha256((path / name).read_bytes()).hexdigest()
            assert got == want, f"{repo} vendored {name} has drifted"
    if checked == 0:
        pytest.skip("no sibling repositories present")
