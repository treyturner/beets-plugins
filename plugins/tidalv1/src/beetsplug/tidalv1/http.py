from __future__ import annotations

import atexit
import threading
import time
from http import HTTPStatus
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

REQUEST_INTERVAL = 0.25
RETRY_COUNT = 6
RETRY_BACKOFF_FACTOR = 0.5
RETRYABLE_METHODS = frozenset({"GET", "POST"})


class RetryAdapter(HTTPAdapter):
    """Retry HTTP 429 responses without retrying other failures."""

    def __init__(
        self,
        retry_count: int = RETRY_COUNT,
        backoff_factor: float = RETRY_BACKOFF_FACTOR,
    ) -> None:
        # Keep urllib3 retries disabled so each retry re-enters ``send`` and,
        # for TIDAL traffic, the pacing gate in ``_pace``.
        super().__init__(max_retries=0)
        self.retry_count = retry_count
        self.retry_backoff_factor: float = backoff_factor
        self._retry_after_parser = Retry(total=0)

    def _pace(self) -> None:
        """Wait before a wire attempt when the adapter requires pacing."""

    def _retry_delay(self, response: requests.Response, retry_index: int) -> float:
        if retry_after := response.headers.get("Retry-After"):
            try:
                return self._retry_after_parser.parse_retry_after(retry_after)
            except InvalidHeader:
                pass
        if retry_index == 0:
            return 0.0
        delay: float = self.retry_backoff_factor * (2**retry_index)
        return delay

    def send(
        self, request: requests.PreparedRequest, *args: Any, **kwargs: Any
    ) -> requests.Response:
        retry_index = 0
        while True:
            self._pace()
            response = super().send(request, *args, **kwargs)
            method = (request.method or "").upper()
            if (
                response.status_code != HTTPStatus.TOO_MANY_REQUESTS
                or method not in RETRYABLE_METHODS
                or retry_index >= self.retry_count
            ):
                return response

            delay = self._retry_delay(response, retry_index)
            response.close()
            if delay:
                time.sleep(delay)
            retry_index += 1


class RateLimitAdapter(RetryAdapter):
    """Enforce a minimum interval between every wire request and retry."""

    def __init__(self, request_interval: float = REQUEST_INTERVAL) -> None:
        super().__init__()
        self.request_interval = request_interval
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def _pace(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_time
            wait = max(0.0, self.request_interval - elapsed)
            if wait:
                time.sleep(wait)
            self._last_request_time = time.monotonic()


def create_tidal_session() -> requests.Session:
    """Create a 429-retrying session with process-wide TIDAL pacing."""
    session = requests.Session()
    adapter = RateLimitAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def create_retry_session() -> requests.Session:
    """Create a 429-retrying session without proactive request pacing."""
    session = requests.Session()
    adapter = RetryAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_tidal_session: requests.Session | None = None
_credential_discovery_session: requests.Session | None = None
_session_lock = threading.Lock()


def tidal_session() -> requests.Session:
    """Return the shared session for TIDAL API and authentication traffic."""
    global _tidal_session
    if _tidal_session is None:
        with _session_lock:
            if _tidal_session is None:
                _tidal_session = create_tidal_session()
    return _tidal_session


def credential_discovery_session() -> requests.Session:
    """Return the retry-only session for best-effort credential discovery."""
    global _credential_discovery_session
    if _credential_discovery_session is None:
        with _session_lock:
            if _credential_discovery_session is None:
                _credential_discovery_session = create_retry_session()
    return _credential_discovery_session


def close_sessions() -> None:
    """Close shared HTTP sessions during interpreter shutdown."""
    if _tidal_session is not None:
        _tidal_session.close()
    if _credential_discovery_session is not None:
        _credential_discovery_session.close()


atexit.register(close_sessions)
