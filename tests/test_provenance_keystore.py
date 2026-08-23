"""Persistent Ed25519 keystore — replaces per-process ephemeral producer keys.

Falsification targets:
  * a key that does not survive the process, so a chain outlives its verifier
  * a rotation that silently overwrites signing material
  * a producer id that escapes the keystore directory
"""
import os
import stat

import pytest

from aletheia.provenance import Keystore, KeystoreError, codec


def test_key_survives_the_process(tmp_path):
    """The defect this module exists to fix: aletheia-dac's Producer generated
    a fresh key per process, so a stored envelope could never be re-verified."""
    ks = Keystore(tmp_path)
    key = ks.create("sensor.l0")
    fpr = codec.fingerprint(key.public_key())
    reopened = Keystore(tmp_path).load("sensor.l0")
    assert codec.fingerprint(reopened.public_key()) == fpr


def test_rotation_is_a_new_identifier_never_an_overwrite(tmp_path):
    ks = Keystore(tmp_path)
    ks.create("release-key-v1")
    with pytest.raises(KeystoreError, match="REFUSING"):
        ks.create("release-key-v1")
    ks.create("release-key-v2")           # rotation is a new id
    assert ks.producers() == ["release-key-v1", "release-key-v2"]


def test_private_key_file_is_not_world_readable(tmp_path):
    ks = Keystore(tmp_path)
    ks.create("p")
    mode = os.stat(tmp_path / "private" / "p.pem").st_mode
    assert not (mode & (stat.S_IRWXG | stat.S_IRWXO)), oct(mode)


def test_passphrase_protected_keys(tmp_path):
    ks = Keystore(tmp_path)
    ks.create("p", passphrase=b"correct horse")
    with pytest.raises(KeystoreError):
        ks.load("p", passphrase=b"wrong")
    assert ks.load("p", passphrase=b"correct horse") is not None


@pytest.mark.parametrize("bad", [
    "../escape", "a/b", "", ".", "..", "with space", "sensor\x00", "/abs",
])
def test_producer_ids_cannot_escape_the_keystore(tmp_path, bad):
    ks = Keystore(tmp_path)
    with pytest.raises(KeystoreError):
        ks.create(bad)


def test_fingerprint_mismatch_refuses_to_sign(tmp_path):
    """If the file on disk stops matching the recorded fingerprint, refuse."""
    ks = Keystore(tmp_path)
    ks.create("p")
    other = Keystore(tmp_path / "other")
    swapped = other.create("p")
    from cryptography.hazmat.primitives import serialization
    (tmp_path / "private" / "p.pem").write_bytes(swapped.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    with pytest.raises(KeystoreError, match="does not match the recorded"):
        ks.load("p")


def test_trust_root_distinguishes_consistency_from_authority(tmp_path):
    """A v1 envelope carries its own public key, so verifying its signature
    proves internal consistency only. Authority is the trust-root check."""
    ks = Keystore(tmp_path)
    mine = ks.create("peer")
    raw_mine = codec.public_key_bytes(mine.public_key())
    assert ks.is_trusted("peer", raw_mine)

    impostor = Keystore(tmp_path / "impostor").create("peer")
    raw_impostor = codec.public_key_bytes(impostor.public_key())
    assert not ks.is_trusted("peer", raw_impostor)


def test_trust_store_accepts_a_verify_only_peer(tmp_path):
    ks = Keystore(tmp_path)
    peer = Keystore(tmp_path / "peer").create("ephemeris.peer")
    raw = codec.public_key_bytes(peer.public_key())
    ks.trust("ephemeris.peer", raw)
    assert ks.trusted() == ["ephemeris.peer"]
    assert ks.is_trusted("ephemeris.peer", raw)
    assert codec.public_key_bytes(ks.public_key("ephemeris.peer")) == raw
    assert "ephemeris.peer" not in ks.producers()   # no signing key held


def test_trust_rejects_a_wrong_length_key(tmp_path):
    with pytest.raises(KeystoreError):
        Keystore(tmp_path).trust("p", b"\x00" * 31)


def test_load_or_create_is_idempotent(tmp_path):
    ks = Keystore(tmp_path)
    a = ks.load_or_create("p")
    b = ks.load_or_create("p")
    assert codec.fingerprint(a.public_key()) == codec.fingerprint(b.public_key())
