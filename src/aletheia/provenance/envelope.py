"""
envelope.py — the zil-provenance v1 DAC envelope.

One schema, one encoding, one signature construction, shared by every substrate
that issues Drift-Aware Claims. See docs/WIRE_FORMAT.md §6 for the normative
field table and docs/zil-provenance-v1.cddl for the machine-readable schema.

Two changes from the legacy Python envelope are load-bearing and were approved
before implementation:

  1. ``prev`` is INSIDE the signed payload. The legacy envelope excluded it so
     the store could link records after signing. That was implementation
     convenience, and its cost was that a producer never attested to its own
     position in the chain — exactly the property CADUCEUS-004 T1 and
     EPHEMERIS A7(3) both require. The store is now asked for the head hash
     before signing rather than after.

  2. The envelope carries the raw 32-byte public key, not a 16-hex-character
     fingerprint, so a peer holding only the envelope can verify it.

No floating-point value appears anywhere in the payload; see quantize.py.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from . import attest, cbor, codec, quantize

FORMAT_VERSION = 1

#: Data-classification lattice, matching the MVCI four-tier scheme.
CLS_PUBLIC, CLS_INTERNAL, CLS_CONFIDENTIAL, CLS_REGULATED = 0, 1, 2, 3
CLS_MIN, CLS_MAX = 0, 3

STATUS_VALID = "VALID"
STATUS_STALE = "STALE"
STATUS_REVOKED = "REVOKED"
STATUSES = (STATUS_VALID, STATUS_STALE, STATUS_REVOKED)

CONF_METHODS_KNOWN = ("split_conformal", "aci", "asserted")

_ENVELOPE_KEYS = {"v", "id", "kind", "ph", "pid", "pk", "par",
                  "conf", "val", "cls", "hitl", "prev", "ext"}
_CONF_KEYS = {"m", "v", "a", "iv"}
_VAL_KEYS = {"mon", "iat", "exp", "st"}


class SchemaError(ValueError):
    """Raised when a structure does not conform to the v1 schema."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SchemaError(msg)


def _reject_unknown(got: dict, allowed: set, where: str) -> None:
    """Unknown keys are REJECTED, never ignored (docs/WIRE_FORMAT.md §7).

    A verifier that ignores an unknown key verifies a signature over bytes it
    did not fully understand. Extension goes through the ``ext`` map, which is
    declared and signed, or through a new ``v`` tag.
    """
    unknown = set(got) - allowed
    _require(not unknown, f"unknown key(s) in {where}: {sorted(unknown)}")


# --------------------------------------------------------------------------- #
# Confidence and validity                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class ConfidenceV1:
    """Calibrated confidence, in integer parts-per-million.

    ``value_ppm`` is a coverage level (floor-quantized); ``alpha_ppm`` is a
    miscoverage rate (ceil-quantized); ``interval`` is an optional pair of
    ``[mantissa, exp10]`` decimal endpoints that only ever widens.
    """
    method: str
    value_ppm: int
    alpha_ppm: int
    interval: Optional[list] = None

    def to_map(self) -> dict:
        m = {"m": self.method,
             "v": int(self.value_ppm),
             "a": int(self.alpha_ppm)}
        if self.interval is not None:
            m["iv"] = [[int(self.interval[0][0]), int(self.interval[0][1])],
                       [int(self.interval[1][0]), int(self.interval[1][1])]]
        return m

    @classmethod
    def from_map(cls, m: dict) -> "ConfidenceV1":
        _require(isinstance(m, dict), "conf must be a map")
        _reject_unknown(m, _CONF_KEYS, "conf")
        for k in ("m", "v", "a"):
            _require(k in m, f"conf.{k} is required")
        _require(isinstance(m["m"], str), "conf.m must be a text string")
        for k in ("v", "a"):
            _require(isinstance(m[k], int) and not isinstance(m[k], bool),
                     f"conf.{k} must be an integer")
            _require(quantize.PPM_MIN <= m[k] <= quantize.PPM_MAX,
                     f"conf.{k} = {m[k]} outside [0, {quantize.PPM_MAX}] ppm")
        iv = m.get("iv")
        if iv is not None:
            _require(isinstance(iv, list) and len(iv) == 2,
                     "conf.iv must be a 2-element array")
            for endpoint in iv:
                _require(isinstance(endpoint, list) and len(endpoint) == 2,
                         "conf.iv endpoint must be [mantissa, exp10]")
                for part in endpoint:
                    _require(isinstance(part, int) and not isinstance(part, bool),
                             "conf.iv components must be integers")
                _require(abs(endpoint[0]) <= quantize.MANTISSA_ABS_MAX,
                         "conf.iv mantissa exceeds signed 64-bit range")
        return cls(method=m["m"], value_ppm=m["v"], alpha_ppm=m["a"], interval=iv)


@dataclass
class ValidityV1:
    """A validity window in integer microseconds since the Unix epoch, UTC.

    EPOCH HAZARD — read before writing any converter. This field is UTC, not TT
    and not TAI. EPHEMERIS carries uint64 microseconds since J2000 in TT for its
    astronomical payload; that stays internal and the peer converts at the
    envelope boundary. The conversion crosses the leap-second table and is NOT a
    fixed offset. See docs/WIRE_FORMAT.md §4.4.
    """
    monitor_id: Optional[str]
    issued_at_us: int
    expires_at_us: int
    status: str = STATUS_VALID

    def to_map(self) -> dict:
        m = {"iat": int(self.issued_at_us),
             "exp": int(self.expires_at_us),
             "st": self.status}
        if self.monitor_id is not None:
            m["mon"] = self.monitor_id
        return m

    @classmethod
    def from_map(cls, m: dict) -> "ValidityV1":
        _require(isinstance(m, dict), "val must be a map")
        _reject_unknown(m, _VAL_KEYS, "val")
        for k in ("iat", "exp", "st"):
            _require(k in m, f"val.{k} is required")
        for k in ("iat", "exp"):
            _require(isinstance(m[k], int) and not isinstance(m[k], bool),
                     f"val.{k} must be an integer")
            _require(quantize.US_MIN <= m[k] <= quantize.US_MAX,
                     f"val.{k} = {m[k]} outside the representable range")
        _require(m["exp"] >= m["iat"],
                 f"val.exp ({m['exp']}) precedes val.iat ({m['iat']})")
        _require(m["st"] in STATUSES, f"val.st must be one of {STATUSES}")
        mon = m.get("mon")
        if mon is not None:
            _require(isinstance(mon, str), "val.mon must be a text string")
        return cls(monitor_id=mon, issued_at_us=m["iat"],
                   expires_at_us=m["exp"], status=m["st"])


# --------------------------------------------------------------------------- #
# The envelope                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class DacV1:
    """A signed Drift-Aware Claim envelope, wire-format version 1."""
    kind: str
    payload_hash: bytes           # 32 bytes, SHA-256 of the payload
    producer_id: str
    producer_pk: bytes            # 32 bytes, raw Ed25519 public key
    parents: list                 # list of 16-byte claim ids
    confidence: ConfidenceV1
    validity: ValidityV1
    classification: int
    requires_hitl: bool
    prev: bytes = codec.GENESIS_PREV
    claim_id: bytes = field(default_factory=lambda: uuid.uuid4().bytes)
    ext: Optional[dict] = None
    #: An author signature plus zero or more attestor signatures. Modelled as a
    #: set from the start so multi-party attestation never forces a v2 format
    #: (PORTFOLIO_BUILD_PLAN.md 7.6.9).
    signatures: Optional[attest.SignatureSet] = None

    # ---- schema ---------------------------------------------------------- #
    def to_map(self) -> dict:
        """The signed structure, without the signature."""
        m = {
            "v": FORMAT_VERSION,
            "id": bytes(self.claim_id),
            "kind": self.kind,
            "ph": bytes(self.payload_hash),
            "pid": self.producer_id,
            "pk": bytes(self.producer_pk),
            "par": [bytes(p) for p in self.parents],
            "conf": self.confidence.to_map(),
            "val": self.validity.to_map(),
            "cls": int(self.classification),
            "hitl": bool(self.requires_hitl),
            "prev": bytes(self.prev),
        }
        if self.ext is not None:
            m["ext"] = self.ext
        return m

    @classmethod
    def from_map(cls, m: dict) -> "DacV1":
        """Strict decode. Rejects unknown keys, wrong types, bad ranges."""
        _require(isinstance(m, dict), "envelope must be a map")
        _reject_unknown(m, _ENVELOPE_KEYS, "envelope")
        for k in ("v", "id", "kind", "ph", "pid", "pk", "par",
                  "conf", "val", "cls", "hitl", "prev"):
            _require(k in m, f"envelope.{k} is required")
        _require(m["v"] == FORMAT_VERSION,
                 f"envelope.v must be {FORMAT_VERSION}, got {m['v']!r}")
        _require(isinstance(m["id"], bytes) and len(m["id"]) == 16,
                 "envelope.id must be 16 bytes")
        _require(isinstance(m["kind"], str), "envelope.kind must be a text string")
        _require(isinstance(m["ph"], bytes) and len(m["ph"]) == 32,
                 "envelope.ph must be 32 bytes")
        _require(isinstance(m["pid"], str), "envelope.pid must be a text string")
        _require(isinstance(m["pk"], bytes) and len(m["pk"]) == 32,
                 "envelope.pk must be a 32-byte Ed25519 public key")
        _require(isinstance(m["par"], list), "envelope.par must be an array")
        prev_parent = None
        for p in m["par"]:
            _require(isinstance(p, bytes) and len(p) == 16,
                     "envelope.par entries must be 16-byte ids")
            # Parent order is canonical so the same provenance set always
            # encodes to the same bytes.
            if prev_parent is not None:
                _require(p != prev_parent, "envelope.par contains a duplicate id")
                _require(p > prev_parent,
                         "envelope.par must be sorted in bytewise order")
            prev_parent = p
        _require(isinstance(m["cls"], int) and not isinstance(m["cls"], bool),
                 "envelope.cls must be an integer")
        _require(CLS_MIN <= m["cls"] <= CLS_MAX,
                 f"envelope.cls = {m['cls']} outside [{CLS_MIN}, {CLS_MAX}]")
        _require(isinstance(m["hitl"], bool), "envelope.hitl must be a boolean")
        _require(isinstance(m["prev"], bytes) and len(m["prev"]) == 32,
                 "envelope.prev must be 32 bytes")
        ext = m.get("ext")
        if ext is not None:
            _require(isinstance(ext, dict), "envelope.ext must be a map")
            _require(all(isinstance(k, str) for k in ext),
                     "envelope.ext keys must be text strings")

        conf = ConfidenceV1.from_map(m["conf"])
        val = ValidityV1.from_map(m["val"])

        # REGULATED artifacts always carry a human-in-the-loop gate. This is a
        # schema-level invariant, not only a runtime one, so a hand-built
        # envelope cannot assert REGULATED without the gate.
        if m["cls"] >= CLS_REGULATED:
            _require(m["hitl"] is True,
                     "envelope.cls REGULATED requires envelope.hitl = true")

        return cls(
            kind=m["kind"], payload_hash=m["ph"], producer_id=m["pid"],
            producer_pk=m["pk"], parents=list(m["par"]), confidence=conf,
            validity=val, classification=m["cls"], requires_hitl=m["hitl"],
            prev=m["prev"], claim_id=m["id"], ext=ext,
        )

    # ---- bytes, signing, verification ------------------------------------ #
    def signing_bytes(self) -> bytes:
        return codec.signing_bytes(codec.DOMAIN_DAC, self.to_map())

    @property
    def signature(self) -> bytes:
        """The author signature alone, for callers that only need that."""
        return b"" if self.signatures is None else bytes(self.signatures.author.signature)

    @signature.setter
    def signature(self, sig: bytes) -> None:
        """Set an author-only signature set from a bare signature.

        Kept so a caller holding a raw signature and the producer key can seal
        an envelope without constructing the set by hand.
        """
        self.signatures = attest.SignatureSet(
            author=attest.Attestation(public_key=bytes(self.producer_pk),
                                      signature=bytes(sig)))

    def encode(self) -> bytes:
        """Full on-the-wire form: the signed structure plus its signature set."""
        _require(self.signatures is not None, "envelope is not signed")
        return cbor.encode({"e": self.to_map(), "sig": self.signatures.to_map()})

    @classmethod
    def decode(cls, data: bytes) -> "DacV1":
        outer = cbor.decode(data)
        _require(isinstance(outer, dict), "wire form must be a map")
        _reject_unknown(outer, {"sig", "e"}, "wire form")
        _require("sig" in outer and "e" in outer, "wire form requires 'e' and 'sig'")
        env = cls.from_map(outer["e"])
        env.signatures = attest.SignatureSet.from_map(outer["sig"])
        return env

    def sign(self, private_key, policy=None) -> "DacV1":
        """Seal with an author signature and no attestors.

        A valid instance of the n-of-m model, not a special case outside it.
        """
        self.signatures = attest.author_only(
            private_key, codec.DOMAIN_DAC, self.to_map(), policy)
        return self

    def verify(self, public_key=None) -> bool:
        """Verify the envelope's author signature.

        With no argument, verifies against the public key the envelope carries —
        which establishes internal consistency, not authority. Authority comes
        from checking ``producer_pk`` against a trust root; the verifier does
        that separately. For the full n-of-m report use ``verify_signatures``.
        """
        if self.signatures is None:
            return False
        pk = public_key if public_key is not None else codec.public_key_from_bytes(self.producer_pk)
        return codec.verify(pk, codec.DOMAIN_DAC, self.to_map(), self.signature)

    def verify_signatures(self, roster=None) -> dict:
        """Full report: author signature, attestor signatures, threshold."""
        if self.signatures is None:
            return {"ok": False, "problems": ["unsigned"]}
        return self.signatures.verify(self.signing_bytes(), roster)

    def record_hash(self) -> bytes:
        _require(self.signatures is not None, "envelope is not signed")
        return codec.record_hash(codec.DOMAIN_DAC, self.to_map(),
                                 self.signatures.encode())


# --------------------------------------------------------------------------- #
# Monotone propagation — exact on integers                                     #
# --------------------------------------------------------------------------- #
def propagate(*, value_ppm: int, alpha_ppm: int, issued_at_us: int,
              expires_at_us: int, classification: int, requires_hitl: bool,
              parents: list) -> dict:
    """Combine a claim's own attributes with its parents' under the lattice.

    Inputs:  the claim's own quantized attributes and a list of parent DacV1.
    Outputs: a dict of the combined attributes plus the derived status.
    Precondition:  all integer inputs are already quantized and in range.
    Postcondition: the MONOTONE PROPAGATION invariant holds --
        confidence     = min(self, parents)     never stronger than the weakest
        alpha          = max(self, parents)     never weaker than the loosest
        validity       = intersection(parents)  expires when any input does
        classification = max(self, parents)     REGULATED taints downstream
        requires_hitl  = OR(...), forced True when REGULATED
        status         = STALE if any parent is not VALID

    On integers these are exact. The float versions carried comparison edge
    cases at the boundary; min/max/intersection over ints have none.
    VERIFIED by T3/T4/T6 and tests/test_provenance_propagate.py.
    """
    status = STATUS_VALID
    for p in parents:
        value_ppm = min(value_ppm, p.confidence.value_ppm)
        alpha_ppm = max(alpha_ppm, p.confidence.alpha_ppm)
        issued_at_us = max(issued_at_us, p.validity.issued_at_us)
        expires_at_us = min(expires_at_us, p.validity.expires_at_us)
        classification = max(classification, p.classification)
        requires_hitl = requires_hitl or p.requires_hitl
        if p.validity.status != STATUS_VALID:
            status = STATUS_STALE
    if classification >= CLS_REGULATED:
        requires_hitl = True
    # An empty intersection is a claim that was never valid, not an error: the
    # window is clamped so exp >= iat and the claim is born STALE.
    if expires_at_us < issued_at_us:
        expires_at_us = issued_at_us
        status = STATUS_STALE
    return {
        "value_ppm": value_ppm,
        "alpha_ppm": alpha_ppm,
        "issued_at_us": issued_at_us,
        "expires_at_us": expires_at_us,
        "classification": classification,
        "requires_hitl": requires_hitl,
        "status": status,
    }


# --------------------------------------------------------------------------- #
# JSON projection                                                              #
# --------------------------------------------------------------------------- #
# The signed form is deterministic CBOR. Stores and operators also want a
# human-readable, greppable form. The projection below is lossless: byte fields
# become hex strings and everything else is carried through, so an envelope can
# be rebuilt from its projection and will re-encode to the identical CBOR bytes.
# It is a VIEW, never the thing that is signed.

def to_projection(env: "DacV1") -> dict:
    """Lossless JSON-safe view of a signed envelope."""
    m = env.to_map()
    proj = {
        "v": m["v"],
        "id": m["id"].hex(),
        "kind": m["kind"],
        "ph": m["ph"].hex(),
        "pid": m["pid"],
        "pk": m["pk"].hex(),
        "par": [p.hex() for p in m["par"]],
        "conf": m["conf"],
        "val": m["val"],
        "cls": m["cls"],
        "hitl": m["hitl"],
        "prev": m["prev"].hex(),
        "sig": env.signatures.encode().hex() if env.signatures else "",
    }
    if "ext" in m:
        proj["ext"] = m["ext"]
    return proj


def from_projection(proj: dict) -> "DacV1":
    """Rebuild an envelope from its projection.

    Postcondition: ``to_map()`` of the result encodes to the same CBOR bytes as
    the envelope the projection was taken from, so the record hash is stable
    across a store round-trip.
    """
    _require(isinstance(proj, dict), "projection must be an object")
    m = {
        "v": proj["v"],
        "id": bytes.fromhex(proj["id"]),
        "kind": proj["kind"],
        "ph": bytes.fromhex(proj["ph"]),
        "pid": proj["pid"],
        "pk": bytes.fromhex(proj["pk"]),
        "par": [bytes.fromhex(p) for p in proj["par"]],
        "conf": proj["conf"],
        "val": proj["val"],
        "cls": proj["cls"],
        "hitl": proj["hitl"],
        "prev": bytes.fromhex(proj["prev"]),
    }
    if proj.get("ext") is not None:
        m["ext"] = proj["ext"]
    # A projection round-trips JSON, which has no integer/float distinction for
    # whole numbers; normalize before schema checking so a stored 1.0 does not
    # masquerade as a valid uint.
    for section, keys in (("conf", ("v", "a")), ("val", ("iat", "exp"))):
        for k in keys:
            val = m[section].get(k)
            if isinstance(val, float):
                if not val.is_integer():
                    raise SchemaError(f"{section}.{k} is not an integer: {val!r}")
                m[section][k] = int(val)
    env = DacV1.from_map(m)
    raw = proj.get("sig", "")
    if raw:
        env.signatures = attest.SignatureSet.from_map(cbor.decode(bytes.fromhex(raw)))
    return env
