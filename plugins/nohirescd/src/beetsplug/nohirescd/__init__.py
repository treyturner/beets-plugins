"""Reject and audit CD album matches for high-resolution audio."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from beets import config, ui
from beets.autotag import AlbumMatch
from beets.autotag.match import _recommendation  # pyright: ignore[reportPrivateUsage]
from beets.dbcore.query import InQuery
from beets.exceptions import UserError
from beets.importer import ImportSession, ImportTask
from beets.library import Album, Item, Library
from beets.plugins import BeetsPlugin
from beets.ui.commands import import_ as import_command
from beets.util import displayable_path

DEFAULT_MAX_BITDEPTH = 16
DEFAULT_MAX_SAMPLERATE = 44_100
DEFAULT_CD_MEDIA_PATTERN = r"(?:^|[^A-Za-z0-9])(?:HDCD|HQCD|CD(?:-R)?)(?:$|[^A-Za-z0-9])"
CSV_FIELDS = (
    "album_id",
    "mb_albumid",
    "albumartist",
    "album",
    "path",
    "track_count",
    "max_bitdepth",
    "max_samplerate",
    "media",
    "hires_tracks",
    "cd_tracks",
)


@dataclass(frozen=True)
class AlbumViolation:
    """A persisted album that violates the no-hi-res-CD rule."""

    album: Album
    items: tuple[Item, ...]
    max_bitdepth: int
    max_samplerate: int
    media: tuple[str, ...]
    cd_media: tuple[str, ...]
    hires_tracks: tuple[str, ...]
    cd_tracks: tuple[str, ...]


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

    def commands(self) -> list[Any]:
        cmd = cast(Any, ui.Subcommand)(
            "nohirescd",
            help="audit or reimport hi-res albums matched to CD releases",
        )
        cmd.parser.add_option(
            "-o",
            "--output",
            help="write a detailed album-level CSV report",
        )
        cmd.parser.add_option(
            "--reimport",
            action="store_true",
            default=False,
            help="reimport violating albums instead of reporting them",
        )
        cmd.func = self._run_command
        return [cmd]

    def _is_hires_item(self, item: Item) -> bool:
        max_bitdepth = self.config["max_bitdepth"].get(int)
        max_samplerate = self.config["max_samplerate"].get(int)
        return int(item.bitdepth or 0) > max_bitdepth or int(item.samplerate or 0) > max_samplerate

    def _is_hires(self, items: Sequence[Item]) -> bool:
        return any(self._is_hires_item(item) for item in items)

    def _is_cd_media(self, media: object | None) -> bool:
        pattern = re.compile(
            self.config["cd_media_pattern"].as_str(),
            re.IGNORECASE,
        )
        return media is not None and pattern.search(str(media)) is not None

    def _is_cd_candidate(self, match: AlbumMatch) -> bool:
        media_values = [match.info.media]
        media_values.extend(track.media for track in match.mapping.values())
        return any(self._is_cd_media(value) for value in media_values)

    def _find_violations(
        self,
        lib: Library,
        query: Sequence[str] | None,
    ) -> list[AlbumViolation]:
        violations: list[AlbumViolation] = []
        for album in lib.albums(query):
            items = tuple(album.items())
            if not self._is_hires(items) or not any(
                self._is_cd_media(item.media) for item in items
            ):
                continue

            media = self._distinct_media(items)
            cd_media = tuple(value for value in media if self._is_cd_media(value))
            violations.append(
                AlbumViolation(
                    album=album,
                    items=items,
                    max_bitdepth=max(int(item.bitdepth or 0) for item in items),
                    max_samplerate=max(int(item.samplerate or 0) for item in items),
                    media=media,
                    cd_media=cd_media,
                    hires_tracks=tuple(
                        self._hires_track_detail(item)
                        for item in items
                        if self._is_hires_item(item)
                    ),
                    cd_tracks=tuple(
                        self._cd_track_detail(item)
                        for item in items
                        if self._is_cd_media(item.media)
                    ),
                )
            )
        return violations

    @staticmethod
    def _distinct_media(items: Sequence[Item]) -> tuple[str, ...]:
        values = {str(item.media) for item in items if item.media}
        return tuple(sorted(values, key=str.casefold))

    @staticmethod
    def _track_label(item: Item) -> str:
        position = ".".join(str(value) for value in (item.disc, item.track) if value)
        title = str(item.title or "")
        label = " ".join(value for value in (position, title) if value)
        return label or f"item {item.id}"

    def _hires_track_detail(self, item: Item) -> str:
        resolution = self._format_resolution(
            int(item.bitdepth or 0),
            int(item.samplerate or 0),
        )
        return f"{self._track_label(item)} ({resolution})"

    def _cd_track_detail(self, item: Item) -> str:
        return f"{self._track_label(item)} ({item.media})"

    @staticmethod
    def _format_resolution(bitdepth: int, samplerate: int) -> str:
        values: list[str] = []
        if bitdepth:
            values.append(f"{bitdepth}-bit")
        if samplerate:
            values.append(f"{samplerate} Hz")
        return "/".join(values)

    def _run_command(self, lib: Library, opts: Any, args: list[str]) -> None:
        if opts.reimport and opts.output:
            raise UserError("--reimport and --output cannot be used together")

        violations = self._find_violations(lib, args or None)
        if opts.reimport:
            self._reimport(lib, violations)
            return

        self._print_report(violations)
        if opts.output:
            self._write_csv(opts.output, violations)
            ui.print_(f"Wrote {len(violations)} album row(s) to {displayable_path(opts.output)}.")

    def _print_report(self, violations: Sequence[AlbumViolation]) -> None:
        if not violations:
            ui.print_("No nohirescd violations found.")
            return

        for violation in violations:
            album = violation.album
            artist = str(album.albumartist or "Unknown Artist")
            title = str(album.album or "Unknown Album")
            resolution = self._format_resolution(
                violation.max_bitdepth,
                violation.max_samplerate,
            )
            ui.print_(
                f"{artist} — {title} [album {album.id}] — {resolution} — "
                f"{', '.join(violation.cd_media)}"
            )

        item_count = sum(len(violation.items) for violation in violations)
        ui.print_(f"{len(violations)} violating album(s), {item_count} track(s).")

    def _csv_row(self, violation: AlbumViolation) -> dict[str, object]:
        album = violation.album
        return {
            "album_id": album.id,
            "mb_albumid": album.mb_albumid,
            "albumartist": album.albumartist,
            "album": album.album,
            "path": displayable_path(album.item_dir()),
            "track_count": len(violation.items),
            "max_bitdepth": violation.max_bitdepth or "",
            "max_samplerate": violation.max_samplerate or "",
            "media": "; ".join(violation.media),
            "hires_tracks": "; ".join(violation.hires_tracks),
            "cd_tracks": "; ".join(violation.cd_tracks),
        }

    def _write_csv(
        self,
        output: str,
        violations: Sequence[AlbumViolation],
    ) -> None:
        try:
            with open(output, "w", encoding="utf-8", newline="") as output_file:
                fieldnames: list[str] = list(CSV_FIELDS)
                writer = csv.DictWriter(
                    output_file,
                    fieldnames=fieldnames,
                    dialect="excel",
                    delimiter=",",
                )
                writer.writeheader()
                writer.writerows(self._csv_row(violation) for violation in violations)
        except (OSError, csv.Error) as exc:
            raise UserError(
                f"Could not write nohirescd CSV to {displayable_path(output)}: {exc}"
            ) from exc

    @staticmethod
    def _reimport(
        lib: Library,
        violations: Sequence[AlbumViolation],
    ) -> None:
        album_ids = [
            violation.album.id for violation in violations if violation.album.id is not None
        ]
        if not album_ids:
            ui.print_("No nohirescd violations found; nothing to reimport.")
            return

        if not config["import"]["autotag"].get(bool):
            raise UserError("--reimport requires import.autotag to be enabled")

        ui.print_(f"Reimporting {len(album_ids)} violating album(s).")
        singletons = config["import"]["singletons"]
        configured_singletons = singletons.get(bool)
        singletons.set(False)
        try:
            cast(Any, import_command).import_files(
                lib,
                [],
                InQuery("id", album_ids),
            )
        finally:
            singletons.set(configured_singletons)

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
