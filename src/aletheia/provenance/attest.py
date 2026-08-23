"""
attest.py — n-of-m attestation: signatures as a SET, from the start.

Required by PORTFOLIO_BUILD_PLAN.md §7.6.9 and docs/PROMPT_shared_provenance_core.md
deliverable 3. The portfolio has decided on multi-party attestation for benchmark
commits — author signature plus 2-of-3 independent attestors (§7.6.2) — and a
schema that holds exactly one signature cannot carry that. Discovering it after
v1 ships forces a v2 for purely structural reasons.

So the set is modelled now. **No attestation is produced by this session**;
recruitment is still open and no AI collaborator holds attestor key material.
An author signature with zero attestors is a valid instance of the model, and it
is what every substrate emits today.

What the model carries (§7.6.9):
  * the author signature, distinguished from attestor signatures;
  * attestor signatures as a sorted, duplicate-free set;
  * the threshold policy in force, recorded IN the entry;
  * attestor key fingerprints resolvable against a signed roster.

Three rules that are enforced, not merely documented:

  1. **The author signature never counts toward the threshold** (§7.6.2).
     Otherwise 2-of-3 degrades to one independent signer.
  2. **An attestor key equal to the author key is rejected.** Independence is a
     recruitment property this module cannot check, but this much is
     mechanically checkable, so it is checked.
  3. **Threshold not reached is a failure, never a footnote** (§7.6.7). The
     verifier reports the entry as not meeting its own recorded policy. A
     ceremony with a documented bypass is not a ceremony.

Everyone signs the same bytes — ``DOMAIN || deterministic_cbor(structure)`` — so
an attestor attests to exactly what the author signed, and verification is one
code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import cbor, codec

#: Attestor roles (§7.6.5). One person per role gives the 2-of-3 quorum.
ROLE_PROCESS = "process"
ROLE_METHODOLOGY = "methodology"
ROLE_DOMAIN = "domain"
ROLES = (ROLE_PROCESS, ROLE_METHODOLOGY, ROLE_DOMAIN)

_ATTESTATION_KEYS = {"k", "s", "r"}
_SIGSET_KEYS = {"a", "at", "th"}
_POLICY_KEYS = {"n", "m", "roster"}


class AttestationError(ValueError):
    """Raised when a signature set is malformed or violates an attestation rule."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise AttestationError(msg)


@dataclass
class Attestation:
    """One signature over a structure, by a key that a roster can resolve."""
    public_key: bytes            # 32 raw bytes
    signature: bytes             # 64 bytes
    role: Optional[str] = None   # process / methodology / domain

    def to_map(self) -> dict:
        m = {"k": bytes(self.public_key), "s": bytes(self.signature)}
        if self.role is not None:
            m["r"] = self.role
        return m

    @classmethod
    def from_map(cls, m: dict) -> "Attestation":
        _require(isinstance(m, dict), "attestation must be a map")
        unknown = set(m) - _ATTESTATION_KEYS
        _require(not unknown, f"unknown key(s) in attestation: {sorted(unknown)}")
        _require("k" in m and "s" in m, "attestation requires 'k' and 's'")
        _require(isinstance(m["k"], bytes) and len(m["k"]) == 32,
                 "attestation.k must be a 32-byte Ed25519 public key")
        _require(isinstance(m["s"], bytes) and len(m["s"]) == codec.SIGNATURE_LEN,
                 f"attestation.s must be {codec.SIGNATURE_LEN} bytes")
        role = m.get("r")
        if role is not None:
            _require(isinstance(role, str), "attestation.r must be a text string")
        return cls(public_key=m["k"], signature=m["s"], role=role)

    def verify(self, message: bytes) -> bool:
        return codec.verify_raw_ok(
            codec.public_key_from_bytes(self.public_key), message, self.signature)

    def fingerprint(self) -> str:
        """16 hex characters, the form a published roster lists."""
        return codec.fingerprint(codec.public_key_from_bytes(self.public_key))


@dataclass
class ThresholdPolicy:
    """The attestation policy in force when an entry was sealed.

    Recorded IN the entry, not looked up at verification time: a policy that
    could be edited afterwards would let a 2-of-3 entry be reinterpreted as
    author-only. ``required`` counts INDEPENDENT attestors and never includes
    the author.
    """
    required: int                    # n — independent attestors required
    roster_size: int                 # m — roster the threshold is drawn from
    roster_hash: Optional[bytes] = None   # SHA-256 of the signed roster

    def to_map(self) -> dict:
        m = {"n": int(self.required), "m": int(self.roster_size)}
        if self.roster_hash is not None:
            m["roster"] = bytes(self.roster_hash)
        return m

    @classmethod
    def from_map(cls, m: dict) -> "ThresholdPolicy":
        _require(isinstance(m, dict), "threshold policy must be a map")
        unknown = set(m) - _POLICY_KEYS
        _require(not unknown, f"unknown key(s) in threshold policy: {sorted(unknown)}")
        _require("n" in m and "m" in m, "threshold policy requires 'n' and 'm'")
        for k in ("n", "m"):
            _require(isinstance(m[k], int) and not isinstance(m[k], bool) and m[k] >= 0,
                     f"threshold.{k} must be a non-negative integer")
        _require(m["n"] <= m["m"],
                 f"threshold requires {m['n']} of a roster of {m['m']}")
        rh = m.get("roster")
        if rh is not None:
            _require(isinstance(rh, bytes) and len(rh) == 32,
                     "threshold.roster must be a 32-byte hash")
        return cls(required=m["n"], roster_size=m["m"], roster_hash=rh)


#: The default for ordinary commits (§7.6.2). Benchmark versions backing a
#: federal deliverable or an IP filing escalate to 3-of-5.
POLICY_2_OF_3 = ThresholdPolicy(required=2, roster_size=3)
POLICY_3_OF_5 = ThresholdPolicy(required=3, roster_size=5)
#: What every substrate emits today: an author signature and no attestors.
POLICY_AUTHOR_ONLY = ThresholdPolicy(required=0, roster_size=0)


@dataclass
class SignatureSet:
    """An author signature plus zero or more independent attestor signatures."""
    author: Attestation
    attestors: list = field(default_factory=list)
    policy: Optional[ThresholdPolicy] = None

    # ---- encoding -------------------------------------------------------- #
    def to_map(self) -> dict:
        m = {"a": self.author.to_map()}
        if self.attestors:
            # Canonical order: by public key, bytewise. The same set of
            # attestors always encodes to the same bytes.
            ordered = sorted(self.attestors, key=lambda x: bytes(x.public_key))
            m["at"] = [x.to_map() for x in ordered]
        if self.policy is not None:
            m["th"] = self.policy.to_map()
        return m

    @classmethod
    def from_map(cls, m: dict) -> "SignatureSet":
        _require(isinstance(m, dict), "signature set must be a map")
        unknown = set(m) - _SIGSET_KEYS
        _require(not unknown, f"unknown key(s) in signature set: {sorted(unknown)}")
        _require("a" in m, "signature set requires an author signature 'a'")
        author = Attestation.from_map(m["a"])

        attestors = []
        raw = m.get("at")
        if raw is not None:
            _require(isinstance(raw, list) and raw,
                     "signature set 'at' must be a non-empty array when present")
            prev = None
            for item in raw:
                att = Attestation.from_map(item)
                key = bytes(att.public_key)
                if prev is not None:
                    _require(key != prev, "duplicate attestor key")
                    _require(key > prev,
                             "attestor signatures must be sorted by key, bytewise")
                prev = key
                # Rule 2: independence is a recruitment property, but this much
                # is mechanically checkable.
                _require(key != bytes(author.public_key),
                         "an attestor key must not equal the author key")
                attestors.append(att)

        policy = ThresholdPolicy.from_map(m["th"]) if "th" in m else None
        return cls(author=author, attestors=attestors, policy=policy)

    def encode(self) -> bytes:
        return cbor.encode(self.to_map())

    # ---- verification ---------------------------------------------------- #
    def verify(self, message: bytes, roster: Optional["Roster"] = None) -> dict:
        """Verify every signature and report against the recorded policy.

        Inputs:  the exact signed bytes, and optionally the roster in force.
        Outputs: a report dict.
        Postcondition: ``ok`` is True only if the author signature verifies AND
                       the recorded threshold is met by INDEPENDENT attestors.
                       The author never counts toward the threshold.
        """
        problems = []
        author_ok = self.author.verify(message)
        if not author_ok:
            problems.append("author_signature_invalid")

        valid, invalid, unrostered = [], [], []
        for att in self.attestors:
            if not att.verify(message):
                invalid.append(att.fingerprint())
                continue
            if roster is not None and not roster.contains(att.public_key):
                # Rule: fingerprints must be resolvable against a signed roster.
                unrostered.append(att.fingerprint())
                continue
            valid.append(att.fingerprint())
        if invalid:
            problems.append("attestor_signature_invalid")
        if unrostered:
            problems.append("attestor_not_in_roster")

        required = self.policy.required if self.policy else 0
        met = len(valid) >= required
        if not met:
            # Section 7.6.7: the failure mode is an uncommitted artifact, never
            # a committed one with a footnote.
            problems.append("threshold_not_reached")

        if (roster is not None and self.policy is not None
                and self.policy.roster_hash is not None
                and roster.hash() != self.policy.roster_hash):
            problems.append("roster_hash_mismatch")

        return {
            "author_signature": "VALID" if author_ok else "INVALID",
            "attestors_valid": valid,
            "attestors_invalid": invalid,
            "attestors_unrostered": unrostered,
            "threshold_required": required,
            "threshold_met": met,
            "problems": problems,
            "ok": author_ok and met and not invalid and not unrostered
                  and "roster_hash_mismatch" not in problems,
        }


def author_only(private_key, domain: bytes, struct: dict,
                policy: Optional[ThresholdPolicy] = None) -> SignatureSet:
    """Seal a structure with an author signature and no attestors.

    This is what every substrate emits today, and it is a valid instance of the
    n-of-m model rather than a special case outside it.
    """
    msg = codec.signing_bytes(domain, struct)
    return SignatureSet(
        author=Attestation(public_key=codec.public_key_bytes(private_key.public_key()),
                           signature=private_key.sign(msg)),
        attestors=[],
        policy=policy,
    )


def attest(signature_set: SignatureSet, private_key, domain: bytes, struct: dict,
           role: Optional[str] = None) -> SignatureSet:
    """Add an attestor signature over the same bytes the author signed.

    Precondition:  the attestor key differs from the author key.
    Postcondition: the returned set carries the new attestation in canonical
                   order. The input set is not mutated.

    NOTE: attestations are made at seal time, not added to history afterwards.
    The record hash covers the whole signature set, so adding an attestation to
    a committed entry would change its hash and break the chain — which is
    correct: PORTFOLIO_BUILD_PLAN.md §7.6.7 says existing single-signed history
    is never rewritten, and later review is recorded as a new forward-only
    corroboration entry instead.
    """
    msg = codec.signing_bytes(domain, struct)
    pk = codec.public_key_bytes(private_key.public_key())
    _require(pk != bytes(signature_set.author.public_key),
             "an attestor key must not equal the author key")
    new = Attestation(public_key=pk, signature=private_key.sign(msg), role=role)
    return SignatureSet(
        author=signature_set.author,
        attestors=sorted(list(signature_set.attestors) + [new],
                         key=lambda x: bytes(x.public_key)),
        policy=signature_set.policy,
    )


@dataclass
class Roster:
    """A signed list of attestor keys.

    §7.6.7: attestors generate and hold their own keys; a roster records the
    fingerprints so an entry's attestations can be resolved. Roster changes are
    themselves chain entries — see ``roster_event_payload``.
    """
    entries: list = field(default_factory=list)   # [{"id":.., "k": bytes, "roles": [..]}]

    def to_map(self) -> dict:
        return {"v": 1, "e": [
            {"id": e["id"], "k": bytes(e["k"]), "roles": sorted(e.get("roles", []))}
            for e in sorted(self.entries, key=lambda e: bytes(e["k"]))
        ]}

    def encode(self) -> bytes:
        return cbor.encode(self.to_map())

    def hash(self) -> bytes:
        import hashlib
        return hashlib.sha256(self.encode()).digest()

    def contains(self, public_key: bytes) -> bool:
        return any(bytes(e["k"]) == bytes(public_key) for e in self.entries)

    def fingerprints(self) -> list:
        return sorted(codec.fingerprint(codec.public_key_from_bytes(bytes(e["k"])))
                      for e in self.entries)


def roster_event_payload(roster: Roster) -> bytes:
    """The attested bytes of a roster-change chain entry.

    §7.6.7: "roster changes are themselves chain entries". A substrate records
    one by appending an entry whose event type is ``ROSTER_UPDATE`` and whose
    payload is these bytes.
    """
    return roster.encode()


ROSTER_EVENT_TYPE = "ROSTER_UPDATE"
