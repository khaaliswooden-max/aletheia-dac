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

Dependencies: numpy, scipy, cryptography, sqlite3 (all open-source).
Author scaffold for: A. Khaalis Wooden, Sr. | Zuup Innovation Lab
"""
from __future__ import annotations

import json
import time
import uuid
import hashlib
import sqlite3
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Optional

import numpy as np
from scipy import stats
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


# --------------------------------------------------------------------------- #
# 0. Data classification lattice (matches MVCI 4-tier scheme)                  #
# --------------------------------------------------------------------------- #
class Classification(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    REGULATED = 3  # HIPAA / FISMA / EPA-governed


# --------------------------------------------------------------------------- #
# 1. Cryptographic attestation — real Ed25519 (production-grade)              #
# --------------------------------------------------------------------------- #
class Producer:
    """A non-human actor (a layer/agent) with a verifiable identity."""

    def __init__(self, producer_id: str):
        self.id = producer_id
        self._sk = Ed25519PrivateKey.generate()
        self.pk = self._sk.public_key()

    @property
    def fingerprint(self) -> str:
        raw = self.pk.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return hashlib.sha256(raw).hexdigest()[:16]

    def sign(self, message: bytes) -> bytes:
        return self._sk.sign(message)

    @staticmethod
    def verify(pk: Ed25519PublicKey, message: bytes, sig: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature
        try:
            pk.verify(sig, message)
            return True
        except InvalidSignature:
            return False


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
# 4. The DAC envelope                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class Confidence:
    method: str                       # "split_conformal" | "aci" | "asserted"
    value: float                      # coverage level (1 - alpha) achieved/claimed
    alpha: float
    interval: Optional[tuple] = None  # (lo, hi) when applicable


@dataclass
class Validity:
    monitor_id: Optional[str]
    issued_at: float
    expires_at: float
    status: str = "VALID"             # VALID | STALE | REVOKED


@dataclass
class DAC:
    kind: str
    payload_hash: str
    producer_id: str
    producer_fpr: str
    parents: list[str]
    confidence: Confidence
    validity: Validity
    classification: int
    requires_hitl: bool
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prev_hash: str = ""               # hash-chain link (Civium-style audit)
    sig: str = ""                     # hex Ed25519 signature

    # ---- canonical bytes that get signed (semantic content only) --------- #
    # prev_hash is a store-level chaining field, bound by record_hash (not by
    # the producer signature) so the store can link records after signing.
    def signing_bytes(self) -> bytes:
        d = asdict(self)
        d.pop("sig", None)
        d.pop("prev_hash", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()

    def record_hash(self) -> str:
        return hashlib.sha256(
            self.signing_bytes() + self.sig.encode() + self.prev_hash.encode()
        ).hexdigest()


# --------------------------------------------------------------------------- #
# 5. Persistent, tamper-evident store (SQLite) + provenance graph             #
# --------------------------------------------------------------------------- #
class ClaimStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS claims(
                 id TEXT PRIMARY KEY, prev_hash TEXT, rec_hash TEXT,
                 json TEXT, status TEXT, monitor_id TEXT)"""
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS edges(parent TEXT, child TEXT)"
        )
        # Resume the hash chain from the persisted head so chaining is correct
        # across separate processes (e.g. one CLI invocation per n8n step).
        row = self.db.execute(
            "SELECT rec_hash FROM claims ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        self._last_hash = row[0] if row else ""

    def append(self, dac: DAC) -> DAC:
        dac.prev_hash = self._last_hash
        rec = dac.record_hash()
        self.db.execute(
            "INSERT INTO claims VALUES (?,?,?,?,?,?)",
            (dac.id, dac.prev_hash, rec, json.dumps(asdict(dac)),
             dac.validity.status, dac.validity.monitor_id),
        )
        for p in dac.parents:
            self.db.execute("INSERT INTO edges VALUES (?,?)", (p, dac.id))
        self._last_hash = rec
        self.db.commit()
        return dac

    def get(self, dac_id: str) -> dict:
        row = self.db.execute(
            "SELECT json,status FROM claims WHERE id=?", (dac_id,)
        ).fetchone()
        d = json.loads(row[0]); d["validity"]["status"] = row[1]
        return d

    def verify_chain(self) -> bool:
        """Recompute the hash chain; any tampered row breaks it."""
        prev = ""
        for (j, rec, ph) in self.db.execute(
            "SELECT json, rec_hash, prev_hash FROM claims ORDER BY rowid"
        ):
            try:
                dac = _dac_from_dict(json.loads(j))
            except Exception:
                return False          # unparseable row == tampered == broken
            if dac.prev_hash != prev:
                return False
            if dac.record_hash() != rec:
                return False
            prev = rec
        return True

    def cascade_stale(self, monitor_id: str) -> int:
        """When a monitor trips: mark every DAC bound to it STALE, then BFS the
        provenance graph marking all descendants STALE. Returns count."""
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
        parents = parents or []
        now = time.time()

        # --- MONOTONE PROPAGATION: the core invariant -------------------- #
        # confidence: only as strong as the weakest link
        conf_val = confidence.value
        # validity window: intersection of all parents' windows
        issued_at, expires_at = now, now + ttl_s
        # classification: max sensitivity of self + parents
        cls = int(classification)
        hitl = requires_hitl
        status = "VALID"
        for p in parents:
            conf_val = min(conf_val, p.confidence.value)
            issued_at = max(issued_at, p.validity.issued_at)
            expires_at = min(expires_at, p.validity.expires_at)
            cls = max(cls, p.classification)
            hitl = hitl or p.requires_hitl
            if p.validity.status != "VALID":
                status = "STALE"     # cannot derive fresh from stale
        # REGULATED artifacts always require a human gate
        if cls >= Classification.REGULATED:
            hitl = True
        confidence.value = conf_val

        dac = DAC(
            kind=kind,
            payload_hash=hashlib.sha256(payload).hexdigest(),
            producer_id=producer.id,
            producer_fpr=producer.fingerprint,
            parents=[p.id for p in parents],
            confidence=confidence,
            validity=Validity(monitor_id, issued_at, expires_at, status),
            classification=cls,
            requires_hitl=hitl,
        )
        dac.sig = producer.sign(dac.signing_bytes()).hex()
        return self.store.append(dac)

    def verify(self, dac: DAC) -> bool:
        prod = self.producers[dac.producer_id]
        return Producer.verify(prod.pk, dac.signing_bytes(),
                               bytes.fromhex(dac.sig))


def _dac_from_dict(d: dict) -> DAC:
    c = d["confidence"]; v = d["validity"]
    return DAC(
        kind=d["kind"], payload_hash=d["payload_hash"],
        producer_id=d["producer_id"], producer_fpr=d["producer_fpr"],
        parents=d["parents"],
        confidence=Confidence(c["method"], c["value"], c["alpha"],
                              tuple(c["interval"]) if c["interval"] else None),
        validity=Validity(v["monitor_id"], v["issued_at"], v["expires_at"],
                          v["status"]),
        classification=d["classification"], requires_hitl=d["requires_hitl"],
        id=d["id"], prev_hash=d["prev_hash"], sig=d["sig"],
    )
