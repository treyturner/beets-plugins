from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, cast

import requests

from .auth import AuthManager
from .http_types import HTTPSession, ResponseLike

DEFAULT_API_BASE = "https://api.tidal.com/v1"
LISTEN_BASE = "https://listen.tidal.com"


class TidalAPIError(RuntimeError):
    """Raised for unexpected TIDAL API responses."""


@dataclass(frozen=True)
class TrackMatch:
    id: int
    title: str
    artist: str
    album: str | None
    duration: float | None
    score: float

    @property
    def url(self) -> str:
        return f"{LISTEN_BASE}/track/{self.id}"


@dataclass(frozen=True)
class AlbumMatch:
    id: int
    title: str
    artist: str
    cover: str
    score: float

    @property
    def url(self) -> str:
        return f"{LISTEN_BASE}/album/{self.id}"


@dataclass(frozen=True)
class LyricsResult:
    text: str
    provider: str | None
    track: TrackMatch
    synced: bool

    @property
    def url(self) -> str:
        return self.track.url


class TidalClient:
    def __init__(
        self,
        auth: AuthManager,
        *,
        api_base: str = DEFAULT_API_BASE,
        country_code: str = "US",
        search_limit: int = 10,
        request_timeout: float = 15.0,
        session: HTTPSession | None = None,
    ) -> None:
        self.auth = auth
        self.api_base = api_base.rstrip("/")
        self.country_code = country_code
        self.search_limit = search_limit
        self.request_timeout = request_timeout
        self.session: HTTPSession = session or cast(HTTPSession, requests.Session())

    def search_tracks(self, query: str) -> list[dict[str, Any]]:
        payload = self._request(
            "search",
            params={"query": query, "limit": self.search_limit},
            require_user=False,
        )
        return _items(payload, "tracks")

    def search_albums(self, query: str) -> list[dict[str, Any]]:
        payload = self._request(
            "search",
            params={"query": query, "limit": self.search_limit},
            require_user=False,
        )
        return _items(payload, "albums")

    def get_track_lyrics(self, track_id: int) -> dict[str, Any]:
        return self._request(f"tracks/{track_id}/lyrics", require_user=True)

    def lyrics_for(
        self,
        artist: str,
        title: str,
        *,
        album: str | None = None,
        length: float | None = None,
        prefer_synced: bool = True,
        threshold: float = 0.78,
    ) -> LyricsResult | None:
        track = self.find_track(artist, title, album=album, length=length, threshold=threshold)
        if not track:
            return None

        payload = self.get_track_lyrics(track.id)
        subtitles = (payload.get("subtitles") or "").strip()
        plain = (payload.get("lyrics") or "").strip()
        text = subtitles if prefer_synced and subtitles else plain or subtitles
        if not text:
            return None

        return LyricsResult(
            text=text,
            provider=payload.get("lyricsProvider"),
            track=track,
            synced=bool(subtitles and text == subtitles),
        )

    def find_track(
        self,
        artist: str,
        title: str,
        *,
        album: str | None = None,
        length: float | None = None,
        threshold: float = 0.78,
    ) -> TrackMatch | None:
        query = " ".join(part for part in (artist, title) if part)
        matches: list[TrackMatch] = []
        for item in self.search_tracks(query):
            match = _track_match(item, artist=artist, title=title, album=album, length=length)
            if match is not None:
                matches.append(match)
        best = max(matches, key=lambda match: match.score, default=None)
        return best if best and best.score >= threshold else None

    def find_album(
        self,
        artist: str,
        album: str,
        *,
        threshold: float = 0.78,
    ) -> AlbumMatch | None:
        query = " ".join(part for part in (artist, album) if part)
        matches: list[AlbumMatch] = []
        for item in self.search_albums(query):
            match = _album_match(item, artist=artist, album=album)
            if match is not None and match.cover:
                matches.append(match)
        best = max(matches, key=lambda match: match.score, default=None)
        return best if best and best.score >= threshold else None

    def legacy_username_login(
        self,
        *,
        username: str,
        password: str,
        client_token: str,
        client_version: str = "2.38.0",
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base}/login/username",
            data={
                "username": username,
                "password": password,
                "token": client_token,
                "clientVersion": client_version,
            },
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return response_json_object(response)

    def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        require_user: bool,
    ) -> dict[str, Any]:
        token = self.auth.get_token(require_user=require_user)
        request_params = {"countryCode": token.country_code or self.country_code}
        request_params.update(params or {})
        response = self.session.get(
            f"{self.api_base}/{endpoint.lstrip('/')}",
            params=request_params,
            headers={
                "Authorization": f"{token.token_type} {token.access_token}",
                "Accept": "application/json",
            },
            timeout=self.request_timeout,
        )
        if response.status_code == 404:
            return {}
        if not response.ok:
            raise TidalAPIError(_format_error(response))
        payload = response.json()
        if not isinstance(payload, dict):
            raise TidalAPIError("TIDAL returned an unexpected non-object JSON payload")
        return cast(dict[str, Any], payload)


def cover_url(cover_id: str, size: int = 1280) -> str:
    safe_size = min(max(int(size), 80), 1280)
    return f"https://resources.tidal.com/images/{cover_id.replace('-', '/')}/{safe_size}x{safe_size}.jpg"


def _items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    section_obj = payload.get(key)
    if not isinstance(section_obj, dict):
        return []
    section = cast(dict[str, Any], section_obj)
    items_obj = section.get("items")
    if not isinstance(items_obj, list):
        return []
    items = cast(list[object], items_obj)
    matches: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            matches.append(cast(dict[str, Any], item))
    return matches


def _track_match(
    item: dict[str, Any],
    *,
    artist: str,
    title: str,
    album: str | None,
    length: float | None,
) -> TrackMatch | None:
    track_id = item.get("id")
    item_title = item.get("title") or ""
    if not track_id or not item_title:
        return None

    item_artist = _artist_name(item)
    item_album = _album_title(item)
    item_duration = _duration(item)
    score = (
        0.55 * similarity(title, item_title)
        + 0.25 * similarity(artist, item_artist)
        + 0.10 * (similarity(album, item_album) if album and item_album else 0.5)
        + 0.10 * duration_similarity(length, item_duration)
    )
    return TrackMatch(
        id=int(track_id),
        title=item_title,
        artist=item_artist,
        album=item_album,
        duration=item_duration,
        score=score,
    )


def _album_match(item: dict[str, Any], *, artist: str, album: str) -> AlbumMatch | None:
    album_id = item.get("id")
    title = item.get("title") or ""
    cover = item.get("cover") or ""
    if not album_id or not title or not cover:
        return None

    item_artist = _artist_name(item)
    score = 0.65 * similarity(album, title) + 0.35 * similarity(artist, item_artist)
    return AlbumMatch(id=int(album_id), title=title, artist=item_artist, cover=cover, score=score)


def _artist_name(item: dict[str, Any]) -> str:
    artist_obj = item.get("artist")
    if isinstance(artist_obj, dict):
        artist = cast(dict[str, Any], artist_obj)
        if artist.get("name"):
            return str(artist["name"])
    artists_obj = item.get("artists")
    if isinstance(artists_obj, list):
        names: list[str] = []
        for entry_obj in cast(list[object], artists_obj):
            if isinstance(entry_obj, dict):
                entry = cast(dict[str, Any], entry_obj)
                if entry.get("name"):
                    names.append(str(entry["name"]))
        if names:
            return ", ".join(names)
    return ""


def _album_title(item: dict[str, Any]) -> str | None:
    album_obj = item.get("album")
    if isinstance(album_obj, dict):
        album = cast(dict[str, Any], album_obj)
        if album.get("title"):
            return str(album["title"])
    return None


def _duration(item: dict[str, Any]) -> float | None:
    duration = item.get("duration")
    try:
        return float(duration) if duration is not None else None
    except (TypeError, ValueError):
        return None


def similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(a=left_norm, b=right_norm).ratio()


def duration_similarity(left: float | None, right: float | None) -> float:
    if not left or not right:
        return 0.5
    diff = abs(float(left) - float(right))
    if diff <= 2:
        return 1.0
    return max(0.0, 1.0 - diff / max(float(left), float(right), 1.0))


def normalize(value: str | None) -> str:
    value = (value or "").casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(feat|featuring|ft)\b.*", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _format_error(response: ResponseLike) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"TIDAL API request failed with HTTP {response.status_code}"
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, Any], payload)
        detail = optional_str(
            payload_dict.get("userMessage")
            or payload_dict.get("description")
            or payload_dict.get("error")
        )
        if detail:
            return f"TIDAL API request failed with HTTP {response.status_code}: {detail}"
    return f"TIDAL API request failed with HTTP {response.status_code}"


def response_json_object(response: ResponseLike) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise TidalAPIError("TIDAL returned an unexpected non-object JSON payload")
    return cast(dict[str, Any], payload)


def optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
