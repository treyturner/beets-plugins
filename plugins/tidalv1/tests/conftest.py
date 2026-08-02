from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload if self.payload is not None else {}

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(
        self,
        *,
        get: list[FakeResponse] | None = None,
        post: list[FakeResponse] | None = None,
    ) -> None:
        self.get_responses = list(get or [])
        self.post_responses = list(post or [])
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        if not self.get_responses:
            raise AssertionError(f"unexpected GET {url}")
        return self.get_responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        if not self.post_responses:
            raise AssertionError(f"unexpected POST {url}")
        return self.post_responses.pop(0)


@pytest.fixture
def search_payload() -> dict[str, Any]:
    return {
        "tracks": {
            "items": [
                {
                    "id": 1550549,
                    "title": "Harder, Better, Faster, Stronger",
                    "duration": 224,
                    "artist": {"name": "Daft Punk"},
                    "album": {"title": "Discovery"},
                },
                {
                    "id": 1,
                    "title": "Something Else",
                    "duration": 180,
                    "artist": {"name": "Other Artist"},
                    "album": {"title": "Other Album"},
                },
            ]
        }
    }


@pytest.fixture
def album_search_payload() -> dict[str, Any]:
    return {
        "albums": {
            "items": [
                {
                    "id": 123,
                    "title": "Discovery",
                    "cover": "aabbccdd-eeff-0011-2233-445566778899",
                    "artist": {"name": "Daft Punk"},
                },
                {
                    "id": 456,
                    "title": "Homework",
                    "cover": "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb",
                    "artist": {"name": "Daft Punk"},
                },
            ]
        }
    }
