"""Keep the OAuth token store out of the working tree.

`oauth.save_refresh_token` defaults to `.taktline-tokens.json` in the current
directory, so any test that triggers a refresh would otherwise drop a
credential file into the repo.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_token_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_STORE", str(tmp_path / "tokens.json"))
