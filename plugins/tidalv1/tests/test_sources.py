from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest
from beets.util.config import sanitize_pairs
from beets.util.lyrics import Lyrics

import beetsplug.tidalv1 as plugin
from beetsplug import fetchart, lyrics
from beetsplug.tidalv1.auth import DeviceAuthExpired, DeviceCode, TokenSet
from beetsplug.tidalv1.client import AlbumMatch, LyricsResult, TidalAPIError, TrackMatch
from beetsplug.tidalv1.sources import TidalArtSource, TidalV1


def test_import_registers_lyrics_backend_and_fetchart_source():
    assert lyrics.BACKEND_BY_NAME["tidalv1"] is TidalV1
    assert TidalArtSource in fetchart.ART_SOURCES
    assert plugin.__version__


def test_auth_command_prints_authorization_url_in_one_message(monkeypatch):
    device = DeviceCode(
        device_code="device",
        user_code="ABCD",
        verification_uri="https://login.tidal.com/device",
        verification_uri_complete="https://login.tidal.com/device?code=ABCD",
        expires_in=30,
    )
    token = TokenSet(access_token="user-token")
    saved_tokens: list[TokenSet] = []
    manager = SimpleNamespace(
        cache_path="/tmp/tidalv1-token.json",
        start_device_authorization=lambda: device,
        poll_device_authorization=lambda received_device, sleep: token,
        save_token=saved_tokens.append,
    )
    messages: list[str] = []
    monkeypatch.setattr(
        plugin.AuthManager,
        "from_config",
        classmethod(lambda cls, config: manager),
    )
    monkeypatch.setattr(plugin.ui, "print_", messages.append)
    opened_urls: list[str] = []
    monkeypatch.setattr(plugin.webbrowser, "open", opened_urls.append)

    command = plugin.TidalV1Plugin().commands()[0]
    assert command.name == "tidalv1"
    for auth_flag in ("-a", "--auth"):
        opts, args = command.parser.parse_args([auth_flag])
        assert opts.auth
    command.func(None, opts, args)

    assert "Open this TIDAL authorization URL: " + device.verification_uri_complete in messages
    assert opened_urls == [device.verification_uri_complete]
    assert saved_tokens == [token]


def test_auth_command_prints_help_when_auth_is_omitted(monkeypatch):
    command = plugin.TidalV1Plugin().commands()[0]
    help_calls: list[bool] = []
    monkeypatch.setattr(command, "print_help", lambda: help_calls.append(True))
    monkeypatch.setattr(
        plugin.AuthManager,
        "from_config",
        classmethod(lambda cls, config: pytest.fail("authentication unexpectedly started")),
    )
    opts, args = command.parser.parse_args([])

    command.func(None, opts, args)

    assert help_calls == [True]


def test_auth_command_reports_device_authorization_timeout(monkeypatch):
    device = DeviceCode(
        device_code="device",
        user_code="ABCD",
        verification_uri="https://login.tidal.com/device",
        verification_uri_complete=None,
        expires_in=30,
    )

    def poll_device_authorization(received_device, sleep):
        raise DeviceAuthExpired("TIDAL device authorization expired")

    manager = SimpleNamespace(
        start_device_authorization=lambda: device,
        poll_device_authorization=poll_device_authorization,
        save_token=lambda token: pytest.fail("expired token unexpectedly saved"),
    )
    monkeypatch.setattr(
        plugin.AuthManager,
        "from_config",
        classmethod(lambda cls, config: manager),
    )
    monkeypatch.setattr(plugin.webbrowser, "open", lambda url: True)

    command = plugin.TidalV1Plugin().commands()[0]
    opts, args = command.parser.parse_args(["--auth"])

    with pytest.raises(
        plugin.UserError,
        match=r"TIDAL authorization timed out.*beet tidalv1 --auth.*try again",
    ):
        command.func(None, opts, args)


def test_tidal_fetchart_source_accepts_plain_source_config():
    available_sources = [
        (source.ID, criterion)
        for source in fetchart.ART_SOURCES
        for criterion in source.VALID_MATCHING_CRITERIA
    ]

    assert sanitize_pairs([("tidalv1", "*")], available_sources) == [("tidalv1", "default")]


def test_tidal_backend_returns_beets_lyrics(monkeypatch):
    track = TrackMatch(
        id=1550549,
        title="Harder, Better, Faster, Stronger",
        artist="Daft Punk",
        album="Discovery",
        duration=224,
        score=1.0,
    )
    result = LyricsResult(
        text="[00:01.00] Work it",
        provider="Provider",
        track=track,
        synced=True,
    )
    fake_client = SimpleNamespace(lyrics_for=lambda *args, **kwargs: result)
    monkeypatch.setattr("beetsplug.tidalv1.sources.client_from_config", lambda config: fake_client)

    backend = TidalV1(config=cast(Any, None), log=cast(Any, logging.getLogger("test")))
    fetched = backend.fetch("Daft Punk", "Harder Better Faster Stronger", "Discovery", 224)

    assert fetched is not None
    assert isinstance(fetched, Lyrics)
    assert fetched.text == "[00:01.00] Work it"
    assert fetched.backend == "tidalv1"
    assert fetched.url == "https://listen.tidal.com/track/1550549"


def test_tidal_art_source_yields_candidate(monkeypatch):
    album_match = AlbumMatch(
        id=123,
        title="Discovery",
        artist="Daft Punk",
        cover="aabbccdd-eeff-0011-2233-445566778899",
        score=1.0,
    )
    fake_client = SimpleNamespace(find_album=lambda *args, **kwargs: album_match)
    monkeypatch.setattr("beetsplug.tidalv1.sources.client_from_config", lambda config: fake_client)
    monkeypatch.setattr(
        "beetsplug.tidalv1.sources._config_value",
        lambda key, default, value_type=None: 2000 if key == "art_size" else default,
    )

    source = TidalArtSource(cast(Any, logging.getLogger("test")), config=cast(Any, {}))
    album = SimpleNamespace(albumartist="Daft Punk", album="Discovery")
    candidates = list(source.get(album, plugin=SimpleNamespace(), paths=None))

    assert len(candidates) == 1
    assert candidates[0].url.endswith("/1280x1280.jpg")
    assert candidates[0].size == (1280, 1280)
    assert candidates[0].source_name == "tidalv1"


def test_tidal_backend_warns_once_and_returns_no_result_after_retry_exhaustion(
    monkeypatch,
):
    def raise_rate_limit(*args, **kwargs):
        raise TidalAPIError("TIDAL API request failed with HTTP 429")

    fake_client = SimpleNamespace(lyrics_for=raise_rate_limit)
    monkeypatch.setattr("beetsplug.tidalv1.sources.client_from_config", lambda config: fake_client)
    messages: list[str] = []
    log = SimpleNamespace(warning=lambda message, *args: messages.append(message.format(*args)))
    backend = TidalV1(config=cast(Any, None), log=cast(Any, log))

    result = backend.fetch("Daft Punk", "Get Lucky", "Random Access Memories", 369)

    assert result is None
    assert messages == ["TidalV1: TIDAL API request failed with HTTP 429"]


def test_tidal_art_source_warns_once_and_returns_no_candidate_after_retry_exhaustion(
    monkeypatch,
):
    def raise_rate_limit(*args, **kwargs):
        raise TidalAPIError("TIDAL API request failed with HTTP 429")

    fake_client = SimpleNamespace(find_album=raise_rate_limit)
    monkeypatch.setattr("beetsplug.tidalv1.sources.client_from_config", lambda config: fake_client)
    messages: list[str] = []
    log = SimpleNamespace(warning=lambda message, *args: messages.append(message.format(*args)))
    source = TidalArtSource(cast(Any, log), config=cast(Any, {}))
    album = SimpleNamespace(albumartist="Daft Punk", album="Random Access Memories")

    candidates = list(source.get(album, plugin=SimpleNamespace(), paths=None))

    assert candidates == []
    assert messages == ["TIDAL art source failed: TIDAL API request failed with HTTP 429"]
