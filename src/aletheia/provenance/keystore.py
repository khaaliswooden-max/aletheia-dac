"""
keystore.py — persistent Ed25519 keystore.

Replaces aletheia-dac's per-process ephemeral producer keys, which are the
reason that repository could not back the other four: a key that dies with the
process cannot anchor a chain that outlives it. This is item 1 of the
aletheia-dac Phase 1 roadmap and item 5 of Track A.

Layout (directory mode 0o700):

    <root>/
      keystore.json          index: producer id -> fingerprint, created, label
      private/<name>.pem     PKCS#8 Ed25519 private key, mode 0o600
      trust/<name>.pub       raw 32-byte public key of a peer we verify but
                             do not sign for

Custody rules, carried over from Proteus zil_sign.py and non-negotiable:
  * Rotation is a NEW producer identifier, never an overwrite. ``create`` on an
    existing id raises rather than replacing signing material.
  * Private keys never leave this directory. Nothing here logs, prints, or
    serializes private key bytes.
  * No AI collaborator holds or handles production private key material. The
    conformance fixtures use a key derived from a published constant and
    labelled unmistakably as a test key; see vectors.py.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Optional

from . import codec

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class KeystoreError(Exception):
    """Raised for custody-rule violations and missing or malformed keys."""


def _safe_name(producer_id: str) -> str:
    """Map a producer id to a filename, rejecting anything path-unsafe.

    Precondition:  producer_id matches [A-Za-z0-9][A-Za-z0-9._-]{0,127}.
    Postcondition: the result contains no separator and is not '.' or '..'.
    """
    if not isinstance(producer_id, str) or not _SAFE_NAME.match(producer_id):
        raise KeystoreError(
            f"producer id {producer_id!r} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}"
        )
    if producer_id in (".", ".."):
        raise KeystoreError("producer id must not be '.' or '..'")
    return producer_id


class Keystore:
    """A persistent store of Ed25519 signing keys and peer public keys."""

    def __init__(self, root):
        self.root = Path(root)
        self.private_dir = self.root / "private"
        self.trust_dir = self.root / "trust"
        self.index_path = self.root / "keystore.json"
        for d in (self.root, self.private_dir, self.trust_dir):
            d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, stat.S_IRWXU)
            os.chmod(self.private_dir, stat.S_IRWXU)
        except OSError:
            pass  # best effort; some filesystems do not carry POSIX modes
        if not self.index_path.exists():
            self._write_index({})

    # ---- index ----------------------------------------------------------- #
    def _read_index(self) -> dict:
        try:
            return json.loads(self.index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise KeystoreError(f"keystore index unreadable: {exc}") from exc

    def _write_index(self, idx: dict) -> None:
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(idx, indent=1, sort_keys=True))
        tmp.replace(self.index_path)

    # ---- signing keys ---------------------------------------------------- #
    def _private_path(self, producer_id: str) -> Path:
        return self.private_dir / f"{_safe_name(producer_id)}.pem"

    def has(self, producer_id: str) -> bool:
        return self._private_path(producer_id).exists()

    def create(self, producer_id: str, passphrase: Optional[bytes] = None,
               label: str = "") -> "object":
        """Generate and persist a new signing key.

        Outputs: the Ed25519PrivateKey, also written to disk.
        Precondition:  no key exists for this producer id.
        Postcondition: the private file exists with mode 0o600 and the index
                       records the public fingerprint.
        Raises KeystoreError if a key already exists — rotation is a new
        identifier, never an overwrite.
        """
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        path = self._private_path(producer_id)
        if path.exists():
            raise KeystoreError(
                f"REFUSING: a key for {producer_id!r} already exists. "
                "Key rotation is a new producer identifier, not an overwrite."
            )
        key = Ed25519PrivateKey.generate()
        enc = (serialization.BestAvailableEncryption(passphrase)
               if passphrase else serialization.NoEncryption())
        pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8, enc)
        # Create with restrictive mode before any bytes land on disk.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)

        idx = self._read_index()
        idx[producer_id] = {
            "fingerprint": codec.fingerprint(key.public_key()),
            "public_key_hex": codec.public_key_bytes(key.public_key()).hex(),
            "encrypted": bool(passphrase),
            "label": label,
        }
        self._write_index(idx)
        return key

    def load(self, producer_id: str, passphrase: Optional[bytes] = None):
        """Load a persisted signing key.

        Precondition:  a key exists for this producer id.
        Postcondition: the returned key's public fingerprint matches the index.
        """
        from cryptography.hazmat.primitives import serialization

        path = self._private_path(producer_id)
        if not path.exists():
            raise KeystoreError(f"no signing key for producer {producer_id!r}")
        try:
            key = serialization.load_pem_private_key(path.read_bytes(),
                                                     password=passphrase)
        except (ValueError, TypeError) as exc:
            raise KeystoreError(
                f"could not load key for {producer_id!r} "
                "(wrong passphrase, or the file is not a PKCS#8 Ed25519 key)"
            ) from exc
        idx = self._read_index()
        recorded = idx.get(producer_id, {}).get("fingerprint")
        actual = codec.fingerprint(key.public_key())
        if recorded is not None and recorded != actual:
            raise KeystoreError(
                f"key for {producer_id!r} does not match the recorded "
                f"fingerprint ({actual} != {recorded}); refusing to sign"
            )
        return key

    def load_or_create(self, producer_id: str, passphrase: Optional[bytes] = None,
                       label: str = ""):
        """Load the key for a producer, generating one on first use."""
        if self.has(producer_id):
            return self.load(producer_id, passphrase)
        return self.create(producer_id, passphrase, label)

    def public_key(self, producer_id: str):
        """The public key for a producer: from the trust store, else the index."""
        trust_path = self.trust_dir / f"{_safe_name(producer_id)}.pub"
        if trust_path.exists():
            return codec.public_key_from_bytes(trust_path.read_bytes())
        entry = self._read_index().get(producer_id)
        if entry and entry.get("public_key_hex"):
            return codec.public_key_from_bytes(bytes.fromhex(entry["public_key_hex"]))
        raise KeystoreError(f"no public key known for producer {producer_id!r}")

    def producers(self) -> list:
        """Producer ids with a signing key in this store, sorted."""
        return sorted(p.stem for p in self.private_dir.glob("*.pem"))

    # ---- trust root ------------------------------------------------------ #
    def trust(self, producer_id: str, raw_public_key: bytes) -> None:
        """Record a peer's public key so its envelopes can be verified.

        Precondition:  raw_public_key is 32 bytes.
        Postcondition: ``public_key(producer_id)`` returns this key, and
                       ``is_trusted`` reports True for it.
        """
        if len(raw_public_key) != 32:
            raise KeystoreError("an Ed25519 public key is 32 raw bytes")
        (self.trust_dir / f"{_safe_name(producer_id)}.pub").write_bytes(raw_public_key)

    def trusted(self) -> list:
        """Producer ids present in the trust store, sorted."""
        return sorted(p.stem for p in self.trust_dir.glob("*.pub"))

    def is_trusted(self, producer_id: str, raw_public_key: bytes) -> bool:
        """Whether this exact public key is the one recorded for this producer.

        A v1 envelope carries its own public key, so verifying its signature
        proves internal consistency only. Authority requires this check.
        """
        try:
            known = codec.public_key_bytes(self.public_key(producer_id))
        except KeystoreError:
            return False
        return known == raw_public_key
