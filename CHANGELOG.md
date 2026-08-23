# Changelog

All notable changes to Aletheia — Drift-Aware Claim (DAC) Substrate are
documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

House convention: load-bearing claims carry an epistemic marker —
**VERIFIED** (built and tested), **PLAUSIBLE** (designed, not yet built), or
**SPECULATIVE** (research-grade, needs validation). See
[`docs/EPISTEMIC_FRAMEWORK.md`](docs/EPISTEMIC_FRAMEWORK.md).

---

## [Unreleased]

### Fixed
- **Root-directory file restoration.** A batch upload wrote nine files to the
  repository root under names that did not match their contents — `CHANGELOG.md`
  held the one-line body of `src/aletheia/__init__.py`, `__init__.py` held
  `IEEEtran.cls`, `cli.py` held `IEEEtran.bst`, `references.bib` held the
  compiled PDF, `service.py` held the BibTeX bibliography, `aletheia.tex` held
  the n8n workflow JSON, `n8n_workflow.json` held the specification markdown,
  `IEEEtran.cls` held the LaTeX source, and `download` held `service.py`. Each
  was byte-identical to a correctly-named file already present under `src/`,
  `paper/`, `docs/`, `examples/`, or `tests/`, so no content was lost. The
  mislabeled root copies are removed and this changelog is restored. VERIFIED —
  every removed file was confirmed byte-identical to its canonical counterpart
  before deletion, and no document in the repository referenced a root-level
  copy.
- **`docs/EPISTEMIC_FRAMEWORK.md`** — the epistemic-framework document was
  present at the root as `Specification.md`, shadowing the real specification
  name and leaving the `README.md` link to `docs/EPISTEMIC_FRAMEWORK.md`
  dangling. Moved to its documented path; the link now resolves.

### Added
- **Continuous integration** (`.github/workflows/tests.yml`) — runs the seven
  acceptance tests on every push and pull request. The suite was passing but
  nothing enforced it.

---

## [0.1.0] — 2026-05-26 — Reference substrate

First reference implementation of the DAC envelope and its propagation runtime.
All items VERIFIED under `tests/test_acceptance.py` (7/7).

### Added
- **DAC envelope** (`src/aletheia/dac.py`) — Ed25519 producer attestation,
  SHA-256 hash chain, and a provenance DAG over parent claims.
- **Monotone propagation runtime** (`Substrate.issue`) — the load-bearing
  invariant. A derived claim takes `min` confidence, the `intersection` of
  validity windows, and `max` classification over itself and its parents;
  `requires_hitl` is the disjunction and is forced true for `REGULATED`; status
  becomes `STALE` if any parent is not `VALID`. Covered by T3, T4, and T6.
- **Calibrated confidence** — `SplitConformal` and `AdaptiveConformal` (ACI),
  giving a conformal coverage level rather than a softmax score.
- **Drift monitoring** — `DriftMonitor` with Page-Hinkley and Kolmogorov-Smirnov
  detectors, plus `ClaimStore.cascade_stale` for graph-scoped invalidation that
  marks only genuine dependents.
- **Persistence** — `ClaimStore` on SQLite with an append-only hash chain.
  Status transitions live in the `status` column so a stored claim's signed
  `json` is never mutated in place.
- **OSCAL export** (`src/aletheia/oscal.py`) — emits assessment-results shaped
  output for the Civium compliance bridge.
- **Stdlib CLI** (`src/aletheia/cli.py`) — dependency-free command surface, the
  primary n8n integration path via the Execute Command node.
- **Optional HTTP service** (`src/aletheia/service.py`) — FastAPI wrapper behind
  the `[service]` extra, for the n8n HTTP Request node.
- **Acceptance suite** (`tests/test_acceptance.py`) — seven falsifiable tests:
  T1 signature tampering, T2 chain tampering, T3 weakest-link confidence,
  T4 REGULATED/HITL propagation, T5 split-conformal coverage, T6 drift cascade
  scoping, T7 ACI coverage under drift. Seeds are fixed for reproducibility.
- **Documentation** — `docs/Specification.md` (first-principles derivation and
  the authoritative open-gap list), `paper/aletheia.tex` and `paper/aletheia.pdf`
  (IEEE conference paper with closure proofs), `ROADMAP.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, `CLAUDE.md`.
- **Example integration** — `examples/n8n_workflow.json`, an importable pipeline.

### Changed
- Restructured into an installable `src/` package layout with `pyproject.toml`
  (setuptools backend, `aletheia` console script, `pytest` configured with
  `pythonpath = ["src"]`).

### Known gaps
Carried forward, not solved. Documented in `docs/Specification.md` §6 and the
paper's Limitations section:

1. `min`-combination under-counts genuinely independent corroborating evidence.
2. Drift in an *unmonitored* variable is invisible; monitors are not auto-selected.
3. A DAC proves byte-provenance, not semantic meaning.
4. Cross-organization trust root and key distribution are unbuilt.
5. Conformal coverage is marginal and long-run, not conditional, so rare
   subpopulations can be missed.
6. STALE-but-acted-on has defined provenance and undefined legal liability.
