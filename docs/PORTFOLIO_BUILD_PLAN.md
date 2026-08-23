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
The protocol is now specified in §7.6 — author signature plus 2-of-3
independent, three roles, seven people portfolio-wide — so this is a bounded
recruitment task rather than an open design question.

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
- **Radiation path:** resolved — see D5 below.
- Facility access: proton and heavy-ion beam time, thermal-vacuum cycling, and
  vibration to NASA-STD-7003A. **Beam time is booked months ahead and is the
  schedule driver for v1.0, not the engineering.** [PLAUSIBLE — general
  characteristic of accelerator facility scheduling; specific lead times not
  confirmed with any named facility]

#### D5 — radiation path. RESOLVED: two domains, and HF-10 already requires it.

**The question was a false binary.** "Class B parts *or* mitigated COTS" treats
the Phronesis Core as one compute domain that must be classified one way. HF-10
— a **gating** floor, not scoring — already forbids that. Verbatim:

> All decisions in the safety-critical loop ... execute on a formally verified
> deterministic kernel with worst-case execution time bounded and proven,
> **independent of any ML inference subsystem**. The kernel runs on
> **hardware-isolated compute** with bus-level enforcement: the ML subsystem
> **CANNOT bypass the kernel at the bus level, not by policy**.

Two hardware-isolated compute domains are therefore mandatory regardless of
radiation [VERIFIED — `vbx_isps_bench_v1_1.json`, HF-10, scope `substrate`,
gating]. The v1.0 roadmap already anticipates this shape — "a dedicated MCU
running the kernel + bus, with the AI compute on a separate AP processor
connected via a controlled message bus." The radiation decision simply follows
the split that HF-10 compels.

**Decision: classify by domain, not by module.**

| Domain | Contents | Radiation posture |
|---|---|---|
| **Safety** | Mercury kernel, MVCI gate, safety bus, watchdog, Aletheia signing | **Rad-hard / NASA Class B.** Small, deterministic, low compute — Class B is both feasible and affordable here. |
| **Advisory** | Civium 7B inference | **Mitigated COTS.** No alternative exists. |

**Why the advisory domain has no Class B option.** Rad-hard flight processors
in the RAD750 / RAD5545 / GR740 class deliver on the order of hundreds of MIPS
to a few GOPS, against a 7B Q4 model needing roughly 4 GB of resident weights
and tens of GFLOPS for usable latency. Rad-hard memory is not sold in the tens
of gigabytes. **There is no NASA Class B part that runs Mistral-7B**, so
"Class B preferred" was never an available option for Civium.
[PLAUSIBLE — part-class performance from training knowledge, not from verified
datasheets; this session has no vendor-datasheet access. Check 9 requires
confirming against manufacturer datasheets before this reaches a partner
document. The *conclusion* is robust to an order of magnitude either way.]

**Why COTS upsets are architecturally safe.** HF-10 requires the kernel to work
independent of the ML subsystem, so an advisory-domain SEU that forces a reboot
degrades the system to deterministic-floors-only — a defined state, not a
failure. **That state is already under test**: `substrate/requirements-llm.txt`
records that with the LLM extra absent,
`test_hard_safety_floor_blocks_llm_on_hypoxia`,
`test_hard_safety_floor_blocks_llm_on_multi_fault`, and
`test_physical_validity_blocks_llm` all pass, confirmed by direct run. The
radiation degradation mode is the LLM-absent mode, and it is verified today.

**The real cost is HF-12, and it is scoring, not gating.** HF-12 requires ≥70%
autonomous resolution on AUTONOMOUS_ELIGIBLE events. Advisory-domain downtime
pushes those events to safe-passive fallback, so:

> **A_min = 0.70 / R_up**

where `R_up` is the measured autonomous-resolution ratio with the LLM
available. At `R_up` = 0.85 the advisory domain may be unavailable ~18% of the
time; at 0.95, ~26%. Two consequences: the availability requirement is
**loose**, which further supports COTS; and if `R_up` ≤ 0.70 no availability
saves it, so `R_up` must be measured before any radiation budget is
meaningful. [PLAUSIBLE — the relation is derived; the `R_up` values are
illustrative assumptions, not measurements. Measuring `R_up` is a v0.3
calibration-audit deliverable and gates this whole calculation.]

**Non-negotiable mitigation: single-event latch-up protection.** SEL is the
destructive failure mode — one heavy ion can take the part permanently. Current
limiting with fast detect-and-power-cycle is mandatory on the advisory domain.
ECC covers single-bit DRAM upsets; multi-bit and SEFI take the reboot path,
which the architecture already tolerates. For a Mars-class profile behind modest
shielding, **SEE dominates TID** — unlike LEO/GEO or an outer-planet mission —
so the design driver is upset and latch-up rate, not dose accumulation.
[PLAUSIBLE — qualitative environment reasoning; no mission-specific analysis
run. See the unknowns below.]

**A power finding that falls out of this.** A 200 W-class advisory domain cannot
run continuously in a PLSS budget: 200 W × 8 h = 1.6 kWh, against an xEMU-class
suit battery on the order of 0.8–1.2 kWh — the AI domain alone would exceed the
entire historical suit energy budget. [PLAUSIBLE — Fermi estimate, Check 2;
battery figures are order-of-magnitude from training knowledge and need
datasheet confirmation.] **The advisory domain must be event-driven, powered
only for nuanced-band decisions.** This is fortunate rather than merely
constraining: a powered-down part accumulates no SEE, so the duty cycle that
the thermal and energy budget forces is also the cheapest radiation mitigation
available.

**Named unknowns — none of these are optional, and none are scoped today:**

1. A **mission-specific radiation environment analysis** (OLTARIS / CREME96 /
   SPENVIS class) producing TID and LET spectra for the actual shielding
   configuration. Nothing downstream is quantifiable without it.
2. **Beam-test-measured SEU, SEFI, and SEL cross-sections for the selected
   part.** Vendor figures are claims to verify, not facts (Check 9).
3. **`R_up` measured** on the v0.3 calibration audit, which sets `A_min`.

**TRL honesty (Check 5).** This architecture is TRL 2–3 — analysis only,
however detailed. The v1.0 campaign (proton and heavy-ion beam, thermal
vacuum, vibration to NASA-STD-7003A) is what moves it to TRL 5–6 in a relevant
environment. Do not describe it as flight-credible before that campaign
produces data, in capture documents above all.

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
| Display | 1.4″ AMOLED, 466×466, **~3,000 cd/m² peak** (revised, D3) | target |
| Display stack | Total reflectance ≤1% — AR + circular polarizer (added, D3) | target |
| Ambient sensor | Lux + IR cut, 1 lx – 100 klx | target |
| Mainboard | 4-layer FR4: MCU + SE + Flash + 9-DOF IMU + GNSS (**no CSAC**, D2) | target |
| Antenna | Ceramic patch, L1/L5 | target |
| Battery | Li-ion 500 mAh, custom L-shape | target |
| Caseback | Grade-5 titanium, IP68 / 100 m | target |
| Envelope | 44.0 × 13.5 × 52.0 mm, 78 g, −20…+60 °C, MIL-STD-810H | target |

#### D2 — CSAC and the A5/A6 relationship. RESOLVED: commercial variant only.

**Correction to an earlier reading in this document.** A prior revision framed
A5 and A6 as mutually exclusive and raised the possibility of a v1.3 benchmark
back-edge. That was wrong, and reading the frozen assertion text resolves it.
No back-edge is warranted and none should be prepared.

The frozen spec already anticipates two variants. A6, verbatim:

> Without GNSS, using IMU + last-known-state propagation, position drift ≤ **10
> m** over 24 hours of stationary operation. SPECULATIVE pending hardware
> simulation; **commercial variant may relax to ≤ 100 m, Pro variant with
> chip-scale atomic clock (CSAC) holds 10 m.**

And §6 Out of Scope (v1.0), verbatim: *"ITAR/EAR posture. **Commercial variant
only at v1.0.**"*

So the blueprint's "(Pro)" annotation is **consistent with the benchmark, not in
conflict with it** [VERIFIED — direct comparison of blueprint and
`BENCHMARK_v1.0.md` §A6, §6], and the CSAC-bearing variant is already outside
v1.0 scope by the benchmark's own words.

**Decision: the v1.0 BOM carries no CSAC.** Build the commercial variant. It
targets A5 (≥14 days) and A6 at ≤100 m, and those two do not conflict. The
arithmetic below stands but describes a device the benchmark never asks anyone
to build:

- A5: ≥14 days on 500 mAh nominal. `requirement` (scoring assertion, and
  self-labeled in the spec as "a market-positioning threshold (Garmin Fenix
  class), not a derived capability threshold").
- 500 mAh × 3.7 V = 1.85 Wh = 6660 J over 1.209 × 10⁶ s → **≈5.5 mW
  whole-system average**. `target` (derived from a BOM target).
- A CSAC in the Microchip SA.45s class draws on the order of 120 mW continuous,
  roughly 22× that budget. `target` (vendor datasheet class, no EvidenceRecord).

Three consequences follow, and all three are wins:

1. **No benchmark pressure.** Nothing is falsified, nothing is softened.
2. **Export exposure leaves the near-term build.** A CSAC is the part most
   likely to carry ITAR/EAR exposure, and §6 already scopes v1.0 to the
   commercial variant. This narrows §7.2 for EPHEMERIS specifically.
3. **The most expensive line leaves the BOM.** [PLAUSIBLE — no quote obtained;
   asserted from the part class, not from a supplier]

**Residual question, deferred with the Pro variant and not on the critical
path.** A6 specifies *stationary* operation. For a device that is stationary and
can detect that it is stationary, position is held by not moving, not by
inertial propagation — so the mechanism by which a CSAC improves the bound from
100 m to 10 m is not stated in the spec, and A6 marks itself SPECULATIVE
pending hardware simulation. **Write that mechanism down before any Pro-variant
spend.** If it turns out a CSAC does not deliver 10 m for a stationary device,
that is an A6 design question for a future benchmark cycle, and it should be
surfaced as a back-edge candidate rather than absorbed silently.

#### D3 — display luminance. RESOLVED: the blueprint has a units error.

**The blueprint transcribed an ambient-illuminance requirement into a display-
emission spec.** [VERIFIED — direct comparison of the two texts]

A3's audit protocol, verbatim: *"Label visible at **50,000 lux** simulated
sunlight (rendered luminance test)."* The blueprint's specification panel reads
**"50,000 cd/m² peak"**. Lux is incident illuminance; cd/m² is emitted
luminance. They are different quantities, and the benchmark asks for the first.

Nothing needs 50,000 cd/m² of emission. What A3 requires is a **WCAG AA
contrast ratio ≥ 4.5:1 sustained across a 1000-frame sweep at 50,000 lux
ambient** — and it is audited on rendered frames, so it does not gate the
panel's absolute peak luminance at all. The panel spec is a product decision,
not a benchmark-gated one.

**What actually sets legibility is stack reflectance, not peak emission.**
Modelling reflected ambient as Lambertian veiling glare, `L_veil ≈ ρ·E/π` at
E = 50,000 lux:

| Stack reflectance ρ | Veiling glare | Peak luminance needed for 4.5:1 |
|---|---|---|
| 4% (bare sapphire, no AR) | ≈ 637 cd/m² | ≈ 2,700 cd/m² |
| 2% (basic AR) | ≈ 318 cd/m² | ≈ 1,350 cd/m² |
| 0.5% (AR + circular polarizer) | ≈ 80 cd/m² | ≈ 340 cd/m² |

[PLAUSIBLE — first-principles derivation, not measured. Assumes Lambertian
reflection, AMOLED true black, and reuse of the WCAG contrast form with its
0.05 flare term standing in for the ambient floor. A rendered A3 audit or a
physical sunlight measurement would upgrade it.]

**Decision:** revise the BOM to a **procurable ~3,000 cd/m² peak-class panel**,
which clears the requirement with wide margin even against bare sapphire, and
**promote total stack reflectance to a first-class BOM line with a ≤1% target**
(AR coating plus circular polarizer). Reflectance is roughly an 8× lever on
required emission across the table above; peak nits alone is the expensive way
to buy the same legibility.

Two further benefits: a 3,000-nit-class panel is available from multiple
wearable suppliers rather than requiring an unidentified microLED source, and
it draws materially less than a hypothetical 50,000-nit panel, which relieves
the A5 budget that §D2 leaves tight.

**No benchmark change. This is a blueprint correction**, and it should be
recorded as one — the drawing is marked SKETCH ONLY and revising it is not a
back-edge.

#### Residual A5 risk, unresolved by either decision

Even without a CSAC, ≈5.5 mW whole-system average for a 466×466 AMOLED at ≥1 Hz
refresh with a 50 Hz IMU is aggressive. A5 is scoring, not gating, and the spec
labels it a market-positioning threshold, so this is a stretch target honestly
declared rather than a defect. It should be tracked as a measured number at DVT,
not asserted before then.

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
- ~~CSAC export-control screening~~ — removed from v1.0 scope by D2; returns
  with the Pro variant.

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
the methodology itself names as its largest — now specified in §7.6, where the
distinction that matters is that **attestor keys are generated and held by the
attestors**, never issued or escrowed by Visionblox. A signature made with a key
the attested party controls attests to nothing.

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

### 7.6 Attestation protocol (D6) — RESOLVED as to design; names remain open

**What this section settles, and what it cannot.** D6 asked "who are the
independent attestors?" The *who* is the principal investigator's to fill and
nobody else's — proposing named individuals here would be fabrication, and
putting real people forward without their consent is not a decision an assistant
gets to make. What is settled below is everything else: the threat model, the
scheme, what an attestor actually signs, who is eligible, how failure is
handled, and what it requires of the wire format. D6 therefore stops being an
open design question and becomes a bounded recruitment task against a written
specification — **three people, in three named roles.**

#### 7.6.1 Threat model — be precise about what OTS already covers

`EPHEMERIS-1/SECURITY.md` states the gap as key compromise: *"Chain entries are
signed by a single key controlled by the maintainer. A compromise of that key
allows producing fake-but-valid-looking new commits (though not retroactive
ones, given OTS anchoring)."*

Two distinct threats, and OpenTimestamps handles one of them well:

| Threat | Covered by OTS? | Covered by n-of-m? |
|---|---|---|
| Retroactive forgery of an earlier commit | **Yes** — Bitcoin anchoring fixes the hash in time | yes |
| Forged *new* commit after key theft | no — a stolen key signs a valid-looking entry | **yes** |
| Benchmark shaped by a privately-held solution | no — OTS timestamps an artifact, it does not witness a process | **partially** |

The third row is the one worth being careful about. OTS proves a benchmark hash
existed at time T, so a solution *published* later is provably later — ZCS-6's
ordering claim survives on timestamps alone against that case. What a timestamp
cannot see is an author privately iterating benchmark and solution together
before T. Only a human who reviewed the artifact at freeze time and declares no
knowledge of a candidate solution addresses that residual. **Do not oversell
this**: attestation reduces that risk, it does not eliminate it.

#### 7.6.2 The scheme

**Author signature required and separate, plus 2-of-3 independent attestors.**
The author's signature never counts toward the threshold — otherwise "2-of-3"
degrades to one independent signer.

Escalate to **3-of-5** for any benchmark version that backs a federal
deliverable or an IP filing. Everything else stays at 2-of-3.

The binding constraint here is recruitment, not cryptography —
`EPHEMERIS-1/GOVERNANCE.md` already flags that this *"requires identifying
willing attestors"* and calls the effort substantial. 2-of-3 is the smallest
scheme that materially beats a single signer and still tolerates one attestor
being unavailable at commit time. Setting it higher buys marginal assurance and
guarantees the ceremony never runs.

#### 7.6.3 What an attestor signs

Not "this benchmark is good" — that is an unfalsifiable opinion and a burden no
volunteer should carry. Four clauses, three of them mechanically checkable:

1. "I received the bundle with manifest SHA-256 `<hash>` on `<date>`."
2. "I independently recomputed the manifest hash from the bundle contents and it
   matched." *(the bundles already ship `baselines/verify_bundle.py`; this is a
   command, not an analysis)*
3. "I reviewed the assertions and the sealed-pool construction and found no
   evidence of contamination or of a threshold fitted to a known result."
4. "I have no knowledge of a candidate solution to this benchmark, and no
   financial interest in Visionblox LLC or Zuup Innovation Lab."

Clause 4 is what buys the third row of §7.6.1. Clause 3 is the only judgment
call, and it is scoped narrowly enough to be answerable.

#### 7.6.4 Independence criteria

Ineligible: employees or contractors of Visionblox LLC or Zuup Innovation Lab;
anyone holding a financial interest; anyone who contributed to the benchmark or
to a candidate solution; and — flagged deliberately — **the principal
investigator's academic supervisor or thesis committee**, who have a structural
interest in the work succeeding. That last exclusion will be inconvenient and it
is the one most worth keeping.

#### 7.6.5 The three roles to recruit

One person per role gives exactly the 2-of-3 quorum.

| Role | What they check | Domain burden |
|---|---|---|
| **Process attestor** | Recomputes hashes, verifies signatures, confirms chain linkage. Clauses 1–2. | lowest — recruit first |
| **Methodology attestor** | Falsification-first design, Goodhart resistance, sealed-pool fairness. Clause 3. | domain-independent; **one person can serve all five repositories** |
| **Domain attestor** | Whether the assertions are well-posed in the field. Clause 3. | highest, and **per-repository** |

The domain attestor is the only role that does not generalize: planetary and
time-scale expertise for EPHEMERIS, conformal prediction or test-time adaptation
for Proteus, DTN and space communications for Caduceus, safety-critical or
life-support systems for PHRONESIS. Budget five domain attestors across the
portfolio, one process attestor, and one methodology attestor — **seven people
total, not fifteen.**

#### 7.6.6 Recruitment channels

Categories, deliberately not individuals:

- **Authors already cited in the papers.** EPHEMERIS cites 35 references and
  PHRONESIS 45, many by working researchers in exactly the domains above.
  Contacting a cited author is ordinary academic courtesy and the warmest
  channel available. [PLAUSIBLE — a normal practice; no outreach attempted]
- **The reviewer pool of the target venues** the papers are already aimed at.
- **The reproducible-builds and OpenTimestamps communities**, which are the
  natural home for the process-attestor role.
- **SNHU faculty outside the PI's committee**, subject to §7.6.4.
- **SOSSEC / NSTXL consortium technical members**, already in the capture
  posture.

#### 7.6.7 Keys, failure modes, and history

**Keys.** Each attestor generates and holds their own Ed25519 key and publishes
its fingerprint. Attestor keys must never be issued, escrowed, or rotated by
Visionblox — an attestation signed with a key the attested party controls
attests to nothing. Attestor public keys live in a signed roster; roster changes
are themselves chain entries.

**Failure modes, all specified in advance:**

| Condition | Resolution |
|---|---|
| One attestor unavailable | 2-of-3 absorbs it; ceremony proceeds |
| Attestor key lost | Roster-update entry; prior attestations stand |
| Attestor withdraws consent | Prior attestations are historical facts and stand; removed from future rosters |
| **Threshold not reached** | **The commit does not happen.** |

That last row is the one that matters. The failure mode is an uncommitted
benchmark, never a benchmark committed with one signature and a footnote
explaining why. A ceremony with a documented bypass is not a ceremony.

**Existing single-signed history is not rewritten.** PHRONESIS LEDGER #0001–
#0005 and Proteus #0004 stay exactly as they are — chains are append-only and
that rule outranks the desire for a tidy roster. Attestors may instead sign a
**new, forward-only corroboration entry**: "I verified the chain from genesis to
entry #N on date D." That records independent review as a fact about a
verification performed later, without pretending it happened at the time.

#### 7.6.8 Scope — what needs attestation

**Benchmark freezes and benchmark version re-commits only.** Not routine
solution commits, not documentation changes, not phase-transition records. The
ceremony exists to protect the artifacts ZCS-6's credibility rests on, and
attestor goodwill is a finite resource — spend it where the methodology needs
it.

#### 7.6.9 Dependency — this changes what Track A must build

**D6 has a hard dependency on D4.** A chain-entry schema that holds one
signature cannot carry an n-of-m attestation set, and discovering that after the
v1 format ships forces a v2 for purely structural reasons.

**The shared provenance core must model an entry's signatures as a set from the
start** — author signature distinguished from attestor signatures, threshold
policy recorded in the entry, attestor key fingerprints resolvable against a
roster. Building it now costs very little; retrofitting it costs a format
version. This is recorded in `docs/PROMPT_shared_provenance_core.md` as a
required schema property.

## 8. Decisions required before Wave 2

| # | Decision | Owner | Blocks |
|---|---|---|---|
| D1 | Does Caduceus M0 block M1? (§7.1) | PI + practitioner | all Caduceus build |
| D2 | ~~Is EPHEMERIS CSAC a separate Pro SKU?~~ **DECIDED 2026-08-23: yes — and the Pro variant is out of v1.0 scope per benchmark §6. No CSAC in the v1.0 BOM** (§6.3) | PI — closed | — |
| D3 | ~~Revise the display target, or seek a microLED supplier?~~ **DECIDED 2026-08-23: neither — the blueprint had a lux→cd/m² units error. Revise to ~3,000 cd/m² and add a ≤1% reflectance line** (§6.3) | PI — closed | — |
| D4 | ~~Canonical encoding for the shared core~~ **DECIDED 2026-08-23: deterministic CBOR, RFC 8949 §4.2.1** (§1.2) | PI — closed | — |
| D5 | ~~PHRONESIS radiation path: Class B or mitigated COTS?~~ **DECIDED 2026-08-23: both — rad-hard safety domain, mitigated COTS advisory domain. HF-10 already mandates the split** (§6.2) | PI — closed | — |
| D6 | ~~Who are the independent attestors?~~ **DECIDED 2026-08-23: protocol settled — author + 2-of-3 independent, three named roles, seven people portfolio-wide. Names remain the PI's to fill** (§7.6) | PI — design closed, recruitment open | benchmark re-commits |

**D4 is closed, including its sub-decision:** deterministic CBOR per RFC 8949
§4.2.1, and **no floating-point values in the signed payload**. Confidence and
alpha become parts-per-million `uint32`; validity timestamps become `uint64`
microseconds since the Unix epoch (UTC). Rounding is directional and
conservative — coverage floors, alpha ceils, the validity window narrows from
both ends — so quantization can never inflate a guarantee. This makes the shared
core a **v1 format**, with existing float-bearing entries verifying under a `v0`
legacy tag and never re-signed. Bound in
`docs/PROMPT_shared_provenance_core.md`.

Two consequences worth tracking. Monotone propagation becomes *exact* — integer
`min`/`max`/intersection carry none of the float-comparison edge cases, so
T3/T4/T6 tighten rather than weaken. And the EPHEMERIS peer must convert from
its internal J2000/TT representation at the envelope boundary, a conversion that
crosses the leap-second table and is therefore a `DC-6`-class hazard by
construction (§6.3); the work order flags it at the point of definition.

**D2 and D3 are closed** (§6.3). Both resolved by reading the frozen assertion
text rather than by revising it: A6 already authorizes the commercial/Pro
variant split and §6 scopes v1.0 to the commercial variant, and A3's "50,000
lux" is an ambient-illuminance requirement that the blueprint transcribed as
display emission. No benchmark file is touched by either.

**D6 is closed as to design** (§7.6) and reduced to recruitment: three roles,
seven people across the portfolio, against a written attestation statement. It
also imposes a schema requirement on Track A — an entry's signatures must be
modelled as a set from the start, or adding attestation later forces a v2 format
(§7.6.9).

**D5 is closed** (§6.2). It resolved the same way D2 and D3 did — by reading a
frozen assertion rather than revising one. HF-10 is gating and already requires
the ML subsystem to be hardware-isolated from the kernel, so two radiation
domains were never optional and the "Class B or COTS" framing was a false
binary. It leaves three named unknowns (environment analysis, beam-measured
cross-sections, and a measured `R_up`), none currently scoped.

**D1 is the only decision still open**, and it is legal rather than technical.
Recruitment under D6 should start immediately: it is the longest-lead item that
costs nothing to begin.

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
| CSAC ≈120 mW continuous | target (vendor datasheet class) | moot for v1.0 — CSAC removed by D2 |
| ~~Display 50,000 cd/m² peak~~ | **withdrawn — units error (lux vs cd/m²), D3** | — |
| Display ~3,000 cd/m² peak, stack reflectance ≤1% | target (revised BOM) | supplier quote or measured panel |
| Peak luminance needed for A3 4.5:1 at 50 klx (2,700 / 1,350 / 340 cd/m² by reflectance) | target (first-principles derivation) | rendered A3 audit or physical sunlight measurement |
| All other BOM values in §6.3 | target | DVT build + measurement |
| Caduceus 20 weeks / 3.25 FTE | target (planning estimate) | actual burn against M0–M8 |
| Caduceus ~330 tests | target (planning estimate) | the test suite existing |
| Portfolio 6–8 FTE | target (additive estimate) | bottom-up staffing model |
| Advisory-domain availability `A_min = 0.70 / R_up` | requirement (derived from HF-12, gating threshold) | measure `R_up` in the v0.3 calibration audit |
| Rad-hard parts cannot host a 7B model | target (part-class reasoning, no datasheets accessed) | vendor datasheet confirmation |
| 200 W × 8 h = 1.6 kWh vs ~0.8–1.2 kWh suit battery | target (Fermi estimate, Check 2) | PLSS power budget from the shell partner |
| PHRONESIS radiation architecture at TRL 2–3 | measured (analysis-only evidence, per Check 5) | v1.0 beam/TVAC/vibration campaign → TRL 5–6 |
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
