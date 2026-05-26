"""
cli.py — stdlib-only command line for the DAC substrate.

This is the zero-dependency integration surface for n8n (Execute Command node)
and for Claude Code automation. Every command reads/writes a SQLite file so
state persists across n8n steps. JSON in, JSON out.

Usage:
  python -m aletheia.cli issue   --db store.db --kind sensor_reading \
        --producer sensor.l0 --classification REGULATED --confidence 0.99 \
        --alpha 0.01 --monitor stream_A --payload "hr=88"
  python -m aletheia.cli derive  --db store.db --kind policy_decision \
        --producer policy.l5 --classification PUBLIC --confidence 0.95 \
        --alpha 0.05 --parents <id1> <id2> --payload "recommend:triage_2"
  python -m aletheia.cli trip    --db store.db --monitor stream_A
  python -m aletheia.cli verify  --db store.db
  python -m aletheia.cli export-oscal --db store.db > results.json
  python -m aletheia.cli status  --db store.db --id <dac_id>

Note: producer keys are ephemeral per process in this reference CLI. For
production, load persistent Ed25519 keys from a keystore (see CLAUDE.md).
"""
from __future__ import annotations

import sys
import json
import argparse

from .dac import (
    Producer, Substrate, ClaimStore, DriftMonitor, Classification, Confidence,
)
from .oscal import to_json


def _emit(obj):
    print(json.dumps(obj, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="aletheia")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--db", required=True)

    for name in ("issue", "derive"):
        sp = sub.add_parser(name)
        common(sp)
        sp.add_argument("--kind", required=True)
        sp.add_argument("--producer", required=True)
        sp.add_argument("--classification", default="INTERNAL",
                        choices=[c.name for c in Classification])
        sp.add_argument("--confidence", type=float, default=0.9)
        sp.add_argument("--alpha", type=float, default=0.1)
        sp.add_argument("--method", default="asserted")
        sp.add_argument("--monitor", default=None)
        sp.add_argument("--ttl", type=float, default=3600.0)
        sp.add_argument("--payload", default="")
        sp.add_argument("--hitl", action="store_true")
        if name == "derive":
            sp.add_argument("--parents", nargs="+", required=True)

    sp = sub.add_parser("trip"); common(sp); sp.add_argument("--monitor", required=True)
    sp = sub.add_parser("verify"); common(sp)
    sp = sub.add_parser("export-oscal"); common(sp)
    sp = sub.add_parser("status"); common(sp); sp.add_argument("--id", required=True)

    a = p.parse_args(argv)
    store = ClaimStore(a.db)
    sub_rt = Substrate(store)

    if a.cmd in ("issue", "derive"):
        prod = Producer(a.producer)
        sub_rt.register(prod)
        parents = []
        if a.cmd == "derive":
            # rehydrate parent DACs from store (as lightweight objects)
            from .dac import _dac_from_dict
            for pid in a.parents:
                parents.append(_dac_from_dict(store.get(pid)))
        dac = sub_rt.issue(
            kind=a.kind, payload=a.payload.encode(), producer=prod,
            confidence=Confidence(a.method, a.confidence, a.alpha),
            classification=Classification[a.classification],
            monitor_id=a.monitor, ttl_s=a.ttl, parents=parents,
            requires_hitl=a.hitl,
        )
        _emit({"id": dac.id, "kind": dac.kind,
               "confidence": dac.confidence.value,
               "classification": Classification(dac.classification).name,
               "requires_hitl": dac.requires_hitl,
               "status": dac.validity.status})

    elif a.cmd == "trip":
        n = store.cascade_stale(a.monitor)
        _emit({"monitor": a.monitor, "cascaded_stale": n})

    elif a.cmd == "verify":
        _emit({"chain_ok": store.verify_chain()})

    elif a.cmd == "export-oscal":
        print(to_json(store, chain_ok=store.verify_chain()))

    elif a.cmd == "status":
        d = store.get(a.id)
        _emit({"id": a.id, "status": d["validity"]["status"],
               "confidence": d["confidence"]["value"],
               "classification": Classification(d["classification"]).name})


if __name__ == "__main__":
    main(sys.argv[1:])
