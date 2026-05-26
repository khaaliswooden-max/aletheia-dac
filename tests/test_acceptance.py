"""
Acceptance tests for the DAC substrate — falsifiable, reproducible.

Run:  pytest -q          (from repo root, after `pip install -e .`)
or:   python tests/test_acceptance.py   (prints a human-readable report)
"""
import numpy as np

from aletheia.dac import (
    Producer, Substrate, ClaimStore, DriftMonitor, Classification,
    Confidence, SplitConformal, AdaptiveConformal,
)

np.random.seed(7)


def _pipeline(store, monitor_id="stream_A"):
    sub = Substrate(store)
    sensor, encoder, policy = (Producer("sensor.l0"),
                               Producer("encoder.l2"), Producer("policy.l5"))
    for p in (sensor, encoder, policy):
        sub.register(p)
    s = sub.issue(kind="sensor_reading", payload=b"vitals:hr=88",
                  producer=sensor, confidence=Confidence("asserted", 0.99, 0.01),
                  classification=Classification.REGULATED,
                  monitor_id=monitor_id, ttl_s=600)
    e = sub.issue(kind="embedding", payload=b"vec", producer=encoder,
                  confidence=Confidence("split_conformal", 0.92, 0.08),
                  classification=Classification.INTERNAL, parents=[s])
    d = sub.issue(kind="policy_decision", payload=b"recommend:triage_2",
                  producer=policy, confidence=Confidence("asserted", 0.95, 0.05),
                  classification=Classification.PUBLIC, parents=[e])
    return sub, s, e, d


def test_t1_signature_catches_tampering():
    sub, s, e, d = _pipeline(ClaimStore())
    assert sub.verify(d)
    d.payload_hash = "deadbeef" * 8
    assert not sub.verify(d)


def test_t2_hash_chain_catches_store_tampering():
    store = ClaimStore()
    sub, s, e, d = _pipeline(store)
    assert store.verify_chain()
    store.db.execute("UPDATE claims SET json=? WHERE id=?",
                     ('{"tampered":true}', e.id))
    assert not store.verify_chain()


def test_t3_confidence_propagates_weakest_link():
    _, s, e, d = _pipeline(ClaimStore())
    assert abs(d.confidence.value - 0.92) < 1e-9


def test_t4_regulated_and_hitl_propagate():
    _, s, e, d = _pipeline(ClaimStore())
    assert d.classification == int(Classification.REGULATED)
    assert d.requires_hitl


def test_t5_split_conformal_coverage():
    n = 4000
    x = np.random.randn(n); y = 3 * x + np.random.randn(n)
    ca, te = slice(2000, 3000), slice(3000, 4000)
    beta = np.polyfit(x[:2000], y[:2000], 1)
    pred = lambda xx: beta[0] * xx + beta[1]
    sc = SplitConformal(alpha=0.10); sc.calibrate(np.abs(y[ca] - pred(x[ca])))
    lo, hi = pred(x[te]) - sc.q, pred(x[te]) + sc.q
    cov = float(np.mean((y[te] >= lo) & (y[te] <= hi)))
    assert cov >= 0.88


def test_t6_drift_cascades_to_dependents_only():
    store = ClaimStore()
    subA, sA, eA, dA = _pipeline(store, monitor_id="stream_A")
    subB = Substrate(store); pB = Producer("sensor.B"); subB.register(pB)
    sB = subB.issue(kind="sensor_reading", payload=b"other", producer=pB,
                    confidence=Confidence("asserted", 0.99, 0.01),
                    classification=Classification.INTERNAL, monitor_id="stream_B")
    mon = DriftMonitor("stream_A")
    tripped = mon.ks_check(np.random.randn(500), np.random.randn(500) + 2.5)
    n = store.cascade_stale("stream_A") if tripped else 0
    assert tripped and n == 3
    assert store.get(dA.id)["validity"]["status"] == "STALE"
    assert store.get(sB.id)["validity"]["status"] == "VALID"


def test_t7_aci_holds_coverage_under_drift():
    T = 2000
    static = SplitConformal(alpha=0.10)
    static.calibrate(np.abs(np.random.randn(1000)))
    aci = AdaptiveConformal(alpha_target=0.10, gamma=0.05)
    window = list(np.abs(np.random.randn(200)))
    sc_cov, aci_cov = [], []
    for t in range(T):
        a = abs(np.random.randn() * (1.0 if t < 1000 else 3.0))
        sc_cov.append(a <= static.q)
        w = aci.width(np.array(window)); covered = a <= w
        aci_cov.append(covered); aci.update(covered)
        window.append(a); window = window[-200:]
    post = slice(1000, T)
    static_post, aci_post = np.mean(sc_cov[post]), np.mean(aci_cov[post])
    assert aci_post >= 0.85 and static_post < aci_post


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("\n" + "=" * 66 + "\n  DAC SUBSTRATE — ACCEPTANCE REPORT\n" + "=" * 66)
    npass = 0
    for t in tests:
        try:
            t(); print(f"  [\u2713] {t.__name__}  PASS"); npass += 1
        except AssertionError:
            print(f"  [\u2717] {t.__name__}  FAIL"); traceback.print_exc()
    print("-" * 66 + f"\n  {npass}/{len(tests)} passed\n" + "=" * 66)
