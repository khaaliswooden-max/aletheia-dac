# Aletheia — Drift-Aware Claim (DAC) Substrate

A portable epistemic substrate for non-stationary autonomous systems. Every
artifact a layer produces is wrapped in a signed, hash-chained **Drift-Aware
Claim** carrying its provenance graph, a *calibrated* confidence (conformal
coverage, not a softmax), and a validity window that **self-invalidates when a
monitored input drifts**. A derived claim can never silently drop the weakest
confidence, widest sensitivity, or shortest validity of its inputs.

> Closes the two cross-cutting gaps under the next generation of form factors:
> (1) nothing knows when its knowledge expired under drift, and (2) provenance +
> calibrated confidence don't survive the stack.

## Quickstart
```bash
pip install -e ".[dev]"
pytest -q                      # 7 acceptance tests
python tests/test_acceptance.py
```

## CLI (zero-dependency; drives n8n)
```bash
ID=$(python -m aletheia.cli issue --db s.db --kind sensor_reading \
      --producer sensor.l0 --classification REGULATED --confidence 0.99 \
      --alpha 0.01 --monitor stream_A --payload "hr=88" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
python -m aletheia.cli derive --db s.db --kind embedding --producer enc.l2 \
      --classification INTERNAL --confidence 0.92 --alpha 0.08 --parents $ID --payload vec
python -m aletheia.cli trip   --db s.db --monitor stream_A   # drift -> cascade STALE
python -m aletheia.cli verify --db s.db                      # audit chain
python -m aletheia.cli export-oscal --db s.db > results.json # Civium bridge
```

## Three mechanisms (all established techniques, novel composition)
1. **Monotone propagation** — typed precondition on derivation.
2. **Split conformal + Adaptive Conformal Inference** — coverage guarantee that
   survives drift.
3. **Page-Hinkley / KS drift monitor** — cascades staleness through the
   provenance graph.

See `CLAUDE.md` for the design contract, `paper/aletheia.tex` for the formal
treatment, and the spec for the gap analysis. Apache-2.0.
