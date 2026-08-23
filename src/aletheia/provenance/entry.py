"""
entry.py — the zil-provenance v1 chain entry.

The DAC envelope carries a *claim*; a chain entry carries an *event*. PHRONESIS
logs decision events, Proteus logs state transitions, and the Proteus release
ledger logs commits. All three are chain entries, and before this module all
three hashed and signed them differently.

THE PAYLOAD IS AN OPAQUE BYTE STRING. A chain entry attests that *these exact
bytes* occurred at this time in this chain position; it does not interpret them.
That is deliberate, and it is what makes the entry format universal:

  * The substrate that produces an event owns its payload schema. PHRONESIS logs
    float telemetry (partial pressures, latencies); Proteus logs state and
    signal objects. Requiring those to be re-encodable under the no-float rule
    would force a rewrite of application data that has nothing to do with
    provenance.
  * A Rust or embedded-C peer reproduces the entry hash by hashing the same
    bytes. It never has to parse the payload, let alone re-serialize it
    identically -- which would otherwise be a silent portability trap.
  * Tamper detection is unaffected and arguably sharper: any change to the
    stored bytes changes the hash, whatever the bytes mean.

A substrate that wants field-level cross-verification of its payloads should
itself encode them as deterministic CBOR and decode ``payload`` as such. The
no-float rule still binds everywhere it matters: the DAC envelope, and the
entry's own ``ext`` map.

Per-substrate fields live in the signed ``ext`` map rather than forking the
schema. PHRONESIS, for example, keeps nanosecond timestamps there so its
existing public API is preserved and the nanosecond value is still covered by
the signature.

See docs/WIRE_FORMAT.md §8 and docs/zil-provenance-v1.cddl.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import json

from . import attest, cbor, codec, quantize
from .envelope import SchemaError, _reject_unknown, _require

FORMAT_VERSION = 1

_ENTRY_KEYS = {"v", "seq", "ts", "et", "ep", "prev", "ext"}


@dataclass
class EntryV1:
    """A signed, hash-linked event record."""
    seq: int
    ts_us: int                    # microseconds since the Unix epoch, UTC
    event_type: str
    payload: bytes                # opaque; attested, never interpreted
    prev: bytes = codec.GENESIS_PREV
    ext: Optional[dict] = None
    #: An author signature plus zero or more attestor signatures. Required to be
    #: a set from the start: the portfolio has decided on author + 2-of-3
    #: independent attestation for benchmark commits, and a one-signature schema
    #: would force a v2 the moment the first attestor signs
    #: (PORTFOLIO_BUILD_PLAN.md 7.6.9). Author-only with zero attestors is a
    #: valid instance, and is what every substrate emits today.
    signatures: Optional[attest.SignatureSet] = None

    def to_map(self) -> dict:
        m = {
            "v": FORMAT_VERSION,
            "seq": int(self.seq),
            "ts": int(self.ts_us),
            "et": self.event_type,
            "ep": bytes(self.payload),
            "prev": bytes(self.prev),
        }
        if self.ext is not None:
            m["ext"] = self.ext
        return m

    @classmethod
    def from_map(cls, m: dict) -> "EntryV1":
        _require(isinstance(m, dict), "entry must be a map")
        _reject_unknown(m, _ENTRY_KEYS, "entry")
        for k in ("v", "seq", "ts", "et", "ep", "prev"):
            _require(k in m, f"entry.{k} is required")
        _require(m["v"] == FORMAT_VERSION,
                 f"entry.v must be {FORMAT_VERSION}, got {m['v']!r}")
        for k in ("seq", "ts"):
            _require(isinstance(m[k], int) and not isinstance(m[k], bool),
                     f"entry.{k} must be an integer")
        _require(m["seq"] >= 0, "entry.seq must be non-negative")
        _require(quantize.US_MIN <= m["ts"] <= quantize.US_MAX,
                 f"entry.ts = {m['ts']} outside the representable range")
        _require(isinstance(m["et"], str), "entry.et must be a text string")
        _require(isinstance(m["ep"], bytes), "entry.ep must be a byte string")
        _require(isinstance(m["prev"], bytes) and len(m["prev"]) == 32,
                 "entry.prev must be 32 bytes")
        ext = m.get("ext")
        if ext is not None:
            _require(isinstance(ext, dict), "entry.ext must be a map")
            _require(all(isinstance(k, str) for k in ext),
                     "entry.ext keys must be text strings")
        return cls(seq=m["seq"], ts_us=m["ts"], event_type=m["et"],
                   payload=m["ep"], prev=m["prev"], ext=ext)


    @classmethod
    def from_json_payload(cls, *, seq, ts_us, event_type, payload_obj,
                          prev=codec.GENESIS_PREV, ext=None) -> "EntryV1":
        """Build an entry whose payload is compact JSON of ``payload_obj``.

        Convenience for substrates that already store their event payloads as
        JSON text. The bytes produced here are exactly what gets signed, so the
        stored column and the attested bytes are the same thing.
        """
        raw = json.dumps(payload_obj, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return cls(seq=seq, ts_us=ts_us, event_type=event_type, payload=raw,
                   prev=prev, ext=ext)

    def signing_bytes(self) -> bytes:
        return codec.signing_bytes(codec.DOMAIN_CHAIN, self.to_map())

    @property
    def signature(self) -> bytes:
        """The author signature alone, for callers that only need that."""
        return b"" if self.signatures is None else bytes(self.signatures.author.signature)

    def encode(self) -> bytes:
        _require(self.signatures is not None, "entry is not signed")
        return cbor.encode({"e": self.to_map(), "sig": self.signatures.to_map()})

    @classmethod
    def decode(cls, data: bytes) -> "EntryV1":
        outer = cbor.decode(data)
        _require(isinstance(outer, dict), "wire form must be a map")
        _reject_unknown(outer, {"sig", "e"}, "wire form")
        _require("sig" in outer and "e" in outer, "wire form requires 'e' and 'sig'")
        entry = cls.from_map(outer["e"])
        entry.signatures = attest.SignatureSet.from_map(outer["sig"])
        return entry

    def sign(self, private_key, policy=None) -> "EntryV1":
        """Seal with an author signature and no attestors."""
        self.signatures = attest.author_only(
            private_key, codec.DOMAIN_CHAIN, self.to_map(), policy)
        return self

    def attest_with(self, private_key, role=None) -> "EntryV1":
        """Add an independent attestor signature over the same bytes.

        Precondition:  the entry is already author-signed and the attestor key
                       differs from the author key.
        Postcondition: the record hash changes, because the hash covers the
                       whole set. Attestations belong at seal time; history is
                       never re-attested (PORTFOLIO_BUILD_PLAN.md 7.6.7).
        """
        _require(self.signatures is not None, "entry is not author-signed")
        self.signatures = attest.attest(
            self.signatures, private_key, codec.DOMAIN_CHAIN, self.to_map(), role)
        return self

    def verify(self, public_key) -> bool:
        """Verify the author signature against a specific key."""
        if self.signatures is None:
            return False
        return codec.verify(public_key, codec.DOMAIN_CHAIN, self.to_map(), self.signature)

    def verify_signatures(self, roster=None) -> dict:
        """Full report: author signature, attestor signatures, threshold."""
        if self.signatures is None:
            return {"ok": False, "problems": ["unsigned"]}
        return self.signatures.verify(self.signing_bytes(), roster)

    def record_hash(self) -> bytes:
        _require(self.signatures is not None, "entry is not signed")
        return codec.record_hash(codec.DOMAIN_CHAIN, self.to_map(),
                                 self.signatures.encode())
