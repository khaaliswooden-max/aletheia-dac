"""
verify — the one verifier, as a command line.

Track A deliverable 4 and Wave 1 definition-of-done item 1. Validates a chain
from any of the five substrates, detects the format itself, and reports which
format version every entry uses.

    python -m aletheia.provenance.verify <artifact> [options]

    python -m aletheia.provenance.verify chain.db
    python -m aletheia.provenance.verify LEDGER_0004.json --pubkey keys/vbx.pub
    python -m aletheia.provenance.verify episode.sqlite --pubkey zil.pub --json
    python -m aletheia.provenance.verify ledger/VBX_ISPS_LEDGER_0001.json \\
        --repo-root substrate

Exit codes:  0 verified · 1 defects found · 2 unrecognized artifact

This module imports only the stdlib plus ``cryptography``. It deliberately does
NOT pull in numpy or scipy, so verification runs on a bare Python anywhere —
which is the point of a cross-substrate verifier.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import legacy, verifier

EXIT_OK = 0
EXIT_DEFECTS = 1
EXIT_UNKNOWN = 2


def _load_pubkey(path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    raw = open(path, "rb").read()
    if raw.lstrip().startswith(b"-----BEGIN"):
        return serialization.load_pem_public_key(raw)
    if len(raw) == 32:
        return Ed25519PublicKey.from_public_bytes(raw)
    raise SystemExit(f"{path}: not a PEM or raw 32-byte Ed25519 public key")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aletheia.provenance.verify",
        description="Verify a provenance chain from any portfolio substrate.")
    ap.add_argument("artifact", help="SQLite chain database or JSON ledger entry")
    ap.add_argument("--pubkey", help="Ed25519 public key (PEM or raw 32 bytes)")
    ap.add_argument("--keystore", help="keystore directory, to check v1 producer "
                                       "keys against a trust root")
    ap.add_argument("--repo-root", help="repository root, to check PHRONESIS "
                                        "ledger manifest hashes")
    ap.add_argument("--json", action="store_true", help="emit the full report")
    args = ap.parse_args(argv)

    try:
        fmt = verifier.detect(args.artifact)
    except verifier.UnknownArtifact as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    pk = _load_pubkey(args.pubkey) if args.pubkey else None
    ks = None
    if args.keystore:
        from .keystore import Keystore
        ks = Keystore(args.keystore)

    try:
        report = verifier.verify(
            args.artifact, public_key=pk,
            public_keys=None, keystore=ks,
            pubkey_path=args.pubkey, repo_root=args.repo_root)
    except verifier.UnknownArtifact as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"{args.artifact}")
        print(f"  {verifier.summarize(report)}")
        if fmt == legacy.TAG_PHRONESIS_UNSIGNED:
            print(f"  note: {report['note']}")
        for d in report["defects"][:20]:
            print(f"  DEFECT {d}")
        if len(report["defects"]) > 20:
            print(f"  ... and {len(report['defects']) - 20} more")
    return EXIT_OK if report["ok"] else EXIT_DEFECTS


if __name__ == "__main__":
    sys.exit(main())
