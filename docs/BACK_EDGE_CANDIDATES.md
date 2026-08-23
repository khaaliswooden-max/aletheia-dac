# Back-edge candidates — defects found under a frozen contract

| | |
|---|---|
| **Document ID** | ALETHEIA-BACKEDGE-001 |
| **Revision** | A |
| **Raised by** | Track A, `zil-provenance` shared core |
| **Date (UTC)** | 2026-08-23 |
| **Status** | Findings. No benchmark file is modified by this document or by the work that produced it. |

Per ZCS-6, a defect discovered in something that is *already passing* is a
candidate for **benchmark tightening** (the Phase 6 → Phase 2 back-edge), not
for quietly patching the candidate or softening the contract. This file records
the candidates Track A surfaced, each with its delta justification, so the
principal investigator can decide.

**Nothing here has been acted on.** `PHRONESIS-1/benchmark/vbx_isps_bench_v1_1.json`,
`Caduceus-1/docs/CADUCEUS-004.md`, `Proteus/proteus-bench-v1.0.2/` and the
EPHEMERIS `planet-time-bench-*.tar.gz` bundles are all unmodified. VERIFIED:
`git status` shows no change to any of them.

---

## BEC-1 — Proteus Loop B hash preimage is unframed

**Marker:** VERIFIED (demonstrated by execution)
**Frozen artifact:** `Proteus/proteus-bench-v1.0.2/auditor/verify_chain.py`, inside a hash-committed bundle

The Loop B row hash is

```
sha256(prev_hash ‖ state_json ‖ signals_json ‖ ts)
```

with no length prefixes and no separators. Field boundaries are therefore
ambiguous, and distinct `(state, signals)` pairs produce identical preimages:

```
state='{"ab":1}'  signals='{}'      →  same hash as
state='{"ab"'     signals=':1}{}'
```

covered by `tests/test_provenance_legacy.py::test_loop_b_preimage_is_unframed_and_ambiguous`.

**Exploitability:** LOW in practice. Both components are machine-generated JSON
from a controlled serializer, so producing a colliding pair requires control of
the state or signal objects that the harness itself builds. It is a latent
structural defect, not a demonstrated attack.

**Why it was not fixed:** the auditor that validates this chain lives inside a
hash-committed benchmark bundle. Changing the row format would break a frozen
benchmark, which is forbidden. `loop_a/chain.py` therefore stays on `v0-loop-b`
permanently and now routes through one shared definition of the construction
(`zil_provenance.legacy.loop_b_row_hash`) with an import-time equivalence
assertion, so writer and auditor cannot drift apart.

**Delta justification if adopted:** a `proteus-bench v1.1` would specify a
length-delimited preimage. The cost is that every existing Loop B chain becomes
unverifiable under the new auditor, so the bundle would need to carry both
auditors during a transition window. B1a's assertion text would gain a framing
requirement; no threshold changes.

**Recommendation:** adopt at the next Proteus benchmark revision that is being
opened for other reasons. Do not open one for this alone.

---

## BEC-2 — Signature covers an ASCII-hex digest, with no domain separation

**Marker:** VERIFIED (direct inspection)
**Frozen artifacts:** the Proteus Loop B auditor; `Proteus/LEDGER_0004.json` as signed history

Two related defects in the pinned formats:

1. Loop B signs `entry_hash.encode()` — the 64 ASCII hex characters of the
   digest — rather than the entry bytes. PHRONESIS signed
   `bytes.fromhex(entry_hash)`, a third convention. Ed25519 already hashes
   internally; pre-hashing adds a step and gives up the collision-resilience
   argument.
2. No signing construction anywhere in the portfolio carried a
   domain-separation tag before v1. A signature over a claim and a signature
   over a chain event were drawn from the same key with no context, so one
   could in principle be presented as the other.

**Exploitability:** LOW given current key usage — the substrates do not
currently share one signing key across both structure kinds — but the property
that prevents it was absent rather than argued.

**Why it was not fixed:** (1) is frozen by the Loop B auditor and by ledger
history. PHRONESIS had no such constraint and **has been migrated** to the v1
construction. (2) is fixed in v1 for both structures.

**Delta justification if adopted:** folded into BEC-1's transition.

---

## BEC-3 — Caduceus T1 epoch conflicts with the shared envelope epoch

**Marker:** PLAUSIBLE (a conflict between two specifications, not a demonstrated failure)
**Frozen artifact:** `Caduceus-1/docs/CADUCEUS-004.md` (caduceus-bench v1.2.1)

`CADUCEUS-004` **T1** signs a canonical tuple including a `timestamp_tuple`, and
**F1** fixes that as `(TAI_microseconds, vbx-body-URN)` with envelope
`[1972-01-01, 2101-01-01)` **TAI**.

The zil-provenance v1 envelope timestamp is **microseconds since the Unix epoch,
UTC** (WIRE_FORMAT.md §4.5), decided so that provenance timestamps carry one
wall-clock convention across all five substrates.

These are different artifacts — a BP7 bundle attestation versus a provenance
envelope — so they **can** coexist, with the peer converting at the boundary.
The conflict becomes real only if `caduceus-attest` is built on the shared
envelope rather than alongside it. `CADUCEUS-005 §2.1` describes it as
constructing "a canonical signed tuple", which does not settle the question.

**Decision required of the principal investigator:** does `caduceus-attest` sign
the shared v1 envelope, its own T1 tuple, or an envelope that carries the T1
tuple inside `ext`?

**Delta justification:** none proposed. If the answer is "the shared envelope",
the resolution is a Caduceus-side conversion layer and an `ext` field, not a
benchmark edit. The benchmark is not wrong; the integration is unspecified.

---

## BEC-4 — PHRONESIS ledger is described as signed history and is not

**Marker:** VERIFIED (direct inspection, 2026-08-23)
**Affected artifacts:** none frozen — this is a documentation defect, not a benchmark defect

`VBX_ISPS_LEDGER_0001` through `0005` each carry

```json
"signing_key": "PLACEHOLDER — production key custody required for Aletheia DAC chain anchor",
"ots_anchor":  "PLACEHOLDER — OpenTimestamps anchor to be appended on chain submission"
```

no signature field, and no public key exists anywhere in that repository. They
also use two incompatible schemas: `0001`–`0003` carry `commit_id` /
`artifacts[]` / `commit_root_sha256`, while `0004`–`0005` carry `ledger_number` /
`manifest_sha256{}` / `commit_root`.

Both the Track A brief and **PORTFOLIO_BUILD_PLAN.md §4** describe them as
"signed history". They are not. PHRONESIS-1's own §7.3 ("no ceremony exists
anywhere") is the accurate statement, and §4 contradicts it.

**What was done instead:** a `v0-phronesis-unsigned` tag that verifies what is
actually there — predecessor linkage and manifest integrity — and reports
`signature: ABSENT` rather than passing them silently. Nothing was re-signed.
Linkage across all five VERIFIED intact; the schema split is pinned by a test.

**Recommendation:** correct §4 of PORTFOLIO_BUILD_PLAN.md, and correct
§10.3's "all pre-existing signed ledger entries still verify" to name the one
artifact that criterion actually binds on — `Proteus/LEDGER_0004.json`, which
does verify. That correction is the principal investigator's to make; this
document only reports it.

---

## Non-candidates — pressure that was resisted

Recorded because "no benchmark was edited" is stronger evidence when the near
misses are named.

- **PHRONESIS chain migration to v1.** Tempting to check the benchmark for a
  format assertion to relax. Not needed: `vbx_isps_bench_v1_1.json` constrains
  chain *properties* (append-only, signed, hash-linked, replayable,
  integrity-verifiable), not a byte format. VERIFIED by reading its HF-8 text.
  The migration touches no assertion.
- **The PHRONESIS `chain` table column count.** The HF-8 red-team test inserts
  positionally with seven values, so adding a `fmt` column would have broken a
  passing test. The format version went into a `chain_meta` side table instead.
  The test was not edited.
- **Float payloads in PHRONESIS events.** The no-float rule initially rejected
  the substrate's own telemetry. The wrong fix would have been to weaken R6 or
  to rewrite application data. The right fix was recognizing that a chain entry
  attests an *opaque byte string* and does not interpret it — which is also
  better for the Rust and C implementations, since they never have to
  re-serialize a payload identically.
