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
  oscal.py     export claim store -> OSCAL assessment-results (Civium bridge)
  cli.py       stdlib-only CLI (primary n8n integration via Execute Command)
  service.py   OPTIONAL FastAPI HTTP wrapper (needs [service] extra)
tests/test_acceptance.py   the 7 falsifiable acceptance tests (T1-T7)
examples/n8n_workflow.json importable n8n pipeline
paper/aletheia.tex         IEEE conference paper (formal core)
```

## Commands
```bash
pip install -e ".[dev]"        # install with test deps
pytest -q                      # run acceptance suite (expect 7 passed)
python tests/test_acceptance.py  # same tests, human-readable report
python -m aletheia.cli --help  # CLI surface used by n8n
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
5. Conformal coverage is marginal/long-run, not conditional — can miss rare
   subpopulations.
6. STALE-but-acted-on has defined provenance, undefined legal liability.

If asked to "fix" one of these, treat it as real research: propose a design,
add a failing test that encodes the target property, then implement.

## Good first tasks for Claude Code
- Persistent Ed25519 keystore for producers (replace per-process ephemeral keys).
- Postgres/Neo4j `ClaimStore` backend behind the same interface.
- OSCAL schema validation step in CI (`oscal.py` emits the shape; certify it).
- Monitor auto-suggestion (gap #2): rank stream statistics by drift sensitivity.
- Conditional-coverage diagnostics for the conformal layer (gap #5).

## Definition of done for any change
1. `pytest -q` passes (7/7) without weakening T3/T4/T6 assertions.
2. New behavior has a falsifiable test.
3. Monotone-propagation invariant preserved.
4. Epistemic markers + a note in the relevant open-gap list if the change
   narrows or widens a gap.
