# Epistemic Framework

This project treats epistemic honesty as infrastructure, not decoration. The
same discipline applied in prose — marking every claim by how well it is
grounded — is what the substrate enforces mechanically. This document states the
framework so contributors apply it consistently.

## Confidence tiers
Every non-obvious claim in code comments, docs, and the roadmap is marked:

- **VERIFIED** — grounded in cited research, a standard, or a passing test in
  this repo. Example: monotone-propagation closure (proved in the paper, tests
  T3/T4/T6).
- **PLAUSIBLE** — logically sound and consistent with known results, but not yet
  validated here. Example: the Postgres/Neo4j backend design.
- **SPECULATIVE** — theoretical or research-grade; requires empirical work.
  Example: cross-organization federated trust semantics.

A claim with no marker is assumed VERIFIED and must be defensible as such.

## The substrate is the machine-checkable form of this discipline
The DAC's `confidence` field is exactly a VERIFIED/PLAUSIBLE/SPECULATIVE marker
made numerical and testable: a conformal coverage level with a guarantee, rather
than a prose hedge. Monotone propagation is the rule that a synthesis cannot be
more confident than its weakest premise — the formal version of "don't overstate
what the evidence supports." Drift invalidation is the rule that a once-VERIFIED
claim degrades when its grounding no longer holds.

## Four-phase method (Zuup Research Framework)
Changes of any size follow the same loop used to design this substrate:

1. **Deconstruct** — strip the problem to first principles; question every
   assumed threshold and buzzword. (This project began by deconstructing five
   "roads" to four binding constraints and finding the shared meta-gap.)
2. **Reconstruct** — build the minimal primitive that closes the root cause, not
   the symptom. (One envelope, not three subsystems.)
3. **Validate** — encode the intended property as a falsifiable test before
   claiming it works; prefer running code over assertion.
4. **Iterate** — record what remains unsolved as an explicit gap; do not let an
   intellectually coherent design masquerade as an operationally complete one.

## Gap-analysis protocol
Before calling any component "done," list what it does **not** do. The six open
gaps in `docs/Specification.md` §6 and the paper's Limitations section are the
output of this protocol for v0.1.0. Narrowing a gap is progress; pretending it
is closed is a regression.
