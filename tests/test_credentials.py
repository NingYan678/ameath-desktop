import os

import pytest

from digital_pet.credentials import CredentialStore


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is required")
def test_windows_credential_store_round_trips_without_plaintext(tmp_path):
    store = CredentialStore(tmp_path)
    store.save("deepseek", "not-a-real-key")

    assert store.load() == ("deepseek", "not-a-real-key")
    assert "not-a-real-key" not in store.path.read_text(encoding="utf-8")
