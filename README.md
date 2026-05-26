<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

# Aletheia — Drift-Aware Claim (DAC) Substrate

**A portable epistemic substrate for non-stationary autonomous systems.**

[![tests](https://img.shields.io/badge/acceptance%20tests-7%2F7-brightgreen)](tests/test_acceptance.py)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![status](https://img.shields.io/badge/status-v0.1.0%20reference-orange)](CHANGELOG.md)

</div>

Every artifact a system layer produces — a sensor reading, an embedding, a map
tile, a policy decision, an inference — is wrapped in a signed, hash-chained
**Drift-Aware Claim** that carries its **provenance graph**, a **calibrated
confidence** (a conformal coverage level, not a softmax), a **data
classification**, and a **validity window that self-invalidates when a monitored
input drifts**. A derived claim can never silently drop the weakest confidence,
widest sensitivity, or shortest validity of its inputs.

> **The gap it closes.** Across the next generation of AI form factors two
> failure modes recur: (1) nothing knows when its own knowledge has expired under
> drift, and (2) provenance and calibrated confidence don't survive the stack.
> They're the same problem. Aletheia is one primitive for both.

---

## Table of contents
- [Why](#why)
- [Install](#install)
- [Quickstart (CLI)](#quickstart-cli)
- [The three mechanisms](#the-three-mechanisms)
- [Architecture](#architecture)
- [Integrations](#integrations)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Citing](#citing)
- [License](#license)

## Why
A system can act safely only on what it can (a) **trace**, (b) **bound the
confidence of**, and (c) **know is still valid**. Today those three properties
live in disconnected, hand-built places — an audit log here, a softmax there, a
time-to-live somewhere else — and none of them compose across layer boundaries.
Aletheia makes them a single, portable, composable envelope with a typed
propagation contract. See [`docs/Specification.md`](docs/Specification.md) for
the full first-principles derivation and [`paper/aletheia.pdf`](paper/) for the
formal treatment with closure proofs.

## Install
```bash
pip install -e ".[dev]"        # core + test dependencies
# optional HTTP service surface:
pip install -e ".[service]"
```
Core dependencies are open-source only: `numpy`, `scipy`, `cryptography`,
and the standard-library `sqlite3`. The CLI itself is dependency-free.

## Quickstart (CLI)
```bash
# issue a REGULATED sensor reading governed by drift monitor "stream_A"
ID=$(python -m aletheia.cli issue --db s.db --kind sensor_reading \
      --producer sensor.l0 --classification REGULATED --confidence 0.99 \
      --alpha 0.01 --monitor stream_A --payload "hr=88" \
      | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

# derive an embedding from it — confidence is pulled to the weakest link,
# and REGULATED + human-in-the-loop are inherited automatically
python -m aletheia.cli derive --db s.db --kind embedding --producer enc.l2 \
      --classification INTERNAL --confidence 0.92 --alpha 0.08 \
      --method split_conformal --parents $ID --payload "vec"

python -m aletheia.cli trip   --db s.db --monitor stream_A   # drift -> cascade STALE
python -m aletheia.cli verify --db s.db                      # audit-chain integrity
python -m aletheia.cli export-oscal --db s.db > results.json # OSCAL/Civium bridge
```

## The three mechanisms
All are established techniques; the novelty is their composition into a
cross-layer envelope with a propagation contract.

1. **Monotone propagation** — a derived claim inherits `min` confidence, `max`
   sensitivity, intersected validity, and OR-ed human-gate of its inputs, as a
   *typed precondition* of derivation. Confidence/provenance cannot be dropped.
2. **Split conformal + Adaptive Conformal Inference (ACI)** — confidence is a
   distribution-free coverage guarantee; ACI keeps that guarantee under drift.
3. **Page-Hinkley / Kolmogorov-Smirnov drift monitor** — on a shift, staleness
   cascades through the provenance graph to exactly the dependent claims.

## Architecture
```
 Layer 5 agency   ──issues DAC──┐
 Layer 4 mapping  ──issues DAC──┤   monotone
 Layer 2 encoding ──issues DAC──┤   propagation   ┌────────────┐
 Layer 0 sensing  ──issues DAC──┘  ───────────▶   │  Aletheia  │
                                                   │  runtime   │
       DriftMonitor(stream) ──trip──▶ cascade ───▶ │ + store    │
                                                   └─────┬──────┘
                                                         ▼
                                  SQLite claims + SHA-256 hash chain (audit)
                                                         │
                                              OSCAL export ▶ Civium / GRC tooling
```

## Integrations
- **n8n** — the stdlib CLI is invoked from an Execute Command node; see
  [`examples/n8n_workflow.json`](examples/n8n_workflow.json).
- **Civium / OSCAL** — `aletheia.oscal` renders the claim store as an OSCAL
  assessment-results document mapping DAC properties to NIST 800-53 controls.
- **HTTP** — optional FastAPI app in `aletheia.service` for the HTTP Request node.

## Repository layout
```
src/aletheia/   dac.py · oscal.py · cli.py · service.py
tests/          test_acceptance.py  (T1–T7, falsifiable)
examples/       n8n_workflow.json
paper/          aletheia.tex · references.bib · aletheia.pdf
docs/           Specification.md · EPISTEMIC_FRAMEWORK.md
CLAUDE.md       design contract + guardrails for Claude Code
```

## Documentation
| Doc | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Design contract, the invariant, open gaps, agent guardrails |
| [docs/Specification.md](docs/Specification.md) | First-principles spec + gap analysis |
| [docs/EPISTEMIC_FRAMEWORK.md](docs/EPISTEMIC_FRAMEWORK.md) | Confidence tiering + research method |
| [paper/aletheia.pdf](paper/) | IEEE paper: lattice semantics + closure proofs |
| [ROADMAP.md](ROADMAP.md) · [CHANGELOG.md](CHANGELOG.md) · [SECURITY.md](SECURITY.md) | Project process |

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule that matters: **do not weaken
the monotone-propagation invariant** (tests T3/T4/T6), and do not pretend a
documented open gap is solved.

## Citing
If you use this work, please cite it — see [CITATION.cff](CITATION.cff) and the
IEEE paper.

## License
Apache-2.0 — see [LICENSE](LICENSE). © 2026 A. Khaalis Wooden, Sr. / Zuup Innovation Lab.
