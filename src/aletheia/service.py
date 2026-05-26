"""
service.py — OPTIONAL FastAPI HTTP wrapper (for the n8n HTTP Request node).

The stdlib `cli.py` is the recommended zero-dependency integration. Use this
only if you prefer an HTTP surface. Requires: fastapi, uvicorn.

Run: uvicorn aletheia.service:app --port 8088
A single shared SQLite store is used; set ALETHEIA_DB to choose the path.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover
    raise SystemExit("FastAPI not installed. `pip install fastapi uvicorn` "
                     "or use the stdlib cli.py instead.") from e

from .dac import (
    Producer, Substrate, ClaimStore, Classification, Confidence, _dac_from_dict,
)
from .oscal import export_assessment_results

DB = os.environ.get("ALETHEIA_DB", "aletheia.db")
app = FastAPI(title="Aletheia DAC Substrate", version="0.1.0")

# NOTE: ephemeral producer keys per process — load a real keystore in prod.
_producers: dict[str, Producer] = {}


def _runtime():
    store = ClaimStore(DB)
    rt = Substrate(store)
    for p in _producers.values():
        rt.register(p)
    return store, rt


class IssueReq(BaseModel):
    kind: str
    producer: str
    payload: str = ""
    classification: str = "INTERNAL"
    confidence: float = 0.9
    alpha: float = 0.1
    method: str = "asserted"
    monitor_id: Optional[str] = None
    ttl_s: float = 3600.0
    parents: list[str] = []
    requires_hitl: bool = False


@app.post("/issue")
def issue(req: IssueReq):
    store, rt = _runtime()
    prod = _producers.setdefault(req.producer, Producer(req.producer))
    rt.register(prod)
    try:
        parents = [_dac_from_dict(store.get(p)) for p in req.parents]
        dac = rt.issue(
            kind=req.kind, payload=req.payload.encode(), producer=prod,
            confidence=Confidence(req.method, req.confidence, req.alpha),
            classification=Classification[req.classification],
            monitor_id=req.monitor_id, ttl_s=req.ttl_s, parents=parents,
            requires_hitl=req.requires_hitl,
        )
    except KeyError:
        raise HTTPException(400, "bad classification or unknown parent")
    return {"id": dac.id, "confidence": dac.confidence.value,
            "classification": Classification(dac.classification).name,
            "requires_hitl": dac.requires_hitl,
            "status": dac.validity.status}


@app.post("/monitors/{monitor_id}/trip")
def trip(monitor_id: str):
    store, _ = _runtime()
    return {"cascaded_stale": store.cascade_stale(monitor_id)}


@app.get("/verify")
def verify():
    store, _ = _runtime()
    return {"chain_ok": store.verify_chain()}


@app.get("/export/oscal")
def export():
    store, _ = _runtime()
    return export_assessment_results(store, chain_ok=store.verify_chain())
