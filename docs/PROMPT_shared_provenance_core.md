# Session prompt — `zil-provenance` shared core (Wave 1, Track A)

Copy everything below the line into a fresh Claude Code session scoped to
`khaaliswooden-max/aletheia-dac` (read access also needed to PHRONESIS-1,
Proteus, EPHEMERIS-1, Caduceus-1).

---

Build the shared provenance core for the Visionblox/Zuup five-substrate
portfolio. Work on branch `claude/zil-provenance-core`.

## Why this exists

There are currently **four independent Ed25519 hash-chain implementations**
across three repositories:

- `aletheia-dac/src/aletheia/dac.py` (377 lines)
- `PHRONESIS-1/substrate/src/aletheia/chain.py` (258 lines)
- `Proteus/zil_sign.py` (206 lines)
- `Proteus/loop_a/chain.py` (72 lines)

Two more are specified and unbuilt: EPHEMERIS assertion **A7** (signed update
path, deferred to firmware v0.3) and the Caduceus Rust crate
**`caduceus-attest`** (`CADUCEUS-005 §2.1`).

Every one of these repositories claims that provenance is *portable*. With six
divergent formats that claim is false. Caduceus must sign byte-identical tuples
from Rust; the EPHEMERIS peer must verify them from embedded C on a Cortex-M.
That is impossible without a canonical encoding fixed by specification.

Read `aletheia-dac/docs/PORTFOLIO_BUILD_PLAN.md` §1 and §4 Track A first — it
is the parent plan for this work.

## Start by reading, not writing

Before designing anything, read all four implementations above and produce a
**difference matrix**: field names, field ordering, canonicalization approach,
hash input construction, signature payload, chain-linkage field, and timestamp
handling. Show me that matrix and your proposed unified schema **before**
writing the implementation. If the four disagree in ways that cannot be
reconciled without breaking an existing signature, say so explicitly and stop
for a decision — do not paper over it.

## Deliverables

1. **A versioned wire-format specification** — `docs/WIRE_FORMAT.md` plus a
   machine-readable CDDL schema.

   **The encoding is decided: deterministic CBOR.** This is settled by the
   principal investigator — do not re-litigate it, do not survey alternatives,
   do not silently substitute. Caduceus has already independently selected
   `serde` + `ciborium` (`CADUCEUS-005 §3`), so CBOR keeps that plan intact.

   Bind explicitly to **RFC 8949 §4.2.1 core deterministic encoding**, and state
   each rule in the spec rather than citing the RFC and moving on:
   - definite-length encoding only — no indefinite-length items
   - shortest-form encoding for integers and for all major-type argument lengths
   - map keys sorted by bytewise lexicographic order of their *encoded* bytes
   - no duplicate map keys, on encode or decode
   - decoders reject non-deterministic input rather than accepting and
     re-canonicalizing it

   Must cover: the DAC envelope, the chain entry, canonical field ordering,
   version tagging, and unknown-field handling.

   **No floating-point values in the signed payload. Decided.** This is
   settled by the principal investigator alongside the encoding — do not
   re-litigate it and do not preserve a float because it is already there.

   The current Python envelope signs four floats: `Confidence.value`,
   `Confidence.alpha`, `Validity.issued_at`, and `Validity.expires_at` (the
   latter two are `time.time()` values). Deterministic CBOR requires the
   shortest float that round-trips the value, and Python, Rust, and embedded C
   would all have to agree bit-for-bit on that reduction. Many Cortex-M parts
   have a single-precision FPU or none at all, so the EPHEMERIS peer could not
   reliably reproduce an `f64` payload. Scaled integers remove the whole class
   of defect.

   Representation:

   | Field | Type | Scale | Rounding |
   |---|---|---|---|
   | `confidence.value` | `uint32` | parts-per-million; `1.0` = `1_000_000` | **floor** |
   | `confidence.alpha` | `uint32` | parts-per-million | **ceil** |
   | `validity.issued_at` | `uint64` | us since Unix epoch (UTC) | **ceil** |
   | `validity.expires_at` | `uint64` | us since Unix epoch (UTC) | **floor** |

   **The rounding directions are load-bearing, not stylistic.** Every one
   rounds in the direction that weakens the claim, so quantization can never
   inflate a guarantee:

   - coverage floors down — quantization never overstates confidence;
   - alpha ceils up — never understates the miscoverage rate;
   - the validity window narrows from both ends — never extends validity.

   State this rule in `docs/WIRE_FORMAT.md` and give it a test. It composes
   correctly with monotone propagation, and it makes that propagation *exact*:
   `min` / `max` / interval intersection on integers have none of the
   comparison edge cases the float versions carry. Confirm T3/T4/T6 still pass
   and note in the spec that they are now exact rather than approximate.

   **Epoch — resolve this conflict explicitly.** The envelope timestamp is
   **microseconds since the Unix epoch, UTC**. Provenance timestamps are
   wall-clock event times shared across all five substrates, so the envelope
   takes the universal convention. EPHEMERIS uses `uint64` microseconds since
   **J2000 in TT** internally; that is a domain-specific choice for its
   astronomical payload and it stays internal. The peer converts at the envelope
   boundary.

   **That conversion is not a fixed offset.** TT-to-UTC crosses the leap-second
   table, which is exactly the class of defect EPHEMERIS already found and drove
   back into its benchmark as `DC-6` (a constant `TAI-UTC = 37` assumption that
   silently corrupted pre-2017 epochs for every body). Do not reintroduce it.
   The conversion must use the IERS Bulletin C table the device already carries,
   and pre-1972 epochs must signal out-of-scope rather than compute silently,
   per assertion A1d. Call this hazard out in `docs/WIRE_FORMAT.md` where the
   epoch is defined, so the next implementer meets it before writing the
   conversion rather than after.

   Because what gets signed changes, this lands as the **v1 format**. Existing
   float-bearing entries verify under the `v0` legacy tag per the hard
   constraints below — never re-signed, never migrated. Document scale factors,
   rounding rules, range limits, and overflow behavior in
   `docs/WIRE_FORMAT.md`, and include conformance vectors that pin each rounding
   direction at a boundary value.

2. **A Python reference implementation** in `src/aletheia/provenance/`, with the
   four existing implementations refactored onto it behind adapters that
   preserve each repository's current public API. Do not change any repository's
   external call signatures in this pass.

3. **An n-of-m-ready signature model in the chain entry.** An entry's
   signatures must be a **set**, not a single field: the author signature
   distinguished from attestor signatures, the threshold policy in force
   recorded in the entry, and attestor key fingerprints resolvable against a
   signed roster. Roster changes are themselves chain entries.

   The portfolio has decided on multi-party attestation for benchmark commits
   (author signature plus 2-of-3 independent attestors; see
   `docs/PORTFOLIO_BUILD_PLAN.md` §7.6). Recruitment is still in progress, so
   **no attestation will be produced during this session** — but a v1 entry
   format that holds exactly one signature would force a v2 for purely
   structural reasons the moment the first attestor signs. Model the set now;
   leaving it with a single author signature and zero attestors is a valid
   instance of it.

4. **A conformance test-vector suite** — signed fixtures, committed, that any
   implementation in any language must reproduce byte-for-byte. Include
   deliberately adversarial vectors: field reordering, unknown fields, empty
   parent sets, maximum-length fields, non-ASCII, and near-miss signatures.
   These vectors are what Rust and embedded C will be validated against later.

5. **One verifier** that validates a chain from any of the five substrates and
   reports which format version each entry uses.

6. **A persistent Ed25519 keystore**, replacing aletheia-dac's per-process
   ephemeral keys. This is already item 1 of the aletheia-dac Phase 1 roadmap
   and is the reason the repo cannot currently back the other four.

## Hard constraints — violating any of these fails the task

- **Existing signed artifacts must continue to verify, unmodified.** Proteus
  `LEDGER_0004.json` and PHRONESIS `VBX_ISPS_LEDGER_0001`–`0005` are signed
  history. Verify them under a `v0` legacy format tag. **Never re-sign, migrate,
  or rewrite a historical entry.** Chains are append-only across this portfolio
  and that rule is not negotiable.
- **Do not edit any benchmark file.** Frozen and hash-committed:
  `PHRONESIS-1/benchmark/vbx_isps_bench_v1_1.json`,
  `Caduceus-1/docs/CADUCEUS-004.md`, `Proteus/proteus-bench-v1.0.2/`, and the
  EPHEMERIS `planet-time-bench-*.tar.gz` bundles. If the core cannot satisfy a
  benchmark assertion, that is a finding to report, never a reason to soften the
  benchmark. Same for the EPHEMERIS `.tar.gz` bundles generally — do not unpack,
  edit, or re-pack them; their manifest hashes are load-bearing.
- **Every repository's existing test suite must still pass at its current
  count.** aletheia-dac is 7/7; PHRONESIS is 51/51 (5 may skip without the LLM
  extra). Run them and report actual output — do not infer from a summary line.
- **Preserve aletheia-dac's monotone-propagation invariant.** Confidence =
  min(self, parents); validity = intersection; classification = max; HITL = OR,
  forced true if REGULATED; status = STALE if any parent is not VALID. Covered
  by T3/T4/T6. Do not weaken these, and do not edit the tests to accommodate a
  weaker guarantee.
- **Never mutate a stored claim's signed `json` in place.** State changes live
  in the `status` column only; `cascade_stale` already does this correctly.
- **No AI collaborator touches private key material,** and do not propose a
  workflow in which one does. Generate test keys for fixtures only, and mark
  them unmistakably as test keys.
- **Zero-budget rule:** open-source dependencies only. The stdlib CLI must stay
  dependency-free.

## Out of scope for this session

The Rust and embedded-C implementations. This session fixes the *specification
and the vectors*; Rust follows in Caduceus M2, embedded C in EPHEMERIS v0.3,
both validated against your vectors. Do not start them.

## House conventions

- **Epistemic markers** on every load-bearing claim: VERIFIED / PLAUSIBLE /
  SPECULATIVE. Do not remove or upgrade an existing marker without evidence.
- **Trutina labeling** on every quantitative claim: `requirement`, `measured`,
  or `target`. A measured claim cites a record, an n, and an uncertainty.
- Falsification-first: when you add behavior, add the test that would catch it
  being wrong, and prefer writing the failing test first.
- Docstrings state purpose, inputs, outputs, precondition, postcondition.
- Commit with clear messages; push to `claude/zil-provenance-core`. Do not open
  a pull request unless asked.

## Definition of done

1. One verifier validates a chain from aletheia-dac, the PHRONESIS Aletheia
   chain, and Proteus Loop B.
2. Conformance vectors exist, are signed, and are committed.
3. All pre-existing signed ledger entries verify, unmodified.
4. Every repository's test suite passes at its current count, with real output
   pasted.
5. No benchmark file is modified. Any pressure to modify one is written up as a
   back-edge candidate with delta justification, per ZCS-6.
6. `docs/WIRE_FORMAT.md` is complete enough that an engineer could implement it
   in Rust without reading the Python.
7. A chain entry carries its signatures as a set, and a vector exists for the
   author-only case (zero attestors) and for an author-plus-two-attestor case.

## First response

Do not write code in your first response. Read the four implementations, then
give me the difference matrix and your proposed unified schema, plus any
irreconcilable conflicts you found. I will approve the schema before you build.
