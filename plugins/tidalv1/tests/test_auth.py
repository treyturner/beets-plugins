from __future__ import annotations

import base64
import json
import os
import pathlib
import stat

import confuse
import pytest
import requests
from conftest import FakeResponse, FakeSession
from pytest import MonkeyPatch

import beetsplug.tidalv1.auth as auth_module
from beetsplug.tidalv1 import DEFAULT_CONFIG
from beetsplug.tidalv1.auth import (
    DEFAULT_AUTH_CACHE_FILENAME,
    AppCredentialsRequired,
    AuthManager,
    AuthRequired,
    DeviceCode,
    TokenSet,
    decode_v1_client_id_secret_b64,
    default_auth_cache_path,
)


@pytest.fixture(autouse=True)
def reset_discovered_app_credentials(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(auth_module, "_discovered_app_credentials", None)


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


def test_cached_rotated_refresh_token_takes_precedence_over_configured_token(
    tmp_path: pathlib.Path,
):
    cache_path = tmp_path / "auth.json"
    cache_path.write_text(
        json.dumps(
            TokenSet(
                access_token="expired-access",
                refresh_token="rotated-refresh",
                expires_at=1,
                scope="r_usr",
            ).to_json()
        )
    )
    session = FakeSession(
        post=[
            FakeResponse(
                payload={
                    "access_token": "refreshed-access",
                    "refresh_token": "next-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "r_usr",
                }
            )
        ]
    )
    manager = AuthManager(
        v1_client_id="client-id",
        v1_client_secret="client-secret",
        refresh_token="original-configured-refresh",
        cache_path=cache_path,
        session=session,
    )

    token = manager.get_token(require_user=True)

    assert token.access_token == "refreshed-access"
    assert session.post_calls[0]["data"]["refresh_token"] == "rotated-refresh"


def test_token_cache_atomically_replaces_existing_file_with_private_permissions(
    monkeypatch: MonkeyPatch,
    tmp_path: pathlib.Path,
):
    cache_path = tmp_path / "auth.json"
    cache_path.write_text("old token data\n")
    cache_path.chmod(0o644)
    manager = AuthManager(cache_path=cache_path)
    original_replace = os.replace
    observed_temp_modes: list[int] = []

    def inspect_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        observed_temp_modes.append(stat.S_IMODE(pathlib.Path(source).stat().st_mode))
        assert pathlib.Path(destination) == cache_path
        assert cache_path.read_text() == "old token data\n"
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", inspect_replace)

    manager.save_token(TokenSet(access_token="private-access", refresh_token="private-refresh"))

    assert observed_temp_modes == [0o600]
    assert stat.S_IMODE(cache_path.stat().st_mode) == 0o600
    assert json.loads(cache_path.read_text())["refresh_token"] == "private-refresh"


@pytest.mark.parametrize(
    "contents",
    [
        "not JSON",
        "[]",
        '{"access_token": "cached", "expires_at": "not-an-integer"}',
    ],
)
def test_invalid_token_cache_is_ignored(contents: str, tmp_path: pathlib.Path):
    cache_path = tmp_path / "auth.json"
    cache_path.write_text(contents)

    assert AuthManager(cache_path=cache_path).load_cached_token() is None


def test_client_credentials_token_is_not_accepted_for_user_scope(tmp_path: pathlib.Path):
    session = FakeSession(
        post=[
            FakeResponse(
                payload={
                    "access_token": "catalog-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
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
    with pytest.raises(AuthRequired):
        manager.get_token(require_user=True)


def test_catalog_token_falls_back_to_client_credentials_after_rejected_refresh(
    tmp_path: pathlib.Path,
):
    class RejectedRefreshResponse(FakeResponse):
        def raise_for_status(self) -> None:
            raise requests.HTTPError("refresh token rejected")

    session = FakeSession(
        post=[
            RejectedRefreshResponse(status_code=401),
            FakeResponse(
                payload={
                    "access_token": "catalog-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "",
                }
            ),
        ]
    )
    manager = AuthManager(
        v1_client_id="client-id",
        v1_client_secret="client-secret",
        refresh_token="revoked-refresh",
        cache_path=tmp_path / "auth.json",
        session=session,
    )

    token = manager.get_token(require_user=False)

    assert token.access_token == "catalog-token"
    assert [call["data"]["grant_type"] for call in session.post_calls] == [
        "refresh_token",
        "client_credentials",
    ]


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
            "tidalv1": {
                "v1_client_id": "client-id",
                "v1_client_secret": "client-secret",
                "auth_cache": "tokens/tidal.json",
            }
        }
    )

    manager = AuthManager.from_config(config["tidalv1"])

    assert manager.cache_path == beets_dir / "tokens" / "tidal.json"


def test_from_config_resolves_default_plugin_auth_cache_in_beets_app_dir(
    monkeypatch: MonkeyPatch, tmp_path: pathlib.Path
):
    beets_dir = tmp_path / "beets-state"
    monkeypatch.setenv("BEETSDIR", str(beets_dir))
    config = confuse.Configuration("beets", read=False)
    config.set(
        {
            "tidalv1": {
                **DEFAULT_CONFIG,
                "v1_client_id": "client-id",
                "v1_client_secret": "client-secret",
            }
        }
    )

    manager = AuthManager.from_config(config["tidalv1"])

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


def test_from_config_applies_timeout_to_best_effort_credential_lookup(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID_SECRET_B64", raising=False)
    encoded_pair = base64.b64encode(b"discovered-id;discovered-secret").decode()
    session = FakeSession(get=[FakeResponse(text=f'b64decode("{encoded_pair}")')])
    config = confuse.Configuration("beets", read=False)
    config.set({"tidalv1": {"request_timeout": 2.5}})

    manager = AuthManager.from_config(config["tidalv1"], session=session)

    assert manager.require_client_credentials() == ("discovered-id", "discovered-secret")
    assert session.get_calls[0]["timeout"] == 2.5


def test_from_config_caches_discovered_credentials_for_the_process(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID_SECRET_B64", raising=False)
    encoded_pair = base64.b64encode(b"discovered-id;discovered-secret").decode()
    session = FakeSession(get=[FakeResponse(text=f'b64decode("{encoded_pair}")')])

    first_manager = AuthManager.from_config(None, session=session)
    second_manager = AuthManager.from_config(None, session=session)

    expected_credentials = ("discovered-id", "discovered-secret")
    assert first_manager.require_client_credentials() == expected_credentials
    assert second_manager.require_client_credentials() == expected_credentials
    assert len(session.get_calls) == 1


def test_from_config_handles_best_effort_credential_lookup_network_failure(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TIDAL_V1_CLIENT_ID_SECRET_B64", raising=False)
    session = FakeSession()
    get_calls: list[dict[str, object]] = []

    def failing_get(url: str, **kwargs: object) -> FakeResponse:
        get_calls.append({"url": url, **kwargs})
        raise requests.Timeout("credential lookup timed out")

    monkeypatch.setattr(session, "get", failing_get)
    config = confuse.Configuration("beets", read=False)
    config.set({"tidalv1": {"request_timeout": 1.25}})

    with pytest.raises(AppCredentialsRequired):
        AuthManager.from_config(config["tidalv1"], session=session)

    assert get_calls[0]["timeout"] == 1.25
