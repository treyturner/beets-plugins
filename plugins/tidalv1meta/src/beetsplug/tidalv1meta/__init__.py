from __future__ import annotations

import time
from typing import Any, cast
import webbrowser

from beets import ui
from beets.plugins import BeetsPlugin

from .auth import (
    DEFAULT_AUTH_BASE,
    AuthManager,
    DEFAULT_AUTH_CACHE_FILENAME,
)
from .client import DEFAULT_API_BASE
from .sources import register_sources

__version__ = "0.1.0"

DEFAULT_CONFIG: dict[str, str | int | float | bool | None] = {
    "api_base": DEFAULT_API_BASE,
    "auth_base": DEFAULT_AUTH_BASE,
    "v1_client_id": None,
    "v1_client_secret": None,
    "v1_client_id_secret_b64": None,
    "access_token": None,
    "refresh_token": None,
    "token_expires_at": None,
    "country_code": "US",
    "auth_cache": DEFAULT_AUTH_CACHE_FILENAME,
    "request_timeout": 15.0,
    "search_limit": 10,
    "match_threshold": 0.78,
    "prefer_synced": True,
    "art_size": 1280,
}

register_sources()


class TidalV1MetaPlugin(BeetsPlugin):
    def __init__(self) -> None:
        super().__init__()
        self.config.add(DEFAULT_CONFIG)
        for key in (
            "v1_client_id",
            "v1_client_secret",
            "v1_client_id_secret_b64",
            "access_token",
            "refresh_token",
        ):
            self.config[key].redact = True
        register_sources()

    def commands(self) -> list[Any]:
        cmd = cast(Any, ui.Subcommand)("tidalv1-auth", help="authorize TIDAL for tidalv1meta")
        cmd.parser.add_option(
            "--open",
            action="store_true",
            default=False,
            help="open the authorization URL in a browser",
        )

        def func(lib: Any, opts: Any, args: Any) -> None:
            manager = AuthManager.from_config(self.config)
            device = manager.start_device_authorization()
            url = device.verification_uri_complete or device.verification_uri
            ui.print_("OAuth login started; waiting for a response.")
            ui.print_("Open this TIDAL authorization URL:", url)
            ui.print_(f"If not auto-filled, use code: {device.user_code}")
            if opts.open:
                webbrowser.open(url)

            token = manager.poll_device_authorization(device, sleep=time.sleep)
            manager.save_token(token)
            ui.print_(f"TIDAL authorization saved to {manager.cache_path}")

        cmd.func = func
        return [cmd]
