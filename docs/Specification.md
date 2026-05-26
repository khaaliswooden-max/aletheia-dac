# Aletheia™ — Drift-Aware Attestation Substrate
### Platform Specification v0.1 (working draft)

**Author:** A. Khaalis Wooden, Sr. | MBA; MSIT Candidate, Southern New Hampshire University
**Org:** Zuup Innovation Lab / Visionblox LLC
**Status:** Proposed (reference implementation built and passing acceptance tests)
**Working name:** *Aletheia* (Gk. *alētheia*, "unconcealment") — placeholder; folds naturally into **Civium** as its attestation sublayer. Rename at will.

---

## 1. Why this road, and why now

The five-substrate analysis surfaced three meta-gaps that recur across *every* road
(energy, representation, intent, spatial frame, agency). Two of them are the same
problem wearing two coats:

- **Gap #2 — provenance and calibrated confidence do not survive the stack.** Origin,
  license, consent, and error bars get stripped every time data moves up a layer
  (raw signal → embedding → map → decision → action).
- **Gap #1 — nothing knows when its own knowledge has expired under drift.** Every
  road's hardest open problem is *coherence under non-stationarity*.

A system can only act safely on what it can (a) trace, (b) bound the confidence of, and
(c) know is still valid. Today those three properties live in disconnected, hand-built
places — audit logs here, a softmax there, a TTL somewhere else — and none of them
compose. `Aletheia` makes them a single, portable, composable primitive.

> This is not a new model or a new sensor. It is the **interface contract between
> layers** — the thing that was missing under all five roads. [VERIFIED as whitespace:
> cross-references your `Rural_Biomedical_LLM_FTO` "calibration audit countering silent
> drift" and `Formal_Verification_Compliance_FTO` Civium hash-chain/OSCAL claims.]

---

## 2. The primitive: a Drift-Aware Claim (DAC)

Every artifact any layer produces is wrapped in a DAC — a signed, hash-chained envelope:

```jsonc
{
  "id": "uuid",
  "kind": "sensor_reading | embedding | map_tile | policy_decision | inference",
  "payload_hash": "sha256(payload)",        // artifact stays where it lives; DAC is metadata
  "producer_id": "encoder.layer2",
  "producer_fpr": "ed25519 pubkey fingerprint",
  "parents": ["dac_id", ...],               // provenance DAG edge set
  "confidence": {                           // calibrated, not a raw softmax
    "method": "split_conformal | aci | asserted",
    "value": 0.92,                          // achieved coverage level (1 - alpha)
    "alpha": 0.08,
    "interval": [lo, hi]
  },
  "validity": {
    "monitor_id": "stream_A",               // which drift monitor governs this claim
    "issued_at": 1690000000.0,
    "expires_at": 1690003600.0,
    "status": "VALID | STALE | REVOKED"
  },
  "classification": "PUBLIC|INTERNAL|CONFIDENTIAL|REGULATED",
  "requires_hitl": true,
  "prev_hash": "sha256 chain link",         // tamper-evident audit (Civium-aligned)
  "sig": "ed25519 over semantic fields"
}
```

The artifact itself is never moved — the DAC carries a hash of it. The DAC *is* the road.

---

## 3. Three mechanisms (each a real, established technique)

### 3.1 Monotone propagation — confidence/provenance cannot be silently dropped
When layer *N* derives a DAC from parent DACs, the runtime enforces:

| Field | Rule | Meaning |
|---|---|---|
| `confidence.value` | `min(self, parents)` | a chain is only as trustworthy as its weakest link |
| `validity` window | **intersection** of parent windows | derived claim expires when *any* input does |
| `classification` | `max` sensitivity over self + parents | REGULATED inputs taint downstream |
| `requires_hitl` | logical **OR**, forced true if REGULATED | human gate survives composition |
| `status` | STALE if **any** parent non-VALID | cannot derive fresh from stale |

This is the mechanism that makes confidence + provenance **survive the stack**. It is
not optional metadata; it is a typed precondition for issuing a derived claim.
[VERIFIED in code: acceptance tests T3, T4.]

### 3.2 Calibrated confidence — split conformal + Adaptive Conformal Inference
- **Split conformal prediction** (Vovk et al. 2005; Angelopoulos & Bates 2021) gives a
  distribution-free, finite-sample marginal coverage guarantee: P(y ∈ interval) ≥ 1−α.
  Confidence becomes a *grounded coverage level*, not an uncalibrated model score.
  [VERIFIED: T5 — empirical coverage 0.885 at target 0.90.]
- **Adaptive Conformal Inference / ACI** (Gibbs & Candès, NeurIPS 2021) updates α online
  — `α_{t+1} = α_t + γ(α_target − err_t)` — to hold coverage *even under drift*, with no
  exchangeability assumption. This is the bridge that ties confidence (#2) to drift (#1):
  the confidence object reacts to drift instead of silently going wrong.
  [VERIFIED: T7 — under a 3× distribution shift, static conformal coverage collapses to
  **0.404** while ACI holds **0.897**.]

### 3.3 Drift-triggered invalidation — the non-stationarity engine
- A **DriftMonitor** governs each input stream using **Page-Hinkley** (Page 1954; online
  mean-shift) and/or a **two-sample Kolmogorov–Smirnov** test (distributional shift).
- When a monitor trips, the store **cascades STALE** through the provenance DAG: every
  DAC bound to that monitor, and everything transitively derived from it, flips to STALE;
  independent claims are untouched. The system now *knows when its own knowledge expired.*
  [VERIFIED: T6 — shift on `stream_A` cascaded to exactly its 3 dependents; the
  independent `stream_B` claim stayed VALID.]
- This is the operational form of the formalism your **Non-Stationarity Mathematical
  Proofs** whitepaper is circling — drift is no longer an unmodeled hazard; it is a
  first-class, monitored event with a defined invalidation semantics.

---

## 4. Where it sits / zero-budget (MVCI) stack mapping

```
 Layer 5  agency/action  ──issues DAC──┐
 Layer 4  spatial map    ──issues DAC──┤   monotone
 Layer 2  representation ──issues DAC──┤   propagation   ┌────────────┐
 Layer 0  perception     ──issues DAC──┘  ───────────▶   │  Aletheia  │
                                                          │  runtime   │
        DriftMonitor(stream) ──trip──▶ cascade_stale ───▶ │ + store    │
                                                          └─────┬──────┘
                                                                ▼
                                              SQLite claims + hash chain (audit)
```

| Concern | MVCI-compliant component | Status |
|---|---|---|
| Identity / attestation | Ed25519 (`cryptography`) | built |
| Audit integrity | SHA-256 hash chain in SQLite | built |
| Calibration math | numpy / scipy (split conformal, ACI) | built |
| Drift detection | Page-Hinkley + KS (scipy) | built |
| Orchestration | n8n nodes wrapping `issue()` / `cascade_stale()` | scaffold |
| Local inference | Ollama / Mistral-7B producers emit DACs | scaffold |
| Storage | SQLite (→ Postgres/Neo4j at scale) | built (SQLite) |

No paid APIs, no SaaS. Runs on the existing zero-budget stack.

---

## 5. Acceptance criteria (all passing in the reference build)

| # | Property | Result |
|---|---|---|
| T1 | Signature catches payload tampering | PASS |
| T2 | Hash chain catches store tampering | PASS |
| T3 | Confidence propagates as weakest link (→ 0.92) | PASS |
| T4 | REGULATED sensitivity + HITL propagate downstream | PASS |
| T5 | Split-conformal empirical coverage ≥ 1−α | PASS (0.885 @ 0.90) |
| T6 | Drift cascades STALE to dependents only (3 of 3) | PASS |
| T7 | ACI holds coverage under drift; static collapses | PASS (0.897 vs 0.404) |

Run: `python3 acceptance_tests.py`. Seeds fixed for reproducibility.

---

## 6. Honest gap analysis of *this* road (what it does NOT yet solve)

Per the project's gap-analysis protocol — the substrate has real open gaps:

1. **[PLAUSIBLE→OPEN] Confidence combination under dependence.** `min` is the safe,
   conservative default. For genuinely *independent* corroborating evidence, `min`
   under-counts confidence; a principled combiner (e.g., calibrated fusion) is unbuilt.
2. **[OPEN] Monitor coverage is only as good as what you choose to monitor.** A drift in
   an *unmonitored* variable is invisible. There is no automatic discovery of which
   statistics to watch — currently a human declares `monitor_id` per stream.
3. **[OPEN] Semantic provenance vs. byte provenance.** The DAC proves *which artifact* and
   *who produced it*; it does not prove the artifact *means* what the producer claims.
   Bridges to the Road 2 interpretability gap, which remains open.
4. **[SPECULATIVE] Cross-organization trust root.** Within one org, producer keys are
   trusted by registration. Federated trust across CAHs / consortia needs a key-distribution
   / revocation layer (your federated-calibration FTO target is the natural home).
5. **[OPEN] Conformal assumptions.** Split conformal needs exchangeability; ACI relaxes it
   but its coverage is *long-run/marginal*, not conditional — it can be miscalibrated on
   rare subpopulations. Honest confidence ≠ perfect confidence.
6. **[OPEN] Liability semantics.** A STALE-but-acted-on claim has defined provenance but
   undefined legal accountability. This is the Road 5 gap; Aletheia makes it *auditable*,
   not *resolved*.

---

## 7. Domain mapping (why each Zuup line wants this)

- **Civium** — DACs are the native audit/attestation record; monotone propagation is
  compliance-as-data-flow; OSCAL export is a serializer over the claim store.
- **Aureon** — its vector embeddings (Road 2) become DACs; stale source opportunities
  self-invalidate instead of silently aging.
- **QAWM** — operationalizes the "Irreducible Uncertainty" axiom: every reconstructed
  past-state ships with a conformal confidence and a validity window.
- **RCA** — Layer 0/1 perception emits DACs; the epistemic confidence marking you already
  practice in prose becomes infrastructure, machine-checkable across layers.
- **Rural (CAH/RWA)** — an HTI-1 inference or a pump-sensor reading carries its provenance
  + calibrated confidence to the point of action; a sensor distribution shift cascades
  staleness to every downstream recommendation automatically.
- **Federal procurement agent** — REGULATED actions inherit a forced human-in-loop gate by
  construction; an auditor replays the signed hash chain end-to-end.

---

## 8. Build roadmap

- **Phase 1 (now → 30 days):** harden reference impl; n8n wrapper nodes; OSCAL/Civium
  export; publish to `github.com/khaaliswooden-max/zandbox` with this spec + tests.
- **Phase 2 (90 days):** monitor auto-suggestion (which statistics to watch); Postgres/Neo4j
  store backend; conditional-coverage diagnostics; a first CAH or RWA pilot stream.
- **Phase 3:** federated trust root across consortium members; IEEE paper —
  *"Drift-Aware Attestation: a portable epistemic substrate for non-stationary autonomous
  systems"* — extending your non-stationarity proofs whitepaper as the formal core.

---

*Reference implementation: `dac.py` (substrate) + `acceptance_tests.py` (falsifiable proof).
All mechanisms are established techniques composed into a novel primitive; the novelty is
the composition and the cross-layer propagation contract, not any single component.*
