from __future__ import annotations

import base64
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import requests
from requests.adapters import HTTPAdapter

import beetsplug.tidalv1.auth as auth_module
import beetsplug.tidalv1.http as http_module
from beetsplug.tidalv1.auth import AuthManager
from beetsplug.tidalv1.client import TidalClient
from beetsplug.tidalv1.http import (
    RETRY_BACKOFF_FACTOR,
    RETRY_COUNT,
    RETRYABLE_METHODS,
    RateLimitAdapter,
    RetryAdapter,
    create_retry_session,
    credential_discovery_session,
    tidal_session,
)


@dataclass
class ResponseSpec:
    status: int
    body: str = "{}"
    headers: dict[str, str] = field(default_factory=dict)


@contextmanager
def response_server(
    responses: list[ResponseSpec],
) -> Iterator[tuple[str, list[str]]]:
    pending = deque(responses)
    methods: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._respond()

        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length:
                self.rfile.read(content_length)
            self._respond()

        def _respond(self) -> None:
            methods.append(self.command)
            spec = pending.popleft()
            body = spec.body.encode()
            self.send_response(spec.status)
            for key, value in spec.headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/resource", methods
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_retry_adapter_only_retries_get_and_post_429_responses():
    adapter = RetryAdapter()

    assert adapter.retry_count == RETRY_COUNT
    assert adapter.retry_backoff_factor == RETRY_BACKOFF_FACTOR
    assert RETRYABLE_METHODS == {"GET", "POST"}
    assert adapter.max_retries.total == 0


def test_retry_session_honors_numeric_retry_after(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr(http_module.time, "sleep", sleeps.append)
    session = create_retry_session()

    with response_server(
        [
            ResponseSpec(429, headers={"Retry-After": "3"}),
            ResponseSpec(200),
        ]
    ) as (url, methods):
        response = session.get(url)

    session.close()
    assert response.status_code == 200
    assert methods == ["GET", "GET"]
    assert sleeps == [3]


def test_retry_session_uses_exponential_backoff_for_post(
    monkeypatch: pytest.MonkeyPatch,
):
    sleeps: list[float] = []
    monkeypatch.setattr(http_module.time, "sleep", sleeps.append)
    session = create_retry_session()

    with response_server([ResponseSpec(429), ResponseSpec(429), ResponseSpec(200)]) as (
        url,
        methods,
    ):
        response = session.post(url, data={"grant_type": "client_credentials"})

    session.close()
    assert response.status_code == 200
    assert methods == ["POST", "POST", "POST"]
    assert sleeps == [1.0]


@pytest.mark.parametrize("retry_after", ["0.5", "not-a-date"])
def test_retry_session_uses_exponential_backoff_for_invalid_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str,
):
    sleeps: list[float] = []
    monkeypatch.setattr(http_module.time, "sleep", sleeps.append)
    session = create_retry_session()

    with response_server(
        [
            ResponseSpec(429, headers={"Retry-After": retry_after}),
            ResponseSpec(429, headers={"Retry-After": retry_after}),
            ResponseSpec(200),
        ]
    ) as (url, methods):
        response = session.get(url)

    session.close()
    assert response.status_code == 200
    assert methods == ["GET", "GET", "GET"]
    assert sleeps == [1.0]


def test_retry_session_returns_final_429_after_six_retries(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
    session = create_retry_session()

    with response_server([ResponseSpec(429) for _ in range(RETRY_COUNT + 1)]) as (
        url,
        methods,
    ):
        response = session.get(url)

    session.close()
    assert response.status_code == 429
    assert methods == ["GET"] * (RETRY_COUNT + 1)


def test_retry_session_does_not_retry_other_http_errors():
    session = create_retry_session()

    with response_server([ResponseSpec(503, headers={"Retry-After": "1"}), ResponseSpec(200)]) as (
        url,
        methods,
    ):
        response = session.get(url)

    session.close()
    assert response.status_code == 503
    assert methods == ["GET"]


def test_tidal_session_paces_consecutive_requests(monkeypatch: pytest.MonkeyPatch):
    monotonic_values = iter([10.0, 10.0, 10.1, 10.25])
    sleeps: list[float] = []
    monkeypatch.setattr(http_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(http_module.time, "sleep", sleeps.append)
    sent: list[requests.PreparedRequest] = []

    def send(
        self: HTTPAdapter,
        request: requests.PreparedRequest,
        *args: Any,
        **kwargs: Any,
    ) -> requests.Response:
        sent.append(request)
        return requests.Response()

    monkeypatch.setattr(HTTPAdapter, "send", send)
    adapter = RateLimitAdapter()
    request = requests.Request("GET", "https://api.tidal.com/v1/search").prepare()

    adapter.send(request)
    adapter.send(request)

    assert sent == [request, request]
    assert sleeps == [pytest.approx(0.15)]


def test_tidal_session_paces_every_retry(monkeypatch: pytest.MonkeyPatch):
    now = 10.0
    sleeps: list[float] = []
    responses = deque(
        [
            ResponseSpec(429),
            ResponseSpec(429),
            ResponseSpec(200),
        ]
    )
    sent: list[requests.PreparedRequest] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    def send(
        self: HTTPAdapter,
        request: requests.PreparedRequest,
        *args: Any,
        **kwargs: Any,
    ) -> requests.Response:
        sent.append(request)
        spec = responses.popleft()
        response = requests.Response()
        response.status_code = spec.status
        response.request = request
        response._content = b""
        response._content_consumed = True
        return response

    monkeypatch.setattr(http_module.time, "monotonic", monotonic)
    monkeypatch.setattr(http_module.time, "sleep", sleep)
    monkeypatch.setattr(HTTPAdapter, "send", send)
    adapter = RateLimitAdapter()
    request = requests.Request("POST", "https://auth.tidal.com/v1/oauth2/token").prepare()

    response = adapter.send(request)

    assert response.status_code == 200
    assert sent == [request, request, request]
    assert sleeps == [pytest.approx(0.25), 1.0]


def test_auth_and_client_share_process_wide_tidal_session():
    first_manager = AuthManager(v1_client_id="id", v1_client_secret="secret")
    second_manager = AuthManager(v1_client_id="id", v1_client_secret="secret")
    client = TidalClient(first_manager)

    assert first_manager.session is tidal_session()
    assert second_manager.session is first_manager.session
    assert client.session is first_manager.session
    assert isinstance(tidal_session().get_adapter("https://api.tidal.com"), RateLimitAdapter)


def test_credential_discovery_session_retries_without_rate_limiting():
    session = credential_discovery_session()
    adapter = session.get_adapter("https://raw.githubusercontent.com")

    assert session is credential_discovery_session()
    assert isinstance(adapter, RetryAdapter)
    assert not isinstance(adapter, RateLimitAdapter)
    assert adapter.retry_count == RETRY_COUNT


def test_credential_discovery_recovers_from_429(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_module, "_discovered_app_credentials", None)
    monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
    encoded_pair = base64.b64encode(b"discovered-id;discovered-secret").decode()
    session = create_retry_session()

    with response_server(
        [ResponseSpec(429), ResponseSpec(200, body=f'b64decode("{encoded_pair}")')]
    ) as (url, methods):
        original_get = session.get
        monkeypatch.setattr(session, "get", lambda _url, **kwargs: original_get(url, **kwargs))
        credentials = auth_module._discover_app_credentials(session, 1.0)

    session.close()
    assert credentials == ("discovered-id", "discovered-secret")
    assert methods == ["GET", "GET"]
