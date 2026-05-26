"""
oscal.py — export the DAC claim store to an OSCAL-aligned assessment-results
document (NIST SP 800-53 / OSCAL), the bridge into Civium.

Each DAC becomes an OSCAL `observation`. STALE / tamper conditions become
`findings`. This makes the substrate's runtime state consumable by any
OSCAL-aware GRC tooling, and gives an auditor a single replayable artifact.

Reference shape: NIST OSCAL Assessment Results Model.
This emits the structure; run it through an OSCAL schema validator in CI to
certify conformance (see CLAUDE.md "definition of done").
"""
from __future__ import annotations

import json
import time
import uuid
import datetime as _dt
from typing import Optional

from .dac import ClaimStore, Classification


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()


# control mapping: which DAC property evidences which 800-53 / HIPAA control
CONTROL_MAP = {
    "signature": "au-10",     # non-repudiation
    "hash_chain": "au-9",     # protection of audit information
    "classification": "ac-4", # information flow enforcement
    "hitl": "ac-3",           # access enforcement / human gate
    "drift": "si-4",          # system monitoring
    "confidence": "si-7",     # software/firmware/information integrity
}


def export_assessment_results(store: ClaimStore,
                              chain_ok: Optional[bool] = None,
                              title: str = "Aletheia DAC Assessment Results"):
    rows = store.db.execute(
        "SELECT id, json, status, monitor_id FROM claims ORDER BY rowid"
    ).fetchall()

    observations, findings = [], []
    for dac_id, j, status, monitor_id in rows:
        d = json.loads(j)
        observations.append({
            "uuid": dac_id,
            "title": f"DAC:{d['kind']}",
            "description": (
                f"Producer {d['producer_id']} ({d['producer_fpr']}); "
                f"class={Classification(d['classification']).name}; "
                f"confidence={d['confidence']['value']:.3f} "
                f"({d['confidence']['method']}); status={status}"
            ),
            "methods": ["TEST"],
            "collected": _iso(d["validity"]["issued_at"]),
            "expires": _iso(d["validity"]["expires_at"]),
            "props": [
                {"name": "classification",
                 "value": Classification(d["classification"]).name,
                 "ns": "https://zuup.dev/ns/aletheia"},
                {"name": "requires-hitl", "value": str(d["requires_hitl"]),
                 "ns": "https://zuup.dev/ns/aletheia"},
                {"name": "control-id", "value": CONTROL_MAP["classification"]},
            ],
        })
        if status != "VALID":
            findings.append({
                "uuid": str(uuid.uuid4()),
                "title": f"Stale claim {dac_id[:8]} (monitor={monitor_id})",
                "description": "Governing input distribution drifted; claim "
                               "and its descendants invalidated.",
                "target": {"type": "objective-id",
                           "target-id": CONTROL_MAP["drift"],
                           "status": {"state": "not-satisfied"}},
                "related-observations": [{"observation-uuid": dac_id}],
            })

    if chain_ok is False:
        findings.append({
            "uuid": str(uuid.uuid4()),
            "title": "Audit hash chain integrity FAILED",
            "description": "Tamper detected: recomputed chain != stored chain.",
            "target": {"type": "objective-id",
                       "target-id": CONTROL_MAP["hash_chain"],
                       "status": {"state": "not-satisfied"}},
        })

    return {"assessment-results": {
        "uuid": str(uuid.uuid4()),
        "metadata": {
            "title": title,
            "last-modified": _iso(time.time()),
            "version": "0.1.0",
            "oscal-version": "1.1.2",
        },
        "import-ap": {"href": "#aletheia-assessment-plan"},
        "results": [{
            "uuid": str(uuid.uuid4()),
            "title": "DAC runtime snapshot",
            "description": "Point-in-time attestation of all claims.",
            "start": _iso(time.time()),
            "observations": observations,
            "findings": findings,
        }],
    }}


def to_json(store: ClaimStore, chain_ok: Optional[bool] = None) -> str:
    return json.dumps(export_assessment_results(store, chain_ok), indent=2)
