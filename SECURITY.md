# Security Policy

Aletheia is itself an integrity/attestation primitive, so its security
properties are part of its contract, not an afterthought.

## Reporting a vulnerability
Please report suspected vulnerabilities privately to the maintainer at
**aldrich.wooden@snhu.edu** rather than opening a public issue. Include a
description, reproduction steps, and the affected version/commit. Expect an
initial acknowledgement within a few business days. Please allow reasonable
time for a fix before any public disclosure.

## What the substrate guarantees (in scope)
- **Authenticity / non-repudiation:** every claim is signed by a producer's
  Ed25519 key; tampering with the payload hash or semantic fields invalidates
  the signature (test T1).
- **Tamper-evidence:** claims are linked in a SHA-256 hash chain; altering any
  stored record breaks chain verification (test T2).
- **Information-flow safety:** sensitivity is non-decreasing and human-gates are
  non-removable along derivation (tests T3, T4).
- **Freshness:** drift cascades invalidation to all provenance descendants of a
  shifted input (test T6).

## What it does NOT guarantee (known threat-model gaps)
These are documented open gaps, not bugs (see `docs/Specification.md` §6):
- **Cross-organization trust:** producer keys are trusted by intra-org
  registration; there is no federated key distribution/revocation yet. Do not
  rely on signatures across trust boundaries until Phase 3 lands.
- **Unmonitored drift:** a shift in a variable no monitor watches is invisible.
  Declare a `monitor_id` for every stream whose drift could matter.
- **Semantic integrity:** the DAC attests *which bytes* and *who produced them*,
  not that an artifact *means* what its producer claims.
- **Key custody:** the reference CLI uses ephemeral per-process keys for
  convenience; production deployments must use a persistent, access-controlled
  keystore (Phase 1).

## Handling regulated data
The substrate carries a `REGULATED` classification and forces a human-in-the-loop
gate for such claims, but it is **not** a substitute for a HIPAA/FISMA control
assessment. The OSCAL export is evidence input to that assessment, not a
certification.
