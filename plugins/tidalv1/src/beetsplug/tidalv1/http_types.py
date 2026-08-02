from __future__ import annotations

from typing import Any, Protocol


class ResponseLike(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def ok(self) -> bool: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class HTTPSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> ResponseLike: ...

    def post(self, url: str, **kwargs: Any) -> ResponseLike: ...
