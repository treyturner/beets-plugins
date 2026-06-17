from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

from beets.util.lyrics import Lyrics
from beetsplug import fetchart, lyrics

import beetsplug.tidalv1meta as plugin
from beetsplug.tidalv1meta.client import AlbumMatch, LyricsResult, TrackMatch
from beetsplug.tidalv1meta.sources import Tidal, TidalArtSource


def test_import_registers_lyrics_backend_and_fetchart_source():
    assert lyrics.BACKEND_BY_NAME["tidal"] is Tidal
    assert TidalArtSource in fetchart.ART_SOURCES
    assert plugin.__version__


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
    monkeypatch.setattr("beetsplug.tidalv1meta.sources.client_from_config", lambda config: fake_client)

    backend = Tidal(config=cast(Any, None), log=cast(Any, logging.getLogger("test")))
    fetched = backend.fetch("Daft Punk", "Harder Better Faster Stronger", "Discovery", 224)

    assert fetched is not None
    assert isinstance(fetched, Lyrics)
    assert fetched.text == "[00:01.00] Work it"
    assert fetched.backend == "tidal"
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
    monkeypatch.setattr("beetsplug.tidalv1meta.sources.client_from_config", lambda config: fake_client)

    source = TidalArtSource(cast(Any, logging.getLogger("test")), config=cast(Any, {}))
    album = SimpleNamespace(albumartist="Daft Punk", album="Discovery")
    candidates = list(source.get(album, plugin=SimpleNamespace(), paths=None))

    assert len(candidates) == 1
    assert candidates[0].url.endswith("/1280x1280.jpg")
    assert candidates[0].source_name == "tidal"
