# Roadmap

Status legend: VERIFIED (built, tested) · PLAUSIBLE (designed, not yet built) ·
SPECULATIVE (research-grade, needs validation).

## v0.1.0 — Reference substrate (current) · VERIFIED
- DAC envelope: Ed25519 attestation, SHA-256 hash chain, provenance DAG.
- Monotone propagation runtime with lattice semantics + closure proofs.
- Split conformal + Adaptive Conformal Inference confidence.
- Page-Hinkley + KS drift monitor with graph cascade invalidation.
- SQLite store, stdlib CLI, optional FastAPI service, OSCAL export.
- 7/7 falsifiable acceptance tests; compiled IEEE paper.

## Phase 1 — Harden & integrate (≈30 days) · PLAUSIBLE
- [ ] Persistent Ed25519 keystore (replace per-process ephemeral keys).
- [ ] OSCAL schema validation step in CI (certify the emitted shape).
- [ ] n8n community-node wrapper (TS) as an alternative to Execute Command.
- [ ] First Civium round-trip: import OSCAL results into the compliance engine.
- [ ] Publish to `github.com/khaaliswooden-max/zandbox` with CI (pytest + lint).

## Phase 2 — Scale & close gaps (≈90 days) · PLAUSIBLE→SPECULATIVE
- [ ] Postgres/Neo4j `ClaimStore` backend behind the same interface.
- [ ] Monitor auto-suggestion (gap #2): rank stream statistics by drift
      sensitivity so unmonitored-variable drift becomes detectable.
- [ ] Conditional-coverage diagnostics for the conformal layer (gap #5).
- [ ] Calibrated confidence fusion for independent evidence (gap #1).
- [ ] First domain pilot: a CAH inference stream or an RWA sensor stream
      emitting DACs end-to-end with a live drift gate.

## Phase 3 — Federation & formalization · SPECULATIVE
- [ ] Cross-organization trust root + key distribution/revocation (gap #4),
      natural home for the federated-calibration FTO target.
- [ ] Liability/accountability semantics for stale-but-acted-upon claims (gap #6).
- [ ] Journal-length paper: worked CAH/RWA case study, conditional-coverage
      treatment, drift-detection latency study, extending the non-stationarity
      proofs whitepaper as the formal core.

See `docs/Specification.md` §6 for the authoritative gap list these phases close.
