# zil-provenance — wire format specification, version 1

| | |
|---|---|
| **Document ID** | ALETHEIA-WIRE-001 |
| **Revision** | A |
| **Format version** | `v1` |
| **Scope** | aletheia-dac · PHRONESIS-1 · EPHEMERIS-1 · Proteus · Caduceus-1 |
| **Schema** | [`zil-provenance-v1.cddl`](zil-provenance-v1.cddl) |
| **Vectors** | [`../tests/vectors/zil_provenance_v1.json`](../tests/vectors/zil_provenance_v1.json) |
| **Parent plan** | [PORTFOLIO_BUILD_PLAN.md](PORTFOLIO_BUILD_PLAN.md) §1, §4 Track A |
| **Status** | Implemented in Python; Rust (Caduceus M2) and embedded C (EPHEMERIS v0.3) pending |

This document is normative. It is written to be implementable **without reading
the Python**. Where it and the CDDL disagree, this document governs.

Keywords MUST, MUST NOT, SHOULD and MAY are used in the RFC 2119 sense.

---

## 1. Why this exists

Before v1 there were **four independent Ed25519 hash-chain implementations** in
the portfolio and two more specified but unbuilt. VERIFIED by direct inspection,
2026-08-23:

| Implementation | Lines |
|---|---|
| `aletheia-dac/src/aletheia/dac.py` | 377 |
| `PHRONESIS-1/substrate/src/aletheia/chain.py` | 258 |
| `Proteus/zil_sign.py` | 206 |
| `Proteus/loop_a/chain.py` | 72 |

Every repository in the portfolio claims provenance is *portable*. With six
divergent formats that claim is false. `caduceus-attest` must sign byte-identical
tuples from Rust; the EPHEMERIS peer must verify them from embedded C on a
Cortex-M. Neither is possible without a canonical encoding fixed by
specification.

Four concrete defects motivated specific decisions here. All four are VERIFIED
by execution, not asserted:

- **D1 — "canonical JSON" was not one thing.** `zil_sign.py` used
  `ensure_ascii=False`; the other two used the default. For input
  `{"title": "Café — Mañana"}` they produce different bytes, so the same logical
  payload signs differently depending on which implementation touched it.
- **D2 — the JSON envelope could sign syntactically invalid JSON.** A `NaN`
  confidence serialized to a literal `NaN`, which Python's lenient decoder
  accepts and `serde_json` and every embedded-C parser reject. A Rust peer
  literally could not verify such an envelope.
- **D3 — an unframed hash preimage.** Proteus Loop B hashes
  `prev ‖ state_json ‖ signals_json ‖ ts` with no length prefixes and no
  separators, so field boundaries are ambiguous and distinct triples collide.
- **D4 — no domain separation anywhere.** A signature over a claim and a
  signature over a chain event were drawn from the same key with no context
  tag, so one could in principle be presented as the other.

---

## 2. Objects and terminology

The format defines exactly two signed structures.

**DAC envelope** (`dac-v1`) — a *claim*: an assertion about a payload, carrying
provenance, calibrated confidence, a validity window and a data classification.

**Chain entry** (`entry-v1`) — an *event*: a record that something happened at a
time, in a position in a chain, with an attested payload.

A **record hash** is the value a successor carries as its `prev`. A **chain** is
a sequence of structures where each one's `prev` equals its predecessor's record
hash, and the first one's `prev` is the genesis sentinel.

---

## 3. Encoding rules

The encoding is **deterministic CBOR**, bound to RFC 8949 §4.2.1 "Core
Deterministic Encoding Requirements". Each rule is restated here so an
implementer does not have to interpret the RFC.

### R1 — Definite length only

Every byte string, text string, array and map MUST use definite-length encoding.
Indefinite-length items (additional information 31) MUST NOT be produced and
MUST be rejected on decode.

### R2 — Shortest-form arguments

Every major type's argument — an integer's value, a string's byte length, an
array's element count, a map's pair count — MUST use the shortest encoding that
represents it:

| Argument range | Additional information | Following bytes |
|---|---|---|
| 0 – 23 | the value itself | 0 |
| 24 – 255 | 24 | 1 |
| 256 – 65 535 | 25 | 2 |
| 65 536 – 4 294 967 295 | 26 | 4 |
| 4 294 967 296 – 2⁶⁴−1 | 27 | 8 |

A decoder MUST reject an argument encoded in more bytes than necessary. For
example `18 17` (23 in one following byte) is invalid; `17` is the only valid
encoding of 23.

Integers outside `[−2⁶⁴, 2⁶⁴−1]` MUST be rejected. Bignum tags are not available.

### R3 — Map keys sorted by the bytewise order of their *encoded* bytes

Keys are compared as the byte strings their own deterministic encodings produce,
not as the values they denote.

**This is the rule implementations most often get wrong.** A text key shorter
than 24 bytes encodes as a head byte `0x60 + length` followed by its UTF-8
bytes, so the length dominates the comparison. Sorting the *strings* gives the
wrong order:

| Key | Encoded | |
|---|---|---|
| `"v"` | `61 76` | |
| `"id"` | `62 69 64` | `61 … < 62 …`, so `"v"` sorts **before** `"id"` |
| `"cls"` | `63 63 6c 73` | and `"id"` before `"cls"` |

Canonical order for `dac-v1`:

```
v, id, ph, pk, cls, ext, par, pid, val, conf, hitl, kind, prev
```

for `entry-v1`:

```
v, ep, et, ts, ext, seq, prev
```

for `confidence-v1`: `a, m, v, iv` · for `validity-v1`: `st, exp, iat, mon` ·
for either wire map: `e, s`.

A decoder MUST reject a map whose keys are not in this order.

### R4 — No duplicate map keys

An encoder MUST NOT emit a map containing two equal keys. A decoder MUST reject
one, rather than taking the first or last occurrence.

### R5 — Decoders reject, they do not re-canonicalize

A decoder MUST reject any input that is not the deterministic encoding of its
own value. It MUST NOT accept a non-canonical encoding and silently normalize
it. The test is: `encode(decode(x)) == x` for every accepted `x`.

This matters because a signature covers *bytes*. A decoder that re-canonicalizes
would verify a signature over bytes it did not receive.

### R6 — No floating-point values in a signed payload

No CBOR float (additional information 25, 26 or 27 under major type 7) may
appear in a signed structure. Encoders MUST refuse; decoders MUST reject.

Deterministic CBOR would otherwise require the shortest float that round-trips a
value, and Python, Rust and embedded C would all have to agree bit-for-bit on
that reduction. Many Cortex-M parts have a single-precision FPU or none at all,
so the EPHEMERIS peer could not reliably reproduce an `f64` payload. Section 4
replaces every float with a scaled integer.

The one place application floats survive is **inside an opaque chain-entry
payload** (§8), which is attested as bytes and never interpreted.

### R7 — Subset restrictions

CBOR tags (major type 6) MUST be rejected. Under major type 7, only `false`
(20), `true` (21) and `null` (22) are permitted; `undefined` (23) and all other
simple values MUST be rejected. A decoder MUST reject trailing bytes after the
top-level item.

---

## 4. Quantization

### 4.1 Representation

| Field | Type | Scale | Rounding |
|---|---|---|---|
| `conf.v` (coverage) | `uint32` | parts per million; `1.0` = `1 000 000` | **floor** |
| `conf.a` (alpha) | `uint32` | parts per million | **ceil** |
| `val.iat` | `uint64` | µs since the Unix epoch, UTC | **ceil** |
| `val.exp` | `uint64` | µs since the Unix epoch, UTC | **floor** |
| `conf.iv[0]` (lo) | `[int64, int]` | `m · 10ᵉ` | **floor** |
| `conf.iv[1]` (hi) | `[int64, int]` | `m · 10ᵉ` | **ceil** |

### 4.2 Range limits and overflow

- `conf.v` and `conf.a` MUST be in `[0, 1 000 000]`. A value above the maximum
  MUST be rejected, never clamped — a clamp would silently turn an invalid
  claim into a maximal one.
- `val.iat` and `val.exp` MUST be in `[0, 253 402 300 799 999 999]`, the last
  microsecond of 9999-12-31 UTC. The bound keeps every value inside a `uint64`
  and inside the range every mainstream date library can render.
- `val.exp >= val.iat` is REQUIRED. `exp == iat` is legal and denotes a claim
  that was never valid.
- Interval mantissas MUST fit a signed 64-bit integer.
- Arithmetic overflow MUST be an error. No wrapping, no saturation.

### 4.3 The rounding rule

**Every rounding direction weakens the claim, so quantization can never inflate
a guarantee.**

- Coverage floors down — quantization never overstates confidence.
- Alpha ceils up — never understates the miscoverage rate.
- The validity window narrows from both ends — never extends validity.
- Interval endpoints move outward — the interval only ever widens.

This composes with monotone propagation (§9) and makes it *exact*: `min`, `max`
and interval intersection over integers have none of the comparison edge cases
their float equivalents carry.

### 4.4 The reduction is exact-rational

When an implementation accepts a real-valued input and must reduce it, it MUST
interpret the input as its **exact value** and then apply the rounding
direction. For an IEEE-754 double that means the exact binary value the double
holds, not the decimal literal an author typed.

This is observable and the specification pins it:

| Input | Naive `floor(x · 10⁶)` | Specified | |
|---|---|---|---|
| the double nearest `0.99` | 990000 | **989999** | the double is strictly below 0.99 |
| the double nearest `0.95` | 950000 | **949999** | |
| decimal `"0.99"` | 990000 | **990000** | an exact decimal input is exact |
| the double nearest `0.92` | 920000 | **920000** | this one quantizes exactly |

The naive form rounds **up** and overstates the coverage the producer actually
asserted — the exact defect the rounding directions exist to prevent. Reporting
989999 for the double is the truthful reading: the producer did not assert 0.99,
it asserted the nearest double, which is smaller.

**Implementations SHOULD accept integers or decimal strings at the API boundary
and avoid the question entirely.** A float-accepting compatibility layer MUST use
the exact-rational rule above. Conformance vectors
`value-floor-double-below-literal` and `value-floor-exact-decimal` pin both
readings.

> **Do not round-trip a quantized value through a float.** For roughly half of
> all ppm values `n`, `floor(exact(n / 10⁶) · 10⁶) ≠ n`. A system that re-derived
> the integer from a float on every read would drift downward one ppm at a time.
> The integer is authoritative; a float rendering is a one-way view.
> VERIFIED by execution.

### 4.5 Epoch — and the hazard at the EPHEMERIS boundary

**The envelope timestamp is microseconds since the Unix epoch, UTC.** Provenance
timestamps are wall-clock event times shared across all five substrates, so the
envelope takes the universal convention.

EPHEMERIS uses `uint64` microseconds since **J2000 in TT** internally. That is a
domain-specific choice for its astronomical payload and it stays internal. The
peer converts at the envelope boundary.

> ### HAZARD — read this before writing the conversion
>
> **TT-to-UTC is not a fixed offset.** The conversion crosses the leap-second
> table. This is exactly the class of defect EPHEMERIS already found and drove
> back into its own benchmark as **`DC-6`**: a constant `TAI−UTC = 37`
> assumption that silently corrupted oracle correctness by ~2–27 s on pre-2017
> epochs, for **every body**, not just Earth. Do not reintroduce it.
>
> The conversion MUST use the IERS Bulletin C table the device already carries
> (`wearable-firmware-v0.2/solution/iers_leap_seconds.json`, 28 entries,
> hash-pinned), via the era lookup the firmware already implements
> (`tai_minus_utc_at_jd_tt`).
>
> Pre-1972 epochs MUST signal out-of-scope rather than compute silently, per
> benchmark assertion **A1d**. The firmware raises `OutOfScopeError`; the
> envelope encoder MUST propagate that rather than emitting a timestamp.
>
> The validated envelope is `[1972-01-01, 2100-01-01]`; the firmware's exact
> integer-domain check is `micros_in_validated_envelope`.

**Open conflict, recorded not resolved.** `CADUCEUS-004` **T1** signs a
`timestamp_tuple`, and **F1** fixes `(TAI_microseconds, vbx-body-URN)` with
envelope `[1972-01-01, 2101-01-01)` **TAI**. That is a different artifact — a BP7
bundle attestation, not a provenance envelope — so the two can coexist. But if
`caduceus-attest` is built on this envelope, the epochs collide. This is
reported as a finding; **no benchmark file is modified**. See
[BACK_EDGE_CANDIDATES.md](BACK_EDGE_CANDIDATES.md) BEC-3.

---

## 5. Signing and hashing

One construction, both structures.

```
msg          = DOMAIN ‖ deterministic_cbor(structure)
signature    = Ed25519(secret_key, msg)
record_hash  = SHA-256(msg ‖ signature)
```

### 5.1 Domain separation

```
DOMAIN_DAC   = "zil-provenance/v1/dac"   ‖ 0x00
DOMAIN_CHAIN = "zil-provenance/v1/chain" ‖ 0x00
```

as bytes:

```
DOMAIN_DAC   = 7a696c2d70726f76656e616e63652f76312f64616300
DOMAIN_CHAIN = 7a696c2d70726f76656e616e63652f76312f636861696e00
```

The trailing NUL keeps any tag from being a prefix of another, so the tag
boundary stays unambiguous as tags are added. A verifier MUST verify under the
tag for the structure it is checking, and MUST NOT accept a signature made under
another tag. Vector `near-miss-wrong-domain` pins this.

### 5.2 Sign the message, not a digest

The signature is over `msg`. It is **not** over a SHA-256 of `msg`, and **not**
over an ASCII-hex rendering of one.

Ed25519 already hashes internally. Signing a digest with plain Ed25519 is not
Ed25519ph; it adds a step and gives up the collision-resilience argument. The
legacy implementations disagreed here in two different ways — PHRONESIS signed
`bytes.fromhex(entry_hash)`, Proteus Loop B signed the 64 ASCII hex characters —
and neither convention bought anything.

### 5.3 The record hash binds the attestation

`record_hash` covers the signature as well as the content, so an entry cannot be
re-attested without changing the value its successor chains onto.

### 5.4 Genesis

The genesis `prev` is **32 zero bytes**, which is `"0" * 64` in hex.

PHRONESIS already used this value. aletheia-dac used `""` and Proteus used the
literal string `"GENESIS"`; both are normalized to the 32 zero bytes in v1.

### 5.5 `prev` is inside the signature

`prev` is a field of the signed structure. **A producer attests to its own
position in the chain.**

The legacy DAC envelope excluded `prev_hash` from the signature so the store
could link records after signing. That was implementation convenience and its
cost was real: an attacker who could re-link a record kept a valid producer
signature. `CADUCEUS-004` **T1** and EPHEMERIS **A7(3)** both require the
predecessor hash to be signed.

The practical consequence for implementers: **read the chain head before
signing**, not after. Vector `near-miss-different-prev` pins that a signature
over the same claim at a different chain position must fail.

---

## 6. The DAC envelope

See the CDDL for the exact schema. Field notes:

| Field | Type | Notes |
|---|---|---|
| `v` | `1` | format version; any other value MUST be rejected |
| `id` | 16 bytes | UUID as raw bytes, not a 36-character string |
| `kind` | text | application-defined claim kind |
| `ph` | 32 bytes | SHA-256 of the payload, raw |
| `pid` | text | producer identifier |
| `pk` | 32 bytes | the producer's raw Ed25519 public key |
| `par` | array of 16-byte ids | sorted bytewise ascending, no duplicates; empty is valid |
| `conf` | map | §4 |
| `val` | map | §4 |
| `cls` | `0..3` | PUBLIC, INTERNAL, CONFIDENTIAL, REGULATED |
| `hitl` | bool | human-in-the-loop gate |
| `prev` | 32 bytes | §5.5 |
| `ext` | map, optional | §7 |

### 6.1 The envelope carries the key, not a fingerprint

`pk` is the raw public key, so a peer holding only the envelope can verify it
against a trust root. The legacy envelope carried a 16-hex-character
`producer_fpr`, which could identify a producer but never verify one.

**Verifying the signature proves internal consistency, not authority.** An
envelope signs itself with the key it carries; anyone can make one. Authority
requires checking `pk` against a trust root, and a verifier MUST treat the two
as separate results.

### 6.2 Parent ordering is canonical

Parent ids MUST be sorted bytewise ascending with no duplicates, so the same
provenance set always encodes to the same bytes regardless of the order a caller
supplied. An empty `par` is a genesis claim, not an error.

### 6.3 REGULATED implies the gate

`cls == 3` REQUIRES `hitl == true`, at the **schema** level. A hand-built
envelope cannot assert REGULATED without the gate, so the compliance property
does not depend on a particular runtime having enforced it.

---

## 7. Versioning and unknown fields

### 7.1 Unknown fields are REJECTED, not ignored

A decoder MUST reject any key it does not recognize at the top level of
`dac-v1` or `entry-v1`, and inside `conf` and `val`.

"Ignore what you do not understand" is the usual convention and it is **unsound
here**. A verifier that ignores an unknown key verifies a signature over bytes
it did not fully understand, and would report a claim as attested while
silently discarding part of what was attested.

### 7.2 Extension goes through `ext`

Per-substrate fields go in the optional `ext` map, which is declared, signed and
strictly typed. PHRONESIS carries nanosecond timestamps there; EPHEMERIS carries
its TT epoch and body URN. `ext` values are subject to the no-float rule (R6);
anything else belongs in a byte string.

### 7.3 Version tagging

`v` is the format version. A structure with `v != 1` MUST be rejected by a v1
implementation. A future v2 is a new tag, not a negotiated extension.

### 7.4 Legacy formats are read, never rewritten

Chains are **append-only** across this portfolio. Pre-v1 artifacts are verified
under a v0 tag and MUST NOT be re-signed, migrated or rewritten:

| Tag | Covers | Verifies |
|---|---|---|
| `v0-dac-json` | legacy aletheia-dac envelopes | signature (if a key survives) + chain |
| `v0-phronesis-chain` | legacy PHRONESIS chain rows | signature + chain |
| `v0-zil-ledger` | Proteus release ledger | signature + payload hash |
| `v0-loop-b` | Proteus Loop B rows | signature + chain |
| `v0-phronesis-unsigned` | `VBX_ISPS_LEDGER_0001`–`0005` | linkage + manifest only |

Two of these are **permanently pinned**, not deprecated:

- `v0-loop-b` — the auditor that validates it lives inside a hash-committed
  benchmark bundle and cannot be edited.
- `v0-zil-ledger` — `LEDGER_0004.json` is signed history and `#0005` must chain
  onto it under the same `schema_version`.

> **`v0-phronesis-unsigned` is not a cryptographic tag.** VERIFIED by direct
> inspection, 2026-08-23: `VBX_ISPS_LEDGER_0001`–`0005` carry
> `"signing_key": "PLACEHOLDER — production key custody required …"`, no
> signature field, and no public key exists anywhere in that repository. They
> also use two incompatible schemas (`0001`–`0003` vs `0004`–`0005`). A verifier
> MUST report `signature: ABSENT` for them and MUST NOT report a verification.
> This corrects a description of them as "signed history" that appears in both
> the Track A brief and PORTFOLIO_BUILD_PLAN.md §4.

---

## 8. The chain entry

| Field | Type | Notes |
|---|---|---|
| `v` | `1` | |
| `seq` | uint | position in the chain |
| `ts` | uint | µs since the Unix epoch, UTC |
| `et` | text | event type |
| `ep` | **byte string** | opaque payload |
| `prev` | 32 bytes | |
| `ext` | map, optional | §7.2 |

### 8.1 The payload is opaque

A chain entry attests that *these exact bytes* occurred at this time in this
position. It does not interpret them. This is deliberate:

- The substrate that produces an event owns its payload schema. PHRONESIS logs
  float telemetry (partial pressures, latencies); Proteus logs state and signal
  objects. Forcing those under the no-float rule would rewrite application data
  that has nothing to do with provenance.
- A Rust or embedded-C peer reproduces the entry hash by hashing the same bytes.
  It never has to parse the payload, let alone re-serialize it identically —
  which would otherwise be a silent portability trap.
- Tamper detection is unaffected and arguably sharper: any change to the bytes
  changes the hash, whatever the bytes mean.

A substrate that wants field-level cross-verification of its payloads SHOULD
itself encode them as deterministic CBOR and decode `ep` as such.

---

## 9. Monotone propagation

When a DAC is derived from parents, a conforming runtime MUST enforce:

```
conf.v   = min(self, parents)          only as strong as the weakest link
conf.a   = max(self, parents)          only as loose as the loosest link
val.iat  = max(self, parents)          window intersection
val.exp  = min(self, parents)          window intersection
cls      = max(self, parents)          REGULATED taints downstream
hitl     = OR(self, parents), forced true when cls == REGULATED
val.st   = STALE if any parent is not VALID
```

If the intersection is empty (`exp < iat`), the window is clamped to
`exp = iat` and the claim is born STALE. An empty intersection is a claim that
was never valid, not an error.

**On integers this is exact.** The float implementation was approximate at the
boundary; `min`, `max` and interval intersection over integers have no
comparison edge cases. Acceptance tests T3, T4 and T6 continue to cover the
invariant and are now exact rather than approximate.

> **Note on alpha.** The legacy runtime propagated coverage by `min` but left
> alpha at the child's own value, which is incoherent: a derived claim could
> report `value = 0.92` alongside `alpha = 0.05`. v1 propagates alpha by `max`.
> This is a strengthening of the invariant, not a weakening, and it has its own
> test.

> **Open gap #1, unchanged.** `min`-combination still under-counts genuinely
> independent corroborating evidence. Exact integer arithmetic does not narrow
> that gap; it only removes the float edge cases from the existing rule.

---

## 10. Conformance

An implementation conforms if it reproduces every vector in
[`tests/vectors/zil_provenance_v1.json`](../tests/vectors/zil_provenance_v1.json)
byte-for-byte, and rejects every vector marked for rejection.

| Section | Count | What it pins |
|---|---|---|
| `cbor` | 24 | encodings, including shortest-form boundaries, key ordering, non-ASCII, maximum lengths |
| `cbor_reject` | 16 | indefinite length, non-shortest form, misordered and duplicate keys, floats, tags, trailing bytes |
| `quantize` | 12 | every rounding direction at a boundary, including the exact-rational divergence |
| `quantize_reject` | 6 | range limits, non-finite input |
| `dac` | 6 | signing bytes, signature, record hash, wire form |
| `entry` | 5 | including a float-bearing opaque payload |
| `near_miss` | 8 | signatures one bit, one byte, one domain or one `prev` away from valid |
| `schema_reject` | 14 | unknown fields, missing fields, range violations, unsorted parents, REGULATED without the gate |

The adversarial categories the brief requires — field reordering, unknown fields,
empty parent sets, maximum-length fields, non-ASCII, near-miss signatures — are
each covered, and a test asserts none of them silently disappears.

### 10.1 The conformance signing key is a test key

The vectors are signed with a key derived from a published constant:

```
private scalar = SHA-256("zil-provenance/v1/conformance-test-key/DO-NOT-USE-IN-PRODUCTION")
public key     = 02bcf62706e024b12a2ca4f7a75ae4dab5b0356fdfe23269b05a7f068664b9f5
```

Anyone can rederive it and regenerate the fixtures. It has **no custody and no
provenance weight and MUST NOT sign anything real.** No AI collaborator holds or
handles production key material.

### 10.2 Wave 1 exit

PORTFOLIO_BUILD_PLAN.md §10.2 requires that "a second implementation in another
language reproduces them byte-for-byte". Rust and embedded C are explicitly out
of scope for this pass. **That half of §10.2 is not closed** and discharges in
Caduceus M2 and EPHEMERIS v0.3, against exactly these vectors.

---

## 11. Implementation checklist

For an implementer starting from this document:

1. Write the deterministic CBOR encoder and decoder. Enforce R1–R7. Get
   `cbor` and `cbor_reject` green before anything else — every later failure
   otherwise looks like a signing bug.
2. Sort map keys by **encoded** bytes. Re-read §3 R3.
3. Write the quantizers. Do not multiply by `1e6` in floating point (§4.4).
4. Build the structures. Reject unknown keys (§7.1).
5. Implement `msg = DOMAIN ‖ cbor(struct)`; sign `msg`, not a digest (§5.2).
6. Read the chain head **before** signing (§5.5).
7. Check `record_hash = SHA-256(msg ‖ signature)` against the `dac` and `entry`
   vectors.
8. Run `near_miss` and `schema_reject`. An implementation that passes the happy
   path and fails these is not conforming — it is permissive.

---

## 12. Open gaps this format does NOT close

Stated so no reader infers more than was built.

1. **Cross-organization trust root and key distribution** remain unbuilt
   (aletheia-dac open gap #4). §6.1 separates consistency from authority and
   the keystore gives a local trust root; federation, rotation and revocation
   across organizations are future work.
2. **`min`-combination under-counts independent evidence** (open gap #1),
   unchanged. See §9.
3. **Byte-provenance is not semantic provenance** (open gap #3). A conforming
   chain proves what bytes were attested by whom, in what order. It says
   nothing about whether the claim is *true*.
4. **The Caduceus epoch conflict** (§4.5) is reported, not resolved.
5. **Two legacy formats are permanently pinned** (§7.4) with known defects
   (D3 above, BEC-1 and BEC-2). They cannot be repaired in place without
   editing a frozen benchmark.
6. **Multi-party attestation** is untouched. Single-attestor commits remain the
   largest methodology gap the portfolio names about itself.

---

*Prepared under ZCS-6 ordering discipline. This document specifies a format; it
does not commit a ledger entry or upgrade any epistemic marker.*
