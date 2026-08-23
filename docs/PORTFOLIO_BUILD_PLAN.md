# Portfolio Build Plan — Five-Substrate Parallel Build

| | |
|---|---|
| **Document ID** | ALETHEIA-PORTFOLIO-001 |
| **Revision** | A (draft) |
| **Scope** | aletheia-dac · PHRONESIS-1 · EPHEMERIS-1 · Proteus · Caduceus-1 |
| **Author** | A. Khaalis Wooden, Sr. / Visionblox LLC / Zuup Innovation Lab |
| **Date (UTC)** | 2026-08-23 |
| **Status** | Planning artifact. No phase is authorized by this document; it orders work that the per-repo roadmaps already specify, and names work they omit. |
| **Epistemic note** | Every load-bearing claim carries VERIFIED / PLAUSIBLE / SPECULATIVE per house convention. Every quantitative claim carries a Trutina label (`requirement` / `measured` / `target`) per §9. |

---

## 0. Honest status line

This is a plan, not a result. Nothing here is built. Where a number appears, §9
says whether it is a customer/benchmark requirement, an actual measurement, or
design intent. No claim in this document is backed by a Trutina EvidenceRecord,
because none exist yet for this portfolio — §9 names the records that would be
needed to upgrade the load-bearing ones.

---

## 1. The finding that shapes everything

**These five repositories are not five parallel builds. They are one substrate
with four consumers, and two of the five are integrations of the others.**
[VERIFIED — from the repositories' own planning documents, cited inline]

- `CADUCEUS-005 §3` lists **Aletheia DAC v0.2 → v0.3**, the **Civium authority
  graph**, and the **Mercury Subleq kernel** as internal dependencies. All three
  live in PHRONESIS-1, not in Caduceus-1.
- `CADUCEUS-005 §2.8` makes the **EPHEMERIS-side peer module** a Caduceus
  deliverable — firmware on a Cortex-M-class MCU, paired over UWB/BLE.
- `Proteus/ROADMAP.md`: *"ACI skill proxy already shared with Ephemeris;
  Aletheia provenance pattern already shared with the chain."*

So the true graph is:

```
        aletheia-dac ──────┐
        (DAC substrate)    │
                           ├──► Caduceus-1  (capstone integration)
        PHRONESIS-1 ───────┤    needs all four upstream
        (Aletheia chain,   │
         Civium, Mercury)  │
                           │
        EPHEMERIS-1 ───────┤    also supplies the Caduceus peer device
        Proteus ───────────┘    also supplies the ACI skill proxy
```

Caduceus M1 cannot begin until Aletheia v0.3 and the Civium revocation-stream
extension exist. Everything else genuinely can run concurrently.

### 1.1 What ignoring this already cost

**There are four independent Ed25519 hash-chain implementations in the tree.**
[VERIFIED — enumerated by direct inspection, 2026-08-23]

| File | Lines | Language |
|---|---|---|
| `aletheia-dac/src/aletheia/dac.py` | 377 | Python |
| `PHRONESIS-1/substrate/src/aletheia/chain.py` | 258 | Python |
| `Proteus/zil_sign.py` | 206 | Python |
| `Proteus/loop_a/chain.py` | 72 | Python |

Two more are specified and unbuilt: EPHEMERIS assertion **A7** (deferred to
firmware v0.3, described in its roadmap as mirroring "the Aletheia DAC pattern")
and the Caduceus crate **`caduceus-attest`**, planned in Rust.

Six divergent signing formats would make cross-substrate verification
impossible, which falsifies the one claim every repository in the portfolio
makes — that provenance is portable. This is the highest-leverage defect in the
portfolio and it is cheap to fix now and expensive to fix after Caduceus M2.

### 1.2 The missing artifact

**There is no language-independent wire-format specification for a DAC
envelope or a chain entry.** [VERIFIED — no schema file exists in any of the
five repositories]

Today the envelope is defined by Python source. `caduceus-attest` must produce
byte-identical signed tuples from Rust; the EPHEMERIS peer must verify them from
embedded C on a Cortex-M. Without a canonical encoding fixed by specification —
deterministic CBOR with a CDDL schema is the obvious candidate, and Caduceus has
already independently selected `serde` + `ciborium` — those three
implementations cannot interoperate, and no amount of later testing will make
them.

**Wave 1 therefore begins with a shared provenance core, not with any of the
five roadmaps.** See §3.

---

## 2. Wave structure

Waves are gated by what unblocks the most downstream work per unit of cost, not
by repository.

| Wave | Duration | Cost posture | Gate to exit |
|---|---|---|---|
| **0 — Unblock** | days | ~zero | Provisional flags cleared; practitioner engaged |
| **1 — Shared core + software-only tracks** | weeks | labor only | One verifier validates chains from all five |
| **2 — Procurement-gated** | months | capital + hiring | HSM in service; scenario library exists; EPHEMERIS BOM conflicts resolved |
| **3 — Facility-gated** | quarters | major capital + partners | Silicon, beam time, shell partner, DTN testbed |

---

## 3. Wave 0 — Unblock (days, approximately zero cost)

These four items are disproportionate in value to their cost. Every one of them
removes a blocking flag that currently makes downstream results inadmissible.

### 3.1 Lock the three Proteus externalities

`Proteus/harness/ENVIRONMENT.md` marks three values `HASH PENDING`, and states
that until they are locked **every measured result is provisional and must carry
`"stub_validation": true`**:

1. llama.cpp upstream commit hash (tag `b6500+`)
2. exact `python --version` output
3. SHA-256 and HF repo revision of `Mistral-7B-Instruct-v0.3.Q4_K_M.gguf`

**Owner:** operator. **Effort:** half a day. **Unblocks:** the entire Proteus
Phase 5 measured-results track. This is the single cheapest unblock in the
portfolio. [VERIFIED — the file states the dependency explicitly]

### 3.2 Stand up CI on Caduceus-1

Four of five repositories have GitHub Actions workflows. Caduceus-1 has none.
[VERIFIED — `.github/workflows` absent] It is also the repository planning ~330
tests across seven new Rust crates. Add the workflow before M2, not at M7.

### 3.3 Clear the two pending OpenTimestamps stamps

Proteus v1.0.2 bundle hash and the Caduceus LEDGER #0004 artifacts both await
operator action. Bitcoin confirmation latency is roughly 6–24 hours, so this is
wall-clock, not labor.

### 3.4 Engage a registered USPTO patent practitioner

`CADUCEUS-PRACTITIONER-001 §5` defines a twelve-step sequence whose **step 1 is
"identify and engage practitioner."** Three Caduceus PPA skeletons and the
PHRONESIS cross-modal-fabric PPA all wait on this one person. It is the longest-
lead non-engineering item in the portfolio and it is not staffed.

---

## 4. Wave 1 — Shared core and software-only tracks (weeks, labor only)

Five concurrent tracks. Track A gates the others' *integration*, not their
*start*, so all five begin together.

### Track A — `zil-provenance`, the shared core (the critical path)

The extraction described in §1. Scope:

1. **A versioned wire-format specification** — canonical deterministic encoding
   (CBOR + CDDL recommended), one DAC envelope schema, one chain-entry schema,
   explicit versioning and unknown-field rules.
2. **A reference implementation in Python**, replacing the four implementations
   in §1.1 behind adapters that preserve each repository's existing public API.
3. **A conformance test vector suite** — signed fixtures that any implementation
   in any language must reproduce byte-for-byte.
4. **One verifier** that validates a chain from any of the five substrates.
5. **A persistent Ed25519 keystore**, replacing aletheia-dac's per-process
   ephemeral keys — already the first item of its own Phase 1 roadmap, and the
   reason it cannot currently back the other four.

**Non-goal for Wave 1:** the Rust and embedded-C implementations. Wave 1 fixes
the *specification and the vectors*; Rust follows in Caduceus M2 and embedded C
in EPHEMERIS v0.3, both validated against the same vectors.

**Critical constraint:** existing signed artifacts must continue to verify.
LEDGER #0004 (Proteus) and LEDGER #0001–#0005 (PHRONESIS) are signed history.
The core must verify legacy entries under a v0 format tag, never re-sign them.

### Track B — PHRONESIS v0.2-β

Pure software; its roadmap explicitly notes no new external or hardware
dependency. Lean 4 + mathlib for the Mercury WCET proof; OpenTimestamps
anchoring; the standalone chain-replay CLI; CycloneDX 1.6 + SPDX 2.3 validation
for C-3 closure. The replay CLI should be built *on* Track A rather than beside
it — it is the natural first consumer.

### Track C — Proteus F0 baseline

Immediately after §3.1. Note the hardware constraint in §6.4: the benchmark
mandates CPU-only inference, so this needs a dedicated machine for days of
wall-clock, not an afternoon.

### Track D — EPHEMERIS Tier 0 + firmware v0.3 assertions

Tier 0 cleanup is trivial and listed in its roadmap. The v0.3 assertions (A2
light-time, A4 relativistic, A3 pixel-level audit, MCU-precision truncation) are
software. **A7 — the signed update path — should be deferred until Track A ships
its vectors,** so EPHEMERIS implements the shared format rather than a fifth
variant.

### Track E — Caduceus paper, formal-methods scaffolding, and CI

Everything on the Caduceus critical path is gated (§7.1), but the Lean 4 and
TLA+ obligations in `CADUCEUS-006` can be scaffolded, and §3.2 lands here.

---

## 5. Wave 2 — Procurement-gated (months)

| Item | Repo | Blocking on |
|---|---|---|
| FIPS 140-3 L3 HSM for signing + PHI keys | PHRONESIS | vendor selection, capital |
| ≥1000-entry labeled scenario library | PHRONESIS | domain-expert labeling |
| Mistral-7B production inference host | PHRONESIS | 16 GB+ VRAM or Orin NX |
| EPHEMERIS hardware respin | EPHEMERIS | §6.3 conflicts resolved first |
| Caduceus M1 → M4 | Caduceus | Aletheia v0.3 + §7.1 decision |
| Multi-party n-of-m attestation | all | recruiting independent attestors |

Two items in this table are routinely underestimated:

**The PHRONESIS scenario library does not exist.** HF-12 threshold
re-validation and the v0.3 calibration audit both block on ≥1000 labeled state
vectors spanning nuanced-band, safety-floor, sensor-fault, validity-violation,
comm-loss, and multi-fault dispatch. That is domain-expert labeling work, not a
week of engineering. [VERIFIED — `PHRONESIS-1/ROADMAP.md` v0.3, marked "dataset
construction needed"]

**Multi-party attestation is recruitment, not schema work.** EPHEMERIS
`SECURITY.md` names single-attestor commits as the largest known methodology gap
in the whole ZCS-6 approach. The schema is estimated at 3 days; finding
independent attestors willing to sign is the actual cost, and it is unstaffed.

---

## 6. Per-repository build sheets

### 6.1 aletheia-dac — pure software, buildable today

**Hardware/materials:** none. One workstation.

**Software present:** `numpy`, `scipy`, `cryptography`; stdlib CLI; optional
FastAPI service; 7 acceptance tests; CI configured.

**Software needed:** persistent Ed25519 keystore; OSCAL 1.1.x schema validator
in CI; n8n community node (introduces a TypeScript toolchain new to the
portfolio); Postgres or Neo4j `ClaimStore` backend behind the existing
interface.

**Design innovations owed** — the repository's own open-gap list, none solved:
independent-evidence confidence fusion to replace `min`-combination (gap #1);
drift-monitor auto-selection (gap #2); conditional-coverage diagnostics (gap
#5); cross-organization trust root and key distribution (gap #4).

**Omitted from its roadmap and required:** the wire-format specification of
§1.2. This is the portfolio's critical path and it is currently nobody's task.

### 6.2 PHRONESIS-1 — deepest hardware bill

**v0.2-β (software):** Lean 4 + mathlib; OpenTimestamps client; chain-replay
CLI; CycloneDX 1.6 + SPDX 2.3 validators.

**v0.3 (procurement):** FIPS 140-3 Level 3 HSM for the Ed25519 signing key and
the Fernet PHI key, satisfying HIPAA §164.312(a)(2)(iv); vendor unselected. A
Mistral-7B inference host. The scenario library of §5.

**v1.0 (silicon and facilities):**
- Dedicated MCU plus separate AP processor over a controlled message bus,
  moving bus isolation from software surrogate to silicon. Hardware partner
  needed; none identified.
- TPM 2.0 for measured boot.
- Anti-tamper enclosure with tamper-evident sealing and chain-of-custody
  logging.
- **Radiation path decision:** NASA Class B parts (expensive, long-lead) or
  COTS with documented TMR / watchdog / ECC mitigation. Jetson Orin NX is
  consumer-grade and will not fly as-is. The roadmap marks this SPECULATIVE and
  it remains an open architectural decision, not a procurement task.
- Facility access: proton and heavy-ion beam time, thermal-vacuum cycling, and
  vibration to NASA-STD-7003A. **Beam time is booked months ahead and is the
  schedule driver for v1.0, not the engineering.** [PLAUSIBLE — general
  characteristic of accelerator facility scheduling; specific lead times not
  confirmed with any named facility]

**v1.2:** a spacesuit OEM partner (ILC Dover, Collins, Axiom class) owning HF-1
through HF-7 and HF-11. Pre-contractual.

**Omitted and required:** export-control review (see §7.2); a named insurance
underwriter willing to run the HF-15 dry-run, which is a relationship rather
than a deliverable.

### 6.3 EPHEMERIS-1 — real BOM, two hard conflicts

The blueprint carries a genuine bill of materials. All values are `target`
(design intent from a sketch-only drawing), not `requirement` or `measured`:

| Item | Spec | Label |
|---|---|---|
| Crystal | Sapphire, AR-coated, 1.2 mm | target |
| Display | 1.4″ AMOLED, 466×466, 50,000 cd/m² peak | target |
| Ambient sensor | Lux + IR cut, 1 lx – 100 klx | target |
| Mainboard | 4-layer FR4: MCU + SE + Flash + 9-DOF IMU + CSAC + GNSS | target |
| Antenna | Ceramic patch, L1/L5 | target |
| Battery | Li-ion 500 mAh, custom L-shape | target |
| Caseback | Grade-5 titanium, IP68 / 100 m | target |
| Envelope | 44.0 × 13.5 × 52.0 mm, 78 g, −20…+60 °C, MIL-STD-810H | target |

#### Conflict 1 — A5 and A6 are mutually exclusive at 500 mAh

[VERIFIED as arithmetic; PLAUSIBLE as a system conclusion — see the caveat]

- A5 is a scoring assertion: ≥14 days on 500 mAh. `requirement`.
- 500 mAh × 3.7 V = 1.85 Wh = 6660 J. `target` (derived from the BOM target).
- 14 days = 1.209 × 10⁶ s.
- Therefore the **whole-system average power budget is ≈5.5 mW** — display,
  MCU, IMU at 50 Hz, GNSS, and CSAC combined.
- A chip-scale atomic clock in the Microchip SA.45s class draws on the order of
  120 mW continuous — roughly **22× the entire system budget**. `target`
  (vendor datasheet class figure, not measured here, no EvidenceRecord).

The blueprint annotates CSAC as "(Pro)", which reads as a distinct SKU. **If it
is a separate SKU, say so explicitly in the spec: the Pro SKU cannot claim A5 at
500 mAh.** If it is not, this is a genuine falsification and the correct ZCS-6
response is a v1.3 benchmark back-edge, not a firmware patch. Options: duty-
cycle the CSAC with documented holdover degradation; grow the cell; or split the
assertion by SKU.

**This decision is required before any EPHEMERIS hardware spend.**

#### Conflict 2 — 50,000 cd/m² has no wearable supplier

[PLAUSIBLE — no supplier survey has been run; stated as a procurement risk, not
a measured finding]

Shipping wearable AMOLED panels peak roughly one order of magnitude below this
figure. At 1.4″ the spec implies a microLED path with no identified volume
supplier.

The good news is structural: **A3 audits contrast, font size, and luminance
sweep — not an absolute nit figure.** The display spec is therefore a hardware
choice that can be revised without touching the frozen benchmark. Revise it
deliberately, record the revision, and do not let it drift silently.

#### Software

Firmware in the bundles is Python 3.12. Real hardware means C or embedded Rust,
with **polynomial fits truncated to MCU precision** — already a Tier-1 roadmap
item, and the honest acknowledgement that current sub-millisecond accuracy is a
desktop-float artifact. Plus the deferred assertions: A2, A4 (Schwarzschild +
PPN validity envelope), A3 pixel-level audit over 1000 rendered frames, and A7
against the Track A vectors.

#### Omitted and required

- **A reduced on-device ephemeris.** DE441 kernels are far too large for the
  described flash. Error-bounded Chebyshev fits against the frozen oracle are
  themselves an engineering deliverable, and the reduction could violate A1a or
  A1b. Nothing in the roadmap scopes it.
- EMC/FCC/CE certification; UN 38.3 Li-ion transport testing.
- CSAC export-control screening (see §7.2).

### 6.4 Proteus — cheapest start, real compute bill

**Software, fully pinned** in `harness/requirements.txt`: `llama-cpp-python
==0.3.2`, `numpy==1.26.4`, `pydantic==2.9.2`, `scipy==1.13.1`,
`cryptography==50.0.0`; dev `pytest==9.1.1`, `hypothesis==6.165.10`.

**Hardware.** Benchmark §2 mandates **CPU-only inference for every measured
run — GPU acceleration is not permitted** for any result compared against
committed thresholds. So: a high-core-count CPU box, ≥16 GB RAM, running 3
suites × 5 seeds × 10 episodes at 8k context on a 7B Q4_K_M model. Budget days
of wall-clock. Log `{cpu_model, ram_gb, gpu_model_or_none, os, threads_used}`
per the `HardwareTag` schema on every run. v0.4 additionally wants a Jetson Orin
Nano Super (~$249 `target`, from the roadmap) for the optional LoRA path.

**Design innovations owed:** F-A3 graded nonconformity — binary success/failure
scoring saturates the ACI skill proxy at zero for weak models, degenerating the
flow gap to challenge alone; the KV-cache fragility audit plus canonical-state
regeneration fallback; `repeng` contrast-pair control-vector training for Loop
C; the promotion-gate and canary-isolation harness.

**Omitted and required:** Phase 6 is *defined* as requiring external review by
at least one outside party with test-time-adaptation, conformal-prediction, or
compliance-bound-ML background. That is recruitment, and it is unstaffed.

### 6.5 Caduceus-1 — gated capstone

**Hardware:** Jetson Orin NX 16 GB, shielded enclosure, ≤200 W peak
(`requirement` per `CADUCEUS-005 §1.2`); a Cortex-M-class MCU for the EPHEMERIS
peer; a secure element; UWB or BLE radios plus NFC pairing.

**Software stack, locked at planning time:** ION-DTN 3.7.x (BP7 / RFC 9171),
libsodium 1.0.20+, HKDF (RFC 5869), Rust stable + nightly, `pest` or `nom`,
`serde` + `ciborium`, OpenTimestamps client.

**Seven new Rust crates:** `caduceus-attest`, `-gate` (6 weeks, the largest and
deepest module), `-aci`, `-bodyid`, `-nonce-set`, `-interlock`, plus the HF-20
Mercury integration layer.

**Formal methods:** Lean 4 *and* TLA+ obligations for T1, T3, T7, F4, and §3.6
per `CADUCEUS-006`. Two proof assistants, two skill sets, one team.

**Omitted from the plan and required:**

- **A light-time link emulator.** Testing 4–22 minute round-trip authority
  propagation, stale-graph timers, revocation races, and the 90-day adversarial
  flood requires a DTN testbed that injects multi-minute delay, disruption, and
  asymmetric outage. M3, M6, and M7 all depend on it and none scopes it. This is
  the largest omission in an otherwise detailed plan. [VERIFIED — no test-
  infrastructure line item appears in `CADUCEUS-005 §4` or §5]
- **A constant-time analysis harness.** `dudect` / `ctgrind` appear as pass
  criteria in §5 with no harness and no sufficiently quiet machine scoped.
- **Per-link theoretical-floor constants** (§3.7) require a real RF link budget
  for a specific mission configuration — an RF engineer, not a software
  engineer. M1 gates on it.

---

## 7. Cross-cutting

### 7.1 The IP gate — a decision is required

`CADUCEUS-005 §4.1` makes **M0 "PPA filings confirmed"** the entry gate to M1.
`CADUCEUS-PRACTITIONER-001 §5` step 12 states that beginning the Phase 5
substrate build is **independent of the IP track**. These two statements
conflict, and the conflict currently blocks Caduceus.

Separately and not in conflict: step 11 requires the arXiv preprint to follow
PPA filing by at least one business day, to preserve Paris Convention foreign-
filing rights. That constraint is legal and is not in question — publication
waits.

**Required decision (principal investigator only):** does M0 block M1, or does
substrate build proceed in parallel with the IP track while publication remains
gated? This is a legal call and this document does not make it.

### 7.2 Export control — unaddressed in all five

None of the five repositories addresses export control. [VERIFIED — no ITAR,
EAR, or USML discussion appears in any repository] The exposure is real and
plural: a chip-scale atomic clock, a spacesuit decision substrate, interplanetary
DTN authority propagation, and strong cryptography throughout. It interacts
badly with public Apache-2.0 development and with recruiting outside attestors
and reviewers.

**This needs a screening before Wave 2 procurement, not after.** [PLAUSIBLE —
exposure asserted from the nature of the artifacts; no legal review performed]

### 7.3 Key management — no ceremony exists anywhere

Five repositories, ephemeral or filesystem-resident keys, no rotation, no
revocation path, no HSM, and single-attestor commits. The Track A keystore is
the floor, the Wave 2 HSM is the target, and multi-party attestation is the gap
the methodology itself names as its largest.

### 7.4 Staffing

`CADUCEUS-005 §4.1` estimates **20 weeks at roughly 3.25 FTE** for Caduceus
alone (2 engineers plus 1 firmware engineer). Adding PHRONESIS silicon and
firmware, EPHEMERIS hardware EE and industrial design, an RF engineer for the
link budget, a Lean 4 specialist, and a labeling team for the scenario library,
true five-way parallelism needs roughly **6–8 FTE** [PLAUSIBLE — additive
estimate from the per-repository plans; no bottom-up staffing model built]
against one principal investigator today.

This is the honest constraint on the word "parallel." Waves 0 and 1 are
achievable by a very small team. Waves 2 and 3 are not.

### 7.5 Compliance and capture

CMMC Level 2 self-assessment and an SPRS score gate the DoD-side capture
channels that would fund Waves 2 and 3. The framework is complete in
`CADUCEUS-CMMC-001`; the attestation is not done.

---

## 8. Decisions required before Wave 2

| # | Decision | Owner | Blocks |
|---|---|---|---|
| D1 | Does Caduceus M0 block M1? (§7.1) | PI + practitioner | all Caduceus build |
| D2 | Is EPHEMERIS CSAC a separate Pro SKU? (§6.3) | PI | all EPHEMERIS hardware spend |
| D3 | Revise the display target, or seek a microLED supplier? (§6.3) | PI | EPHEMERIS BOM |
| D4 | ~~Canonical encoding for the shared core~~ **DECIDED 2026-08-23: deterministic CBOR, RFC 8949 §4.2.1** (§1.2) | PI — closed | — |
| D5 | PHRONESIS radiation path: Class B or mitigated COTS? (§6.2) | PI | v1.0 architecture |
| D6 | Who are the independent attestors? (§5) | PI | methodology credibility |

**D4 is closed:** deterministic CBOR per RFC 8949 §4.2.1, bound in
`docs/PROMPT_shared_provenance_core.md`. It carries one open sub-decision for
Track A — whether floating-point fields may appear in a signed payload at all.
The current envelope signs four (`Confidence.value`, `Confidence.alpha`,
`Validity.issued_at`, `Validity.expires_at`); the recommendation is scaled
integers, which would make the shared core a v1 format with existing entries
verifying under a v0 legacy tag.

D2 remains on the critical path and is cheap to decide. D1 is legal. D5 can
wait for Wave 3.

---

## 9. Claims register (Trutina)

Per Trutina admissibility rule 1, every quantitative claim in this document is
labeled. No claim here is backed by an EvidenceRecord; the right-hand column
names what would be needed to upgrade it.

| Claim | Label | To upgrade to `measured` |
|---|---|---|
| 4 chain implementations, 377/258/206/72 lines | measured (line count, direct inspection 2026-08-23) | already a direct observation; record not required |
| EPHEMERIS A5 ≥14 days on 500 mAh | requirement (benchmark assertion) | n/a — it is a contract |
| 500 mAh → 1.85 Wh → 5.5 mW average budget | target (derived from a BOM target) | measured cell capacity + a real duty-cycle model |
| CSAC ≈120 mW continuous | target (vendor datasheet class) | bench measurement of the selected part |
| Display 50,000 cd/m² peak | target (sketch-only blueprint) | supplier quote or measured panel |
| All other BOM values in §6.3 | target | DVT build + measurement |
| Caduceus 20 weeks / 3.25 FTE | target (planning estimate) | actual burn against M0–M8 |
| Caduceus ~330 tests | target (planning estimate) | the test suite existing |
| Portfolio 6–8 FTE | target (additive estimate) | bottom-up staffing model |
| Orin NX ≤200 W peak | requirement (`CADUCEUS-005 §1.2`) | n/a |
| Proteus CPU-only mandate | requirement (benchmark §2) | n/a |
| aletheia-dac 7/7 acceptance tests | measured (independently re-run 2026-08-23, this session) | — |
| PHRONESIS 51/51 tests | measured (repo-asserted, CI-backed; not re-run here) | independent re-run |

**Rule 3 note:** no performance claim in this document is a deployment claim, so
the three-axis check does not bind. It will bind the moment Proteus F0 or
Caduceus WCET numbers are published — both must carry quality, cost, and
conditions together, with a hardware fingerprint.

---

## 10. Definition of done for Wave 1

1. One verifier validates a chain produced by aletheia-dac, the PHRONESIS
   Aletheia chain, and Proteus Loop B.
2. Conformance test vectors exist and are signed, and a second implementation in
   another language reproduces them byte-for-byte.
3. All pre-existing signed ledger entries still verify, unmodified and
   re-signed by nothing.
4. Every repository's existing test suite still passes at its current count.
5. Proteus carries no `stub_validation` flag on F0 results.
6. Caduceus CI is green on an empty crate workspace.
7. No benchmark assertion in any repository has been edited. Any pressure to do
   so is recorded as a back-edge candidate with its delta justification, per
   ZCS-6.

---

*Prepared under ZCS-6 ordering discipline. This document plans work; it does not
authorize a phase, commit a ledger entry, or upgrade any epistemic marker.*
