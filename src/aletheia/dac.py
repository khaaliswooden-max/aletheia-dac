"""
dac.py — Drift-Aware Claim (DAC) substrate, reference implementation.

A "road" that closes the two cross-cutting gaps found across all five substrates:
  (#2) provenance + calibrated confidence do not survive the stack
  (#1) nothing knows when its own knowledge has expired under drift

Every artifact any layer produces (an embedding, a map tile, a policy decision,
a sensor reading, an inference) is wrapped in a DAC: a signed, hash-chained
envelope carrying provenance, *calibrated* confidence, a validity window, and a
data classification. The runtime enforces MONOTONE PROPAGATION so a derived DAC
can never silently drop the weakest confidence / widest sensitivity / shortest
validity of its inputs. A drift monitor cascades STALE through the provenance
graph the moment a governing input distribution shifts.

WIRE FORMAT — this module now issues zil-provenance v1 envelopes (deterministic
CBOR, docs/WIRE_FORMAT.md). The public API below is unchanged: the same classes,
the same call signatures, the same attribute names. What changed underneath:

  * The signed bytes are deterministic CBOR, not JSON, so Rust and embedded C
    can reproduce them byte-for-byte.
  * ``prev_hash`` is INSIDE the producer signature. A producer now attests to
    its own position in the chain, as CADUCEUS-004 T1 and EPHEMERIS A7(3) both
    require. ``Substrate.issue`` therefore asks the store for the head hash
    before signing rather than after.
  * Confidence, alpha and the validity window are stored as integers (parts per
    million; microseconds since the Unix epoch, UTC). Floats remain the public
    read/write surface and are quantized on the way in. Monotone propagation is
    now EXACT rather than approximate.
  * The envelope carries the producer's raw public key, so a peer holding only
    the envelope can verify it.
  * Producers can be backed by a persistent keystore. The default stays
    ephemeral-per-process so existing callers are unaffected.

Legacy v0 stores are still readable: aletheia.provenance.legacy verifies them
under the ``v0-dac-json`` tag. Nothing is ever re-signed or migrated.

Dependencies: numpy, scipy, cryptography, sqlite3 (all open-source).
Author scaffold for: A. Khaalis Wooden, Sr. | Zuup Innovation Lab
"""
from __future__ import annotations

import json
import time
import uuid
import hashlib
import sqlite3
from enum import IntEnum
from typing import Optional

import numpy as np
from scipy import stats
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .provenance import attest as _attest, cbor as _cbor, codec, envelope as _env, quantize
from .provenance.envelope import ConfidenceV1, DacV1, ValidityV1


# --------------------------------------------------------------------------- #
# 0. Data classification lattice (matches MVCI 4-tier scheme)                  #
# --------------------------------------------------------------------------- #
class Classification(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    REGULATED = 3  # HIPAA / FISMA / EPA-governed


# --------------------------------------------------------------------------- #
# 2. Calibrated confidence — split conformal + Adaptive Conformal Inference    #
#    (distribution-free coverage guarantee; ACI maintains it under drift)      #
# --------------------------------------------------------------------------- #
class SplitConformal:
    """Split conformal prediction (Vovk; Angelopoulos & Bates).

    Guarantees marginal coverage P(y in interval) >= 1 - alpha, finite-sample,
    distribution-free, *under exchangeability*. Confidence is therefore a
    grounded coverage level, not a raw softmax number.
    """

    def __init__(self, alpha: float = 0.10):
        self.alpha = alpha
        self.q = None  # conformal quantile (interval half-width for regression)

    def calibrate(self, residuals: np.ndarray):
        n = len(residuals)
        # finite-sample-corrected quantile level
        level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
        self.q = float(np.quantile(residuals, level, method="higher"))
        return self.q

    def interval(self, point: float):
        return (point - self.q, point + self.q)


class AdaptiveConformal:
    """Adaptive Conformal Inference (Gibbs & Candes, 2021).

    Online update alpha_{t+1} = alpha_t + gamma * (alpha_target - err_t)
    keeps long-run coverage near the target even when the data distribution
    drifts (no exchangeability assumption). This is the bridge between
    confidence (gap #2) and drift (gap #1): the confidence object reacts to
    drift instead of silently going stale.
    """

    def __init__(self, alpha_target: float = 0.10, gamma: float = 0.02):
        self.alpha_target = alpha_target
        self.gamma = gamma
        self.alpha_t = alpha_target

    def width(self, recent_residuals: np.ndarray) -> float:
        a = min(max(self.alpha_t, 1e-3), 1 - 1e-3)
        return float(np.quantile(recent_residuals, 1 - a, method="higher"))

    def update(self, covered: bool):
        err_t = 0.0 if covered else 1.0
        self.alpha_t += self.gamma * (self.alpha_target - err_t)
        self.alpha_t = float(np.clip(self.alpha_t, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# 3. Drift monitor — Page-Hinkley (online mean-shift) + KS (distributional)    #
# --------------------------------------------------------------------------- #
class DriftMonitor:
    """Governs a stream. When it fires, every DAC bound to it (and everything
    transitively derived) is cascaded to STALE by the store."""

    def __init__(self, monitor_id: str, delta: float = 0.005, lam: float = 2.0):
        self.id = monitor_id
        self.delta = delta          # PH allowed magnitude of change
        self.lam = lam              # PH alarm threshold
        self._n = 0
        self._mean = 0.0
        self._m_t = 0.0
        self._min_m = 0.0
        self.tripped = False
        self.ref_window: list[float] = []

    def observe(self, x: float) -> bool:
        """Page-Hinkley online test for an upward mean shift."""
        self._n += 1
        self._mean += (x - self._mean) / self._n
        self._m_t += x - self._mean - self.delta
        self._min_m = min(self._min_m, self._m_t)
        if (self._m_t - self._min_m) > self.lam:
            self.tripped = True
        return self.tripped

    def ks_check(self, reference: np.ndarray, recent: np.ndarray,
                 p_thresh: float = 0.01) -> bool:
        """Two-sample Kolmogorov-Smirnov distributional drift test."""
        _, p = stats.ks_2samp(reference, recent)
        if p < p_thresh:
            self.tripped = True
        return self.tripped


# --------------------------------------------------------------------------- #
# 1. Cryptographic attestation — real Ed25519 (production-grade)              #
# --------------------------------------------------------------------------- #
class Producer:
    """A non-human actor (a layer/agent) with a verifiable identity.

    Inputs:  a producer id; optionally a Keystore so the identity survives the
             process, and a passphrase if that keystore's keys are encrypted.
    Outputs: an object that can sign DAC envelopes.
    Precondition:  with a keystore, the producer id is filesystem-safe.
    Postcondition: ``fingerprint`` and ``public_key_bytes`` identify this
                   producer stably for as long as the key lives.

    Without a keystore the key is ephemeral per process, which is the legacy
    default and is preserved so existing callers are unaffected. An ephemeral
    key cannot re-verify a stored envelope after the process exits — that is
    the defect the keystore exists to fix, and why aletheia-dac could not back
    the other four substrates. Pass a keystore for anything durable.
    """

    def __init__(self, producer_id: str, keystore=None,
                 passphrase: Optional[bytes] = None):
        self.id = producer_id
        self.keystore = keystore
        if keystore is not None:
            self._sk = keystore.load_or_create(producer_id, passphrase)
        else:
            self._sk = Ed25519PrivateKey.generate()
        self.pk = self._sk.public_key()

    @property
    def fingerprint(self) -> str:
        """16 hex characters of SHA-256 over the raw public key. Identifies
        a producer; does not verify one. v1 envelopes carry the key itself."""
        return codec.fingerprint(self.pk)

    @property
    def public_key_bytes(self) -> bytes:
        """The raw 32-byte Ed25519 public key carried in a v1 envelope."""
        return codec.public_key_bytes(self.pk)

    def sign(self, message: bytes) -> bytes:
        return self._sk.sign(message)

    def seal(self, domain: bytes, struct: dict, policy=None):
        """Produce an author-only signature set over a structure.

        Signatures are a SET even when there is one of them, so multi-party
        attestation never forces a format version (docs/WIRE_FORMAT.md §5.6).
        """
        return _attest.author_only(self._sk, domain, struct, policy)

    @staticmethod
    def verify(pk: Ed25519PublicKey, message: bytes, sig: bytes) -> bool:
        return codec.verify_raw_ok(pk, message, sig)


# --------------------------------------------------------------------------- #
# 4. The DAC envelope                                                          #
# --------------------------------------------------------------------------- #
# Integers are authoritative; the float attributes are a VIEW.
#
# This is not a stylistic choice. Quantization is not idempotent through a
# float: for roughly half of all ppm values n, floor(exact(n / 1e6) * 1e6) != n.
# So a value that round-tripped through a float on every store read would drift
# downward one ppm at a time. The integer is stored, signed and compared; the
# float is produced on demand and never re-quantized.
# VERIFIED by tests/test_provenance_adapter.py::test_ppm_survives_store_round_trip.

class Confidence:
    """Calibrated confidence: a coverage level, not a softmax number.

    Inputs:  method name; coverage in [0, 1]; alpha in [0, 1]; optional (lo, hi).
    Outputs: an object whose ``.value``/``.alpha`` read back as floats.
    Precondition:  the inputs are in range; NaN and infinity are rejected.
    Postcondition: ``value_ppm`` floors and ``alpha_ppm`` ceils, so quantization
                   can only ever weaken the claim.
    """

    __slots__ = ("method", "value_ppm", "alpha_ppm", "interval_q")

    def __init__(self, method: str, value=None, alpha=None, interval=None, *,
                 value_ppm: Optional[int] = None, alpha_ppm: Optional[int] = None,
                 interval_q=None):
        self.method = method
        self.value_ppm = (int(value_ppm) if value_ppm is not None
                          else quantize.ratio_to_ppm_floor(value))
        self.alpha_ppm = (int(alpha_ppm) if alpha_ppm is not None
                          else quantize.ratio_to_ppm_ceil(alpha))
        if interval_q is not None:
            self.interval_q = [list(interval_q[0]), list(interval_q[1])]
        elif interval is not None:
            self.interval_q = [quantize.to_decimal_floor(interval[0]),
                               quantize.to_decimal_ceil(interval[1])]
        else:
            self.interval_q = None

    # -- float view -------------------------------------------------------- #
    @property
    def value(self) -> float:
        return quantize.ppm_to_ratio(self.value_ppm)

    @value.setter
    def value(self, v):
        self.value_ppm = quantize.ratio_to_ppm_floor(v)

    @property
    def alpha(self) -> float:
        return quantize.ppm_to_ratio(self.alpha_ppm)

    @alpha.setter
    def alpha(self, a):
        self.alpha_ppm = quantize.ratio_to_ppm_ceil(a)

    @property
    def interval(self):
        if self.interval_q is None:
            return None
        return (quantize.decimal_to_float(self.interval_q[0]),
                quantize.decimal_to_float(self.interval_q[1]))

    def to_v1(self) -> ConfidenceV1:
        return ConfidenceV1(self.method, self.value_ppm, self.alpha_ppm,
                            self.interval_q)

    def __repr__(self):
        return (f"Confidence(method={self.method!r}, value={self.value!r}, "
                f"alpha={self.alpha!r}, interval={self.interval!r})")

    def __eq__(self, other):
        return (isinstance(other, Confidence)
                and (self.method, self.value_ppm, self.alpha_ppm, self.interval_q)
                == (other.method, other.value_ppm, other.alpha_ppm, other.interval_q))


class Validity:
    """A validity window, stored as microseconds since the Unix epoch, UTC.

    EPOCH HAZARD: this is UTC, not TT and not TAI. EPHEMERIS carries
    microseconds since J2000 in TT internally; the conversion crosses the
    leap-second table and is not a fixed offset. See docs/WIRE_FORMAT.md 4.4.
    """

    __slots__ = ("monitor_id", "issued_at_us", "expires_at_us", "status")

    def __init__(self, monitor_id=None, issued_at=None, expires_at=None,
                 status: str = "VALID", *, issued_at_us: Optional[int] = None,
                 expires_at_us: Optional[int] = None):
        self.monitor_id = monitor_id
        self.issued_at_us = (int(issued_at_us) if issued_at_us is not None
                             else quantize.seconds_to_us_ceil(issued_at))
        self.expires_at_us = (int(expires_at_us) if expires_at_us is not None
                              else quantize.seconds_to_us_floor(expires_at))
        self.status = status

    @property
    def issued_at(self) -> float:
        return quantize.us_to_seconds(self.issued_at_us)

    @issued_at.setter
    def issued_at(self, t):
        self.issued_at_us = quantize.seconds_to_us_ceil(t)

    @property
    def expires_at(self) -> float:
        return quantize.us_to_seconds(self.expires_at_us)

    @expires_at.setter
    def expires_at(self, t):
        self.expires_at_us = quantize.seconds_to_us_floor(t)

    def to_v1(self) -> ValidityV1:
        return ValidityV1(self.monitor_id, self.issued_at_us,
                          self.expires_at_us, self.status)

    def __repr__(self):
        return (f"Validity(monitor_id={self.monitor_id!r}, "
                f"issued_at={self.issued_at!r}, expires_at={self.expires_at!r}, "
                f"status={self.status!r})")

    def __eq__(self, other):
        return (isinstance(other, Validity)
                and (self.monitor_id, self.issued_at_us, self.expires_at_us, self.status)
                == (other.monitor_id, other.issued_at_us, other.expires_at_us, other.status))


class DAC:
    """A signed, hash-chained claim envelope.

    Field names and types on this class are the legacy public surface: ``id`` is
    a UUID string, ``payload_hash`` / ``prev_hash`` / ``sig`` are hex strings,
    ``parents`` is a list of id strings. The v1 wire form uses raw bytes for all
    of them; ``to_v1`` performs the conversion.
    """

    __slots__ = ("kind", "payload_hash", "producer_id", "producer_fpr",
                 "producer_pk", "parents", "confidence", "validity",
                 "classification", "requires_hitl", "id", "prev_hash", "sig")

    def __init__(self, kind, payload_hash, producer_id, producer_fpr, parents,
                 confidence, validity, classification, requires_hitl,
                 id=None, prev_hash="", sig="", producer_pk=""):
        self.kind = kind
        self.payload_hash = payload_hash
        self.producer_id = producer_id
        self.producer_fpr = producer_fpr
        self.producer_pk = producer_pk
        # Parent ids are canonical: sorted bytewise and deduplicated, so the
        # same provenance set always encodes to the same bytes regardless of the
        # order the caller supplied.
        self.parents = _canonical_parents(parents)
        self.confidence = confidence
        self.validity = validity
        self.classification = classification
        self.requires_hitl = requires_hitl
        self.id = id if id is not None else str(uuid.uuid4())
        self.prev_hash = prev_hash
        self.sig = sig

    # -- v1 conversion ----------------------------------------------------- #
    def to_v1(self) -> DacV1:
        """Build the v1 envelope this DAC denotes.

        Postcondition: the result's signing bytes are exactly what ``sig``
        attests to, so ``verify`` and ``record_hash`` agree with the store.
        """
        env = DacV1(
            kind=self.kind,
            payload_hash=bytes.fromhex(self.payload_hash),
            producer_id=self.producer_id,
            producer_pk=bytes.fromhex(self.producer_pk),
            parents=[uuid.UUID(p).bytes for p in self.parents],
            confidence=self.confidence.to_v1(),
            validity=self.validity.to_v1(),
            classification=int(self.classification),
            requires_hitl=bool(self.requires_hitl),
            prev=(bytes.fromhex(self.prev_hash) if self.prev_hash
                  else codec.GENESIS_PREV),
            claim_id=uuid.UUID(self.id).bytes,
        )
        if self.sig:
            # `sig` carries the hex of the encoded signature set, not a bare
            # signature. It stays a hex string, so the public API is unchanged.
            env.signatures = _attest.SignatureSet.from_map(
                _cbor.decode(bytes.fromhex(self.sig)))
        return env

    def signing_bytes(self) -> bytes:
        """The exact bytes the producer signs: DOMAIN_DAC || deterministic CBOR.

        ``prev_hash`` IS included, unlike the v0 construction. A producer
        attests to its own position in the chain.
        """
        return self.to_v1().signing_bytes()

    def record_hash(self) -> str:
        return self.to_v1().record_hash().hex()

    def projection(self) -> dict:
        """The lossless JSON view stored in the claim store."""
        return _env.to_projection(self.to_v1())

    def __repr__(self):
        return (f"DAC(id={self.id!r}, kind={self.kind!r}, "
                f"producer_id={self.producer_id!r}, "
                f"classification={self.classification!r}, "
                f"status={self.validity.status!r})")


def _canonical_parents(parents) -> list:
    """Sort parent ids bytewise and drop duplicates.

    Postcondition: the result is strictly increasing in UUID byte order, which
    is what the v1 schema requires.
    """
    seen, out = set(), []
    for p in parents:
        b = uuid.UUID(p).bytes
        if b not in seen:
            seen.add(b)
            out.append((b, p))
    return [p for _, p in sorted(out)]


# --------------------------------------------------------------------------- #
# 5. Persistent, tamper-evident store (SQLite) + provenance graph             #
# --------------------------------------------------------------------------- #
class ClaimStore:
    """Append-only claim store with a hash chain and a provenance graph.

    The ``json`` column holds the lossless v1 projection and is authoritative;
    ``get`` renders a legacy-shaped view on top of it so existing readers
    (the CLI, the OSCAL exporter) are unaffected.

    AUDIT INTEGRITY: a stored claim's signed content is never mutated in place.
    Legitimate state changes live in the ``status`` column only, which is what
    ``cascade_stale`` does and must keep doing.
    """

    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS claims(
                 id TEXT PRIMARY KEY, prev_hash TEXT, rec_hash TEXT,
                 json TEXT, status TEXT, monitor_id TEXT, fmt INTEGER)"""
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS edges(parent TEXT, child TEXT)"
        )
        # A store written by the v0 code has no fmt column. Add it so the
        # verifier can tell the formats apart; existing rows stay v0 and are
        # never rewritten.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(claims)")}
        if "fmt" not in cols:
            self.db.execute("ALTER TABLE claims ADD COLUMN fmt INTEGER")
            self.db.execute("UPDATE claims SET fmt=0 WHERE fmt IS NULL")
        # Resume the hash chain from the persisted head so chaining is correct
        # across separate processes (e.g. one CLI invocation per n8n step).
        row = self.db.execute(
            "SELECT rec_hash FROM claims ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        self._last_hash = row[0] if row else ""
        self.db.commit()

    def head(self) -> bytes:
        """The current chain head, as the 32 bytes a successor signs.

        Postcondition: 32 zero bytes on an empty store, which is the v1 genesis
        sentinel. ``Substrate.issue`` calls this BEFORE signing, because
        ``prev`` is inside the signature in v1.
        """
        return bytes.fromhex(self._last_hash) if self._last_hash else codec.GENESIS_PREV

    def append(self, dac: DAC) -> DAC:
        """Append an already-signed claim.

        Precondition:  ``dac.prev_hash`` equals the current head and ``dac.sig``
                       was produced over those bytes. Unlike the v0 store, this
                       method does NOT set prev_hash — doing so after signing
                       would put the chain link outside the signature.
        Postcondition: the claim is committed and the head advances.
        """
        rec = dac.record_hash()
        self.db.execute(
            "INSERT INTO claims VALUES (?,?,?,?,?,?,?)",
            (dac.id, dac.prev_hash, rec, json.dumps(dac.projection()),
             dac.validity.status, dac.validity.monitor_id, 1),
        )
        for p in dac.parents:
            self.db.execute("INSERT INTO edges VALUES (?,?)", (p, dac.id))
        self._last_hash = rec
        self.db.commit()
        return dac

    def get(self, dac_id: str) -> dict:
        """A legacy-shaped view of a stored claim.

        Outputs: a dict with the v0 field names and float values, plus the
        authoritative integer fields alongside them. Readers that want exact
        values use the integers; readers that want a display value use the
        floats. ``_dac_from_dict`` prefers the integers.
        """
        row = self.db.execute(
            "SELECT json, status FROM claims WHERE id=?", (dac_id,)
        ).fetchone()
        if row is None:
            raise KeyError(dac_id)
        d = _legacy_view(json.loads(row[0]))
        d["validity"]["status"] = row[1]
        return d

    def rows(self):
        """Yield (id, legacy view, status, monitor_id) in chain order."""
        for dac_id, j, status, monitor_id in self.db.execute(
            "SELECT id, json, status, monitor_id FROM claims ORDER BY rowid"
        ):
            try:
                d = _legacy_view(json.loads(j))
            except Exception:
                d = None
            if d is not None:
                d["validity"]["status"] = status
            yield dac_id, d, status, monitor_id

    def verify_chain(self) -> bool:
        """Recompute the hash chain and every signature; any tampered row breaks it.

        Stronger than the v0 check: because a v1 envelope carries the producer's
        public key, the signature is verified here too. A row whose projection
        no longer parses, no longer satisfies the schema, no longer hashes to
        its recorded value, no longer links to its predecessor, or no longer
        verifies, fails.
        """
        prev = codec.GENESIS_PREV
        for (j, rec, ph) in self.db.execute(
            "SELECT json, rec_hash, prev_hash FROM claims ORDER BY rowid"
        ):
            try:
                env = _env.from_projection(json.loads(j))
            except Exception:
                return False          # unparseable or schema-invalid == tampered
            if env.prev != prev:
                return False
            computed = env.record_hash()
            if computed.hex() != rec:
                return False
            if not env.verify():
                return False
            prev = computed
        return True

    def cascade_stale(self, monitor_id: str) -> int:
        """When a monitor trips: mark every DAC bound to it STALE, then BFS the
        provenance graph marking all descendants STALE. Returns count.

        Only the ``status`` column is written; the signed claim is untouched.
        """
        seeds = [r[0] for r in self.db.execute(
            "SELECT id FROM claims WHERE monitor_id=?", (monitor_id,))]
        seen, frontier, count = set(), list(seeds), 0
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            cur = self.db.execute(
                "SELECT status FROM claims WHERE id=?", (node,)).fetchone()
            if cur and cur[0] == "VALID":
                self.db.execute(
                    "UPDATE claims SET status='STALE' WHERE id=?", (node,))
                count += 1
            for (child,) in self.db.execute(
                "SELECT child FROM edges WHERE parent=?", (node,)):
                frontier.append(child)
        self.db.commit()
        return count


def _legacy_view(proj: dict) -> dict:
    """Render a v1 projection in the v0 field shape.

    Both forms are present: the float keys for display, the integer keys for
    exactness. Nothing re-quantizes a float back to an integer.
    """
    conf, val = proj["conf"], proj["val"]
    interval = None
    if conf.get("iv") is not None:
        interval = [quantize.decimal_to_float(conf["iv"][0]),
                    quantize.decimal_to_float(conf["iv"][1])]
    return {
        "kind": proj["kind"],
        "payload_hash": proj["ph"],
        "producer_id": proj["pid"],
        "producer_fpr": _fpr_from_pk_hex(proj["pk"]),
        "producer_pk": proj["pk"],
        "parents": [str(uuid.UUID(bytes=bytes.fromhex(p))) for p in proj["par"]],
        "confidence": {
            "method": conf["m"],
            "value": quantize.ppm_to_ratio(conf["v"]),
            "alpha": quantize.ppm_to_ratio(conf["a"]),
            "interval": interval,
            "value_ppm": conf["v"],
            "alpha_ppm": conf["a"],
            "interval_q": conf.get("iv"),
        },
        "validity": {
            "monitor_id": val.get("mon"),
            "issued_at": quantize.us_to_seconds(val["iat"]),
            "expires_at": quantize.us_to_seconds(val["exp"]),
            "status": val["st"],
            "issued_at_us": val["iat"],
            "expires_at_us": val["exp"],
        },
        "classification": proj["cls"],
        "requires_hitl": proj["hitl"],
        "id": str(uuid.UUID(bytes=bytes.fromhex(proj["id"]))),
        "prev_hash": proj["prev"],
        "sig": proj.get("sig", ""),
    }


def _fpr_from_pk_hex(pk_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pk_hex)).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# 6. Runtime — enforces monotone propagation across layer transitions          #
# --------------------------------------------------------------------------- #
SENSITIVITY = {c.value: c for c in Classification}


class Substrate:
    def __init__(self, store: ClaimStore):
        self.store = store
        self.producers: dict[str, Producer] = {}

    def register(self, producer: Producer):
        self.producers[producer.id] = producer

    def issue(self, *, kind: str, payload: bytes, producer: Producer,
              confidence: Confidence, classification: Classification,
              monitor_id: Optional[str] = None, ttl_s: float = 3600.0,
              parents: Optional[list[DAC]] = None,
              requires_hitl: bool = False) -> DAC:
        """Issue a claim, enforcing monotone propagation over its parents.

        Precondition:  every parent is a DAC already in this store.
        Postcondition: the returned claim is signed over bytes that include its
                       chain position, appended, and satisfies the invariant in
                       aletheia.provenance.envelope.propagate.

        Ordering note: the chain head is read BEFORE signing. In v0 the store
        stamped prev_hash after the signature was made, which left the chain
        link unattested.
        """
        parents = parents or []
        now = time.time()

        # --- MONOTONE PROPAGATION: the core invariant -------------------- #
        # Exact on integers: min / max / interval intersection over ints have
        # none of the comparison edge cases the float versions carried.
        combined = _env.propagate(
            value_ppm=confidence.value_ppm,
            alpha_ppm=confidence.alpha_ppm,
            issued_at_us=quantize.seconds_to_us_ceil(now),
            expires_at_us=quantize.seconds_to_us_floor(now + ttl_s),
            classification=int(classification),
            requires_hitl=requires_hitl,
            parents=parents,
        )
        # The v0 runtime mutated the caller's Confidence object in place; that
        # behaviour is preserved so existing callers see the same effect.
        confidence.value_ppm = combined["value_ppm"]
        confidence.alpha_ppm = combined["alpha_ppm"]

        dac = DAC(
            kind=kind,
            payload_hash=hashlib.sha256(payload).hexdigest(),
            producer_id=producer.id,
            producer_fpr=producer.fingerprint,
            producer_pk=producer.public_key_bytes.hex(),
            parents=[p.id for p in parents],
            confidence=confidence,
            validity=Validity(monitor_id, status=combined["status"],
                              issued_at_us=combined["issued_at_us"],
                              expires_at_us=combined["expires_at_us"]),
            classification=combined["classification"],
            requires_hitl=combined["requires_hitl"],
        )
        dac.prev_hash = self.store.head().hex()      # signed, not stamped after
        dac.sig = producer.seal(codec.DOMAIN_DAC, dac.to_v1().to_map()).encode().hex()
        return self.store.append(dac)

    def verify(self, dac: DAC) -> bool:
        """Verify a claim's producer signature.

        Uses the registered producer's key when there is one, so an unregistered
        or substituted producer is still caught; otherwise falls back to the key
        the envelope carries, which proves internal consistency only.
        """
        prod = self.producers.get(dac.producer_id)
        pk = prod.pk if prod is not None else None
        try:
            return dac.to_v1().verify(pk)
        except Exception:
            return False


def _dac_from_dict(d: dict) -> DAC:
    """Rebuild a DAC from a stored view.

    Accepts both shapes: a v1 legacy view (integer fields present, used exactly)
    and a v0 stored envelope (floats only, quantized on read). A v0 claim
    rebuilt this way carries no producer public key, so it can take part in
    propagation but cannot be re-verified — its key was ephemeral and is gone.
    """
    c, v = d["confidence"], d["validity"]
    conf = Confidence(
        c["method"],
        interval=None if c.get("interval") is None else tuple(c["interval"]),
        value_ppm=c.get("value_ppm"),
        alpha_ppm=c.get("alpha_ppm"),
        interval_q=c.get("interval_q"),
        **({} if c.get("value_ppm") is not None
           else {"value": c["value"], "alpha": c["alpha"]}),
    )
    val = Validity(
        v["monitor_id"], status=v["status"],
        issued_at_us=v.get("issued_at_us"),
        expires_at_us=v.get("expires_at_us"),
        **({} if v.get("issued_at_us") is not None
           else {"issued_at": v["issued_at"], "expires_at": v["expires_at"]}),
    )
    return DAC(
        kind=d["kind"], payload_hash=d["payload_hash"],
        producer_id=d["producer_id"], producer_fpr=d["producer_fpr"],
        producer_pk=d.get("producer_pk", ""),
        parents=d["parents"], confidence=conf, validity=val,
        classification=d["classification"], requires_hitl=d["requires_hitl"],
        id=d["id"], prev_hash=d["prev_hash"], sig=d["sig"],
    )
