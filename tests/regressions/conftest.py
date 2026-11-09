"""Shared fixtures for the regression tests.

Every folder write is now throttled (#153), and throttling keys its address hash with
`KYD_FOLDERS_SECRET`. Each test gets a fresh, random, test-only secret, so no test reads a live
credential and no secret is written in source. A test that checks the missing-secret refusal
still deletes the variable itself with `monkeypatch.delenv`.
"""

import secrets

import pytest

from app.folders.service import SECRET_ENV


@pytest.fixture(autouse=True)
def ephemeral_folders_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = secrets.token_hex(32)
    monkeypatch.setenv(SECRET_ENV, secret)
    return secret
