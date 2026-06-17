from __future__ import annotations

import base64
import json
import pathlib

import confuse
from pytest import MonkeyPatch

from beetsplug.tidalv1meta import DEFAULT_CONFIG
from beetsplug.tidalv1meta.auth import (
    DEFAULT_AUTH_CACHE_FILENAME,
    AuthManager,
    DeviceCode,
    TokenSet,
    decode_v1_client_id_secret_b64,
    default_auth_cache_path,
)

from conftest import FakeResponse, FakeSession


def test_refresh_token_is_saved_to_private_cache(tmp_path: pathlib.Path):
    session = FakeSession(
        post=[
            FakeResponse(
                payload={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "r_usr w_usr",
                    "user": {"countryCode": "US", "userId": 42},
                }
            )
        ]
    )
    manager = AuthManager(
        v1_client_id="client-id",
        v1_client_secret="client-secret",
        refresh_token="old-refresh",
        cache_path=tmp_path / "auth.json",
        session=session,
    )

    token = manager.get_token(require_user=True)

    assert token.access_token == "new-access"
    assert token.refresh_token == "new-refresh"
    assert session.post_calls[0]["data"]["grant_type"] == "refresh_token"
    cached = json.loads((tmp_path / "auth.json").read_text())
    assert cached["access_token"] == "new-access"
    assert oct((tmp_path / "auth.json").stat().st_mode & 0o777) == "0o600"


def test_client_credentials_token_is_not_accepted_for_user_scope(tmp_path: pathlib.Path):
    session = FakeSession(
        post=[
            FakeResponse(
                payload={
                    "access_token": "catalog-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "",
                }
            )
        ]
    )
    manager = AuthManager(
        v1_client_id="client-id",
        v1_client_secret="client-secret",
        cache_path=tmp_path / "auth.json",
        session=session,
    )

    token = manager.get_token(require_user=False)

    assert token.access_token == "catalog-token"
    assert not token.has_scope("r_usr")


def test_device_authorization_polls_until_success(tmp_path: pathlib.Path):
    session = FakeSession(
        post=[
            FakeResponse(status_code=400, payload={"error": "authorization_pending"}),
            FakeResponse(
                payload={
                    "access_token": "user-token",
                    "refresh_token": "refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "r_usr w_usr",
                }
            ),
        ]
    )
    manager = AuthManager(
        v1_client_id="client-id",
        v1_client_secret="client-secret",
        cache_path=tmp_path / "auth.json",
        session=session,
    )
    device = DeviceCode(
        device_code="device",
        user_code="ABCD",
        verification_uri="https://login.tidal.com",
        expires_in=30,
        interval=1,
    )

    token = manager.poll_device_authorization(device, sleep=lambda _: None)

    assert token.access_token == "user-token"
    assert len(session.post_calls) == 2
    assert session.post_calls[1]["data"]["grant_type"].endswith("device_code")


def test_cached_token_without_scope_metadata_can_be_used_for_user_scope(tmp_path: pathlib.Path):
    token = TokenSet(access_token="configured-user-token")
    cache = tmp_path / "auth.json"
    cache.write_text(json.dumps(token.to_json()))
    manager = AuthManager(cache_path=cache)

    assert manager.get_token(require_user=True).access_token == "configured-user-token"


def test_default_auth_cache_path_uses_beetsdir(monkeypatch: MonkeyPatch, tmp_path: pathlib.Path):
    beets_dir = tmp_path / "custom-beets-dir"
    monkeypatch.setenv("BEETSDIR", str(beets_dir))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert default_auth_cache_path() == beets_dir / DEFAULT_AUTH_CACHE_FILENAME


def test_default_auth_cache_path_uses_discovered_xdg_beets_app_dir(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
):
    xdg_config_home = tmp_path / "xdg-config"
    monkeypatch.delenv("BEETSDIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    (xdg_config_home / "beets").mkdir(parents=True)
    (xdg_config_home / "beets" / "config.yaml").write_text("plugins: []\n")

    assert default_auth_cache_path() == xdg_config_home / "beets" / DEFAULT_AUTH_CACHE_FILENAME


def test_from_config_resolves_relative_auth_cache_in_beets_app_dir(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
):
    beets_dir = tmp_path / "beets-state"
    monkeypatch.setenv("BEETSDIR", str(beets_dir))
    config = confuse.Configuration("beets", read=False)
    config.set(
        {
            "tidalv1meta": {
                "v1_client_id": "client-id",
                "v1_client_secret": "client-secret",
                "auth_cache": "tokens/tidal.json",
            }
        }
    )

    manager = AuthManager.from_config(config["tidalv1meta"])

    assert manager.cache_path == beets_dir / "tokens" / "tidal.json"


def test_from_config_resolves_default_plugin_auth_cache_in_beets_app_dir(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
):
    beets_dir = tmp_path / "beets-state"
    monkeypatch.setenv("BEETSDIR", str(beets_dir))
    config = confuse.Configuration("beets", read=False)
    config.set(
        {
            "tidalv1meta": {
                **DEFAULT_CONFIG,
                "v1_client_id": "client-id",
                "v1_client_secret": "client-secret",
            }
        }
    )

    manager = AuthManager.from_config(config["tidalv1meta"])

    assert manager.cache_path == beets_dir / DEFAULT_AUTH_CACHE_FILENAME


def test_base64_v1_client_secret_pair_decodes_like_tiddl():
    value = base64.b64encode(b"legacy-id;legacy-secret").decode()

    assert decode_v1_client_id_secret_b64(value) == ("legacy-id", "legacy-secret")


def test_from_config_falls_back_to_base64_when_direct_pair_is_incomplete(monkeypatch: MonkeyPatch):
    monkeypatch.setenv(
        "TIDAL_V1_CLIENT_ID_SECRET_B64",
        base64.b64encode(b"fallback-id;fallback-secret").decode(),
    )
    monkeypatch.setenv("TIDAL_V1_CLIENT_ID", "partial-id")
    monkeypatch.delenv("TIDAL_V1_CLIENT_SECRET", raising=False)

    manager = AuthManager.from_config(None)

    assert manager.require_client_credentials() == ("fallback-id", "fallback-secret")
