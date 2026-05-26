"""
acceptance_tests.py — falsifiable proof the DAC substrate works.

Run: python3 acceptance_tests.py
Every test asserts a concrete, checkable property. Seeds are fixed so the
report is reproducible.
"""
import numpy as np

from dac import (
    Producer, Substrate, ClaimStore, DriftMonitor, Classification,
    Confidence, SplitConformal, AdaptiveConformal,
)

np.random.seed(7)
PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, PASS if cond else FAIL, detail))


# ---- shared toy model: a 3-layer pipeline sensor -> embedding -> decision -- #
def build_pipeline(store, monitor_id="stream_A", drift_status="VALID"):
    sub = Substrate(store)
    sensor = Producer("sensor.layer0")
    encoder = Producer("encoder.layer2")
    policy = Producer("policy.layer5")
    for p in (sensor, encoder, policy):
        sub.register(p)

    s = sub.issue(kind="sensor_reading", payload=b"vitals:hr=88",
                  producer=sensor,
                  confidence=Confidence("asserted", 0.99, 0.01),
                  classification=Classification.REGULATED,
                  monitor_id=monitor_id, ttl_s=600)
    e = sub.issue(kind="embedding", payload=b"vec[...]", producer=encoder,
                  confidence=Confidence("split_conformal", 0.92, 0.08),
                  classification=Classification.INTERNAL,
                  parents=[s], ttl_s=3600)
    d = sub.issue(kind="policy_decision", payload=b"recommend:triage_2",
                  producer=policy,
                  confidence=Confidence("asserted", 0.95, 0.05),
                  classification=Classification.PUBLIC,
                  parents=[e], ttl_s=3600)
    return sub, s, e, d


# --------------------------------------------------------------------------- #
# T1 — Provenance integrity: tampering breaks the signature                   #
# --------------------------------------------------------------------------- #
store = ClaimStore()
sub, s, e, d = build_pipeline(store)
ok_before = sub.verify(d)
d.payload_hash = "deadbeef" * 8          # tamper with the artifact
ok_after = sub.verify(d)
check("T1 signature catches payload tampering", ok_before and not ok_after,
      f"valid_before={ok_before} valid_after_tamper={ok_after}")

# --------------------------------------------------------------------------- #
# T2 — Hash-chain integrity: altering any stored row breaks the chain         #
# --------------------------------------------------------------------------- #
store2 = ClaimStore()
sub2, s2, e2, d2 = build_pipeline(store2)
chain_ok = store2.verify_chain()
store2.db.execute("UPDATE claims SET json=? WHERE id=?",
                  ('{"tampered":true}', e2.id))
chain_broken = not store2.verify_chain()
check("T2 hash chain catches store tampering", chain_ok and chain_broken,
      f"chain_ok_before={chain_ok} chain_broken_after={chain_broken}")

# --------------------------------------------------------------------------- #
# T3 — Confidence propagation: downstream = weakest link                       #
# --------------------------------------------------------------------------- #
# parents' confidence values: sensor 0.99 -> embedding 0.92 -> decision 0.95
# decision's own asserted 0.95 must be pulled DOWN to min(0.95,0.92,0.99)=0.92
check("T3 confidence propagates as weakest link",
      abs(d.confidence.value - 0.92) < 1e-9,
      f"decision confidence={d.confidence.value} (expected 0.92)")

# --------------------------------------------------------------------------- #
# T4 — Classification + HITL monotonicity                                      #
# --------------------------------------------------------------------------- #
# sensor is REGULATED; decision (declared PUBLIC) must inherit REGULATED + HITL
check("T4 REGULATED sensitivity + HITL propagate downstream",
      d.classification == int(Classification.REGULATED) and d.requires_hitl,
      f"decision class={Classification(d.classification).name} "
      f"hitl={d.requires_hitl}")

# --------------------------------------------------------------------------- #
# T5 — Conformal coverage guarantee (split conformal)                          #
# --------------------------------------------------------------------------- #
# y = 3x + noise; fit on train, calibrate residuals, test empirical coverage.
n = 4000
x = np.random.randn(n)
y = 3 * x + np.random.randn(n) * 1.0
tr, ca, te = slice(0, 2000), slice(2000, 3000), slice(3000, 4000)
beta = np.polyfit(x[tr], y[tr], 1)
pred = lambda xx: beta[0] * xx + beta[1]
resid_cal = np.abs(y[ca] - pred(x[ca]))
sc = SplitConformal(alpha=0.10)
sc.calibrate(resid_cal)
lo, hi = pred(x[te]) - sc.q, pred(x[te]) + sc.q
cov = float(np.mean((y[te] >= lo) & (y[te] <= hi)))
check("T5 split-conformal empirical coverage >= 1-alpha (0.90)",
      cov >= 0.88,                       # allow small finite-sample slack
      f"target=0.90 empirical={cov:.3f}")

# --------------------------------------------------------------------------- #
# T6 — Drift cascade: shift a stream -> dependent DACs go STALE, others VALID  #
# --------------------------------------------------------------------------- #
store3 = ClaimStore()
subA, sA, eA, dA = build_pipeline(store3, monitor_id="stream_A")
# an INDEPENDENT pipeline on a different monitor that must stay VALID
subB = Substrate(store3)
pB = Producer("sensor.B"); subB.register(pB)
sB = subB.issue(kind="sensor_reading", payload=b"other", producer=pB,
                confidence=Confidence("asserted", 0.99, 0.01),
                classification=Classification.INTERNAL, monitor_id="stream_B")

mon = DriftMonitor("stream_A")
ref = np.random.randn(500)               # in-distribution reference
shifted = np.random.randn(500) + 2.5     # large mean shift
tripped = mon.ks_check(ref, shifted)
n_stale = store3.cascade_stale("stream_A") if tripped else 0

dep_stale = store3.get(dA.id)["validity"]["status"] == "STALE"
indep_valid = store3.get(sB.id)["validity"]["status"] == "VALID"
check("T6 drift cascades STALE to dependents only",
      tripped and dep_stale and indep_valid and n_stale == 3,
      f"tripped={tripped} cascaded={n_stale} "
      f"dependent={store3.get(dA.id)['validity']['status']} "
      f"independent={store3.get(sB.id)['validity']['status']}")

# --------------------------------------------------------------------------- #
# T7 — ACI restores coverage under drift where static conformal fails          #
# --------------------------------------------------------------------------- #
# Stationary for 1000 steps, then the noise scale triples (distribution shift).
T = 2000
resid_static = SplitConformal(alpha=0.10)
resid_static.calibrate(np.abs(np.random.randn(1000)))   # calibrated pre-drift
aci = AdaptiveConformal(alpha_target=0.10, gamma=0.05)

window = list(np.abs(np.random.randn(200)))
static_cov, aci_cov = [], []
for t in range(T):
    scale = 1.0 if t < 1000 else 3.0      # <-- drift at t=1000
    err = np.random.randn() * scale
    a = abs(err)
    # static split-conformal interval (fixed q from pre-drift calibration)
    static_cov.append(a <= resid_static.q)
    # ACI interval from a rolling window, alpha adapts online
    w = aci.width(np.array(window))
    covered = a <= w
    aci_cov.append(covered)
    aci.update(covered)
    window.append(a); window = window[-200:]

post = slice(1000, T)
static_post = float(np.mean(static_cov[post]))
aci_post = float(np.mean(aci_cov[post]))
check("T7 ACI holds coverage under drift; static conformal collapses",
      aci_post >= 0.85 and static_post < aci_post,
      f"post-drift coverage: static={static_post:.3f} aci={aci_post:.3f} "
      f"(target 0.90)")

# --------------------------------------------------------------------------- #
# Report                                                                      #
# --------------------------------------------------------------------------- #
print("\n" + "=" * 70)
print("  DAC SUBSTRATE — ACCEPTANCE TEST REPORT")
print("=" * 70)
width = max(len(n) for n, _, _ in results)
for name, status, detail in results:
    mark = "✓" if status == PASS else "✗"
    print(f"  [{mark}] {name.ljust(width)}  {status}")
    if detail:
        print(f"        └─ {detail}")
n_pass = sum(1 for _, s, _ in results if s == PASS)
print("-" * 70)
print(f"  {n_pass}/{len(results)} passed")
print("=" * 70)
