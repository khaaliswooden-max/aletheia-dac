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

## v0.2.0 — `zil-provenance` shared core (current) · VERIFIED
Portfolio Wave 1, Track A. One wire format for all five substrates.
- Versioned wire-format specification (`docs/WIRE_FORMAT.md`) + CDDL schema,
  deterministic CBOR bound to RFC 8949 §4.2.1; written to be implementable in
  Rust without reading the Python.
- No floating-point values in a signed payload; scaled integers with rounding
  directions that always weaken the claim, so quantization cannot inflate a
  guarantee. Monotone propagation is now EXACT rather than approximate.
- `prev` moved inside the producer signature: a producer attests to its own
  chain position, as CADUCEUS-004 T1 and EPHEMERIS A7(3) both require.
- Domain-separated signing; the envelope carries its producer's public key.
- n-of-m attestation modelled from the start: an entry's signatures are a set
  (author + independent attestors), with the threshold policy recorded in the
  entry and attestor keys resolvable against a signed roster. Required by
  PORTFOLIO_BUILD_PLAN §7.6.9 — a one-signature schema would have forced a v2
  the moment the first attestor signs. No attestor is recruited and no real
  attestation exists; author-only is a valid instance of the model.
- 98 committed, signed conformance vectors including the adversarial set
  (reordering, unknown fields, empty parents, maximum lengths, non-ASCII,
  near-miss signatures, and the attestation rejections). These are what Rust and
  embedded C validate against.
- One verifier across all five substrates, with per-entry format reporting and
  read-only v0 tags for every legacy format. No historical entry re-signed.
- Persistent Ed25519 keystore with a local trust root.
- All four prior chain implementations refactored onto the core. Two remain
  format-pinned by frozen benchmarks and are recorded in
  `docs/BACK_EDGE_CANDIDATES.md` rather than silently changed.

**Not closed:** the Rust and embedded-C implementations, explicitly out of scope
for this pass. `PORTFOLIO_BUILD_PLAN.md` §10.2 also requires a second-language
implementation to reproduce the vectors; that half discharges in Caduceus M2 and
EPHEMERIS v0.3.

## Phase 1 — Harden & integrate (≈30 days) · PLAUSIBLE
- [x] Persistent Ed25519 keystore (replace per-process ephemeral keys).
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
