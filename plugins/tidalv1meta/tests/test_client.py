from __future__ import annotations

import pathlib
import pytest

from beetsplug.tidalv1meta.auth import AuthManager, AuthRequired
from beetsplug.tidalv1meta.client import TidalClient, cover_url, normalize, similarity

from conftest import FakeResponse, FakeSession


def test_cover_url_formats_uuid_and_caps_size():
    assert (
        cover_url("aabbccdd-eeff-0011-2233-445566778899", 2000)
        == "https://resources.tidal.com/images/aabbccdd/eeff/0011/2233/445566778899/1280x1280.jpg"
    )


def test_normalize_removes_features_and_punctuation():
    assert normalize("Song Title (Live) feat. Somebody!") == "song title"
    assert similarity("Harder Better Faster Stronger", "Harder, Better, Faster, Stronger") > 0.9


def test_find_track_selects_best_match(search_payload):
    client = TidalClient(
        AuthManager(access_token="token"),
        session=FakeSession(get=[FakeResponse(payload=search_payload)]),
    )

    match = client.find_track(
        "Daft Punk",
        "Harder Better Faster Stronger",
        album="Discovery",
        length=224,
    )

    assert match is not None
    assert match.id == 1550549
    assert match.score > 0.95


def test_lyrics_prefers_synced_subtitles(search_payload):
    session = FakeSession(
        get=[
            FakeResponse(payload=search_payload),
            FakeResponse(
                payload={
                    "lyrics": "Plain lyrics",
                    "subtitles": "[00:01.00] Synced lyrics",
                    "lyricsProvider": "Provider",
                }
            ),
        ]
    )
    client = TidalClient(AuthManager(access_token="user-token"), session=session)

    result = client.lyrics_for(
        "Daft Punk",
        "Harder Better Faster Stronger",
        album="Discovery",
        length=224,
    )

    assert result is not None
    assert result.text == "[00:01.00] Synced lyrics"
    assert result.synced
    assert result.url == "https://listen.tidal.com/track/1550549"


def test_lyrics_falls_back_to_plain_text(search_payload):
    session = FakeSession(
        get=[
            FakeResponse(payload=search_payload),
            FakeResponse(payload={"lyrics": "Plain lyrics", "subtitles": ""}),
        ]
    )
    client = TidalClient(AuthManager(access_token="user-token"), session=session)

    result = client.lyrics_for(
        "Daft Punk",
        "Harder Better Faster Stronger",
        album="Discovery",
        length=224,
    )

    assert result is not None
    assert result.text == "Plain lyrics"
    assert not result.synced


def test_lyrics_requires_user_scoped_token_after_catalog_search(search_payload, tmp_path: pathlib.Path):
    auth_session = FakeSession(
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
    client = TidalClient(
        AuthManager(
            v1_client_id="client-id",
            v1_client_secret="client-secret",
            cache_path=tmp_path / "auth.json",
            session=auth_session,
        ),
        session=FakeSession(get=[FakeResponse(payload=search_payload)]),
    )

    with pytest.raises(AuthRequired):
        client.lyrics_for("Daft Punk", "Harder Better Faster Stronger", album="Discovery", length=224)


def test_find_album_returns_cover_match(album_search_payload):
    client = TidalClient(
        AuthManager(access_token="token"),
        session=FakeSession(get=[FakeResponse(payload=album_search_payload)]),
    )

    match = client.find_album("Daft Punk", "Discovery")

    assert match is not None
    assert match.id == 123
    assert match.cover == "aabbccdd-eeff-0011-2233-445566778899"


def test_legacy_username_login_posts_to_v1_endpoint():
    session = FakeSession(post=[FakeResponse(payload={"sessionId": "session"})])
    client = TidalClient(AuthManager(access_token="token"), session=session)

    payload = client.legacy_username_login(
        username="user@example.test",
        password="secret",
        client_token="client-token",
    )

    assert payload["sessionId"] == "session"
    call = session.post_calls[0]
    assert call["url"] == "https://api.tidal.com/v1/login/username"
    assert call["data"]["username"] == "user@example.test"
