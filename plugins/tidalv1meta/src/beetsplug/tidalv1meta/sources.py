from __future__ import annotations

from typing import Any, cast

import requests
from beets import config as beets_config
from beets.util.lyrics import Lyrics
from beetsplug import fetchart as fetchart_mod
from beetsplug import lyrics as lyrics_mod
from beetsplug.fetchart import MetadataMatch, RemoteArtSource
from beetsplug.lyrics import Backend

from .auth import AuthManager, TidalAuthError
from .client import DEFAULT_API_BASE, TidalAPIError, TidalClient, cover_url


class TidalV1Meta(Backend):  # type: ignore[misc]
    def fetch(self, artist: str, title: str, album: str, length: int) -> Lyrics | None:
        try:
            client = client_from_config(beets_config["tidalv1meta"])
            result = client.lyrics_for(
                artist,
                title,
                album=album,
                length=length,
                prefer_synced=_config_value("prefer_synced", True, bool),
                threshold=_config_value("match_threshold", 0.78, float),
            )
        except (TidalAuthError, TidalAPIError, requests.RequestException) as exc:
            cast(Any, self).warn("{}", exc)
            return None

        if not result:
            return None
        return Lyrics(result.text, self.__class__.name, result.url)


class TidalArtSource(RemoteArtSource):  # type: ignore[misc]
    NAME = "TIDAL"
    ID = "tidalv1meta"
    VALID_MATCHING_CRITERIA = ["default"]

    def get(self, album: Any, plugin: Any, paths: Any) -> Any:
        try:
            client = client_from_config(beets_config["tidalv1meta"])
            match = client.find_album(
                album.albumartist,
                album.album,
                threshold=_config_value("match_threshold", 0.78, float),
            )
        except (TidalAuthError, TidalAPIError, requests.RequestException) as exc:
            self._log.warning("TIDAL art source failed: {}", exc)
            return

        if not match:
            return

        size = _config_value("art_size", 1280, int)
        yield cast(Any, self)._candidate(
            url=cover_url(match.cover, size),
            match=MetadataMatch.EXACT,
            size=(size, size),
        )


def client_from_config(config: Any) -> TidalClient:
    auth = AuthManager.from_config(config)
    country_code = _config_value("country_code", "US")
    return TidalClient(
        auth,
        api_base=_config_value("api_base", DEFAULT_API_BASE),
        country_code=country_code,
        search_limit=_config_value("search_limit", 10, int),
        request_timeout=_config_value("request_timeout", 15.0, float),
    )


def register_sources() -> None:
    cast(Any, lyrics_mod.BACKEND_BY_NAME).setdefault("tidalv1meta", TidalV1Meta)
    fetchart_mod.ART_SOURCES.add(TidalArtSource)


def _config_value(key: str, default: Any, value_type: Any = None) -> Any:
    view = cast(Any, beets_config)["tidalv1meta"][key]
    try:
        value: Any = view.get(value_type) if value_type else view.get()
    except Exception:
        return default
    return default if value is None else value
