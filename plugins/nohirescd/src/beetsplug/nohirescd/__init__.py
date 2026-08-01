"""Reject CD album matches for high-resolution source audio."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import cast

from beets.autotag import AlbumMatch
from beets.autotag.match import _recommendation  # pyright: ignore[reportPrivateUsage]
from beets.importer import ImportSession, ImportTask
from beets.library import Item
from beets.plugins import BeetsPlugin

DEFAULT_MAX_BITDEPTH = 16
DEFAULT_MAX_SAMPLERATE = 44_100
DEFAULT_CD_MEDIA_PATTERN = r"(?:^|[^A-Za-z0-9])CD(?:-R)?(?:$|[^A-Za-z0-9])"


class NoHiResCdPlugin(BeetsPlugin):
    """Prevent high-resolution source audio from matching a CD release."""

    def __init__(self) -> None:
        super().__init__()
        self.config.add(
            {
                "max_bitdepth": DEFAULT_MAX_BITDEPTH,
                "max_samplerate": DEFAULT_MAX_SAMPLERATE,
                "cd_media_pattern": DEFAULT_CD_MEDIA_PATTERN,
            }
        )
        self.register_listener(
            "import_task_before_choice",
            self._filter_candidates,
        )
        self.register_listener(
            "before_choose_candidate",
            self._filter_candidates,
        )

    def _is_hires(self, items: Sequence[Item]) -> bool:
        max_bitdepth = self.config["max_bitdepth"].get(int)
        max_samplerate = self.config["max_samplerate"].get(int)

        return any(
            int(item.bitdepth or 0) > max_bitdepth or int(item.samplerate or 0) > max_samplerate
            for item in items
        )

    def _is_cd_candidate(self, match: AlbumMatch) -> bool:
        pattern = re.compile(
            self.config["cd_media_pattern"].as_str(),
            re.IGNORECASE,
        )
        media_values = [match.info.media]
        media_values.extend(track.media for track in match.mapping.values())

        return any(
            value is not None and pattern.search(str(value)) is not None for value in media_values
        )

    def _filter_candidates(
        self,
        task: ImportTask,
        session: ImportSession,
    ) -> None:
        if not task.is_album or not task.candidates or not self._is_hires(task.items):
            return

        original_candidates = cast(Sequence[AlbumMatch], task.candidates)
        task.candidates = [
            candidate for candidate in original_candidates if not self._is_cd_candidate(candidate)
        ]

        removed = len(original_candidates) - len(task.candidates)
        if not removed:
            return

        task.rec = _recommendation(task.candidates)

        max_bitdepth = max(int(item.bitdepth or 0) for item in task.items)
        max_samplerate = max(int(item.samplerate or 0) for item in task.items)
        self._log.warning(
            "Rejected {} CD candidate(s) for hi-res input ({}-bit/{} Hz).",
            removed,
            max_bitdepth,
            max_samplerate,
        )
