# CLAUDE.md — Aletheia / Drift-Aware Claim (DAC) Substrate

This file orients Claude Code (and any contributor) on every session. Read it
before changing code. It encodes *why* the design is the way it is, so changes
don't silently break the guarantees that justify the project.

## What this is
A **road**, not an app: the interface contract between layers of any AI/data
system. Every artifact a layer produces (sensor reading, embedding, map tile,
policy decision, inference) is wrapped in a **Drift-Aware Claim (DAC)** — a
signed, hash-chained envelope carrying:
- **provenance** (a DAG of parent DACs + an Ed25519 producer signature),
- **calibrated confidence** (conformal coverage level, not a softmax),
- a **validity window** that self-invalidates when a monitored input drifts,
- a **data classification** (PUBLIC/INTERNAL/CONFIDENTIAL/REGULATED) + HITL flag.

It closes the two cross-cutting gaps found across all five next-gen substrates:
provenance+confidence don't survive the stack (#2), and nothing knows when its
knowledge expired under drift (#1).

## The invariant you must not break: MONOTONE PROPAGATION
When a DAC is derived from parents, the runtime (`Substrate.issue`) enforces:
- `confidence = min(self, parents)`        — only as strong as the weakest link
- `validity   = intersection(parents)`     — expires when any input does
- `classification = max(self, parents)`    — REGULATED taints downstream
- `requires_hitl = OR(...)`, forced True if REGULATED
- `status = STALE if any parent not VALID`

**If you change derivation, these must still hold.** They are covered by tests
T3, T4, T6. A change that weakens any of them is a regression even if tests are
edited to pass — do not edit the tests to accommodate a weaker guarantee.

## Repository map
```
src/aletheia/
  dac.py       core: Producer (Ed25519), Confidence/Validity/DAC, ClaimStore
               (SQLite + hash chain + provenance graph + cascade_stale),
               Substrate (monotone propagation), SplitConformal, AdaptiveConformal,
               DriftMonitor (Page-Hinkley + KS)
  provenance/  THE SHARED CORE — the zil-provenance v1 wire format, used by all
               five substrates. See docs/WIRE_FORMAT.md before changing anything
               in here; the format is specified, not defined by this code.
    cbor.py      deterministic CBOR, RFC 8949 4.2.1 (stdlib only)
    quantize.py  exact-rational reduction to scaled integers (stdlib only)
    codec.py     domain-separated signing / verification / record hashing
    envelope.py  the v1 DAC envelope + monotone propagation (exact, on ints)
    entry.py     the v1 chain entry (opaque attested payload)
    keystore.py  persistent Ed25519 keystore + trust root
    legacy.py    READ-ONLY verifiers for the five pre-v1 formats
    verifier.py  format detection + one verifier for every substrate
    verify.py    `python -m aletheia.provenance.verify` (no numpy/scipy needed)
    vectors.py   the conformance suite generator (TEST KEY only)
  oscal.py     export claim store -> OSCAL assessment-results (Civium bridge)
  cli.py       stdlib-only CLI (primary n8n integration via Execute Command)
  service.py   OPTIONAL FastAPI HTTP wrapper (needs [service] extra)
docs/WIRE_FORMAT.md            normative v1 spec; implementable without the Python
docs/zil-provenance-v1.cddl    machine-readable schema
docs/BACK_EDGE_CANDIDATES.md   defects found under frozen contracts (ZCS-6)
docs/PORTFOLIO_BUILD_PLAN.md   the parent plan; Track A is this work
tests/test_acceptance.py       the 7 falsifiable acceptance tests (T1-T7)
tests/vectors/                 committed, signed conformance vectors
examples/n8n_workflow.json     importable n8n pipeline
paper/aletheia.tex             IEEE conference paper (formal core)
```

## The shared core: rules that are NOT negotiable
The wire format is a specification with conformance vectors, not an
implementation detail. Before changing `src/aletheia/provenance/`:
- `docs/WIRE_FORMAT.md` governs. If the code and the spec disagree, the code is
  wrong.
- `tests/vectors/zil_provenance_v1.json` is committed. If a change moves those
  bytes, that is a **format change** and needs a version bump — regenerating the
  fixture to make the test pass is the failure mode this guards against.
- Vendored copies live in `PHRONESIS-1/substrate/src/aletheia/provenance/` and
  `Proteus/zil_provenance/`. Change the canonical source here, then re-vendor.
  Both repos carry a drift guard that fails if a copy diverges.
- No floats in a signed payload. No re-quantizing a value through a float —
  quantization is not idempotent that way and the value drifts downward.
- Chains are append-only across the whole portfolio. Legacy artifacts are
  verified under a v0 tag and are NEVER re-signed, migrated, or rewritten.

## Commands
```bash
pip install -e ".[dev]"        # install with test deps
pytest -q                      # run acceptance suite (expect 7 passed)
python tests/test_acceptance.py  # same tests, human-readable report
python -m aletheia.cli --help  # CLI surface used by n8n
# verify a chain from ANY of the five substrates (stdlib + cryptography only):
python -m aletheia.provenance.verify <artifact> [--pubkey KEY] [--json]
# optional HTTP service:
pip install -e ".[service]" && uvicorn aletheia.service:app --port 8088
```

## Conventions (house style — keep these)
- **Epistemic markers** in docs/comments: VERIFIED / PLAUSIBLE / SPECULATIVE.
- **Compliance-first:** REGULATED artifacts always carry a human-in-loop gate.
- **Zero-budget:** open-source only (numpy, scipy, cryptography, sqlite3, n8n,
  Ollama). The stdlib CLI must stay dependency-free so it runs anywhere.
- **Audit integrity:** never mutate a stored claim's signed `json` in place; the
  hash chain depends on it. Legitimate state changes (STALE) live in the `status`
  column only — `cascade_stale` already does this correctly; preserve that.
- **Determinism in tests:** seeds are fixed; keep reproducibility.

## Known open gaps (DO NOT pretend these are solved)
Documented in `paper/aletheia.tex` §Limitations and the spec §6:
1. `min`-combination under-counts genuinely independent corroborating evidence.
2. Drift in an *unmonitored* variable is invisible (no auto-selection of monitors).
3. DAC proves byte-provenance, not semantic meaning (Road-2 interpretability gap).
4. Cross-org trust root / key distribution is unbuilt (federated future work).
   NARROWED, not closed: `provenance/keystore.py` gives persistent keys and a
   *local* trust root, and a v1 envelope carries its producer's public key so it
   is self-verifiable. Cross-organization distribution, rotation and revocation
   remain unbuilt.
5. Conformal coverage is marginal/long-run, not conditional — can miss rare
   subpopulations.
6. STALE-but-acted-on has defined provenance, undefined legal liability.

If asked to "fix" one of these, treat it as real research: propose a design,
add a failing test that encodes the target property, then implement.

## Good first tasks for Claude Code
- ~~Persistent Ed25519 keystore for producers~~ — DONE, `provenance/keystore.py`.
- Postgres/Neo4j `ClaimStore` backend behind the same interface.
- OSCAL schema validation step in CI (`oscal.py` emits the shape; certify it).
- Monitor auto-suggestion (gap #2): rank stream statistics by drift sensitivity.
- Conditional-coverage diagnostics for the conformal layer (gap #5).

## Definition of done for any change
1. `pytest -q` passes without weakening T3/T4/T6 assertions. The 7 acceptance
   tests (T1-T7) must stay 7/7; the provenance suites must stay green and the
   committed conformance vectors must still reproduce byte-for-byte.
2. New behavior has a falsifiable test.
3. Monotone-propagation invariant preserved.
4. Epistemic markers + a note in the relevant open-gap list if the change
   narrows or widens a gap.
