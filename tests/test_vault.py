import base64
import json

import pytest

from app.vault import decrypt_value, encrypt_value


def test_encrypt_decrypt_roundtrip():
    blob = encrypt_value("correct horse", "sk-secret-123")
    assert decrypt_value("correct horse", blob) == "sk-secret-123"


def test_blob_format_matches_prototype():
    blob = json.loads(encrypt_value("pw", "value"))
    assert blob["v"] == 1
    for f in ("salt", "iv", "ct"):
        assert f in blob
        base64.b64decode(blob[f])  # valid base64
    assert len(base64.b64decode(blob["salt"])) == 16
    assert len(base64.b64decode(blob["iv"])) == 12


def test_wrong_passphrase_fails():
    blob = encrypt_value("right", "value")
    with pytest.raises(Exception):
        decrypt_value("wrong", blob)
