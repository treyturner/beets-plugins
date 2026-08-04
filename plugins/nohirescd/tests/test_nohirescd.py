from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from beets import ui
from beets.autotag import AlbumInfo, AlbumMatch, Recommendation, TrackInfo
from beets.autotag.distance import Distance
from beets.importer import ImportTask
from beets.library import Album, Item, Library

from beetsplug.nohirescd import CSV_FIELDS, NoHiResCdPlugin


def source_item(bitdepth: int | None, samplerate: int | None) -> SimpleNamespace:
    return SimpleNamespace(bitdepth=bitdepth, samplerate=samplerate)


def candidate(
    album_media: str | None,
    *track_media: str | None,
) -> SimpleNamespace:
    mapping = {object(): SimpleNamespace(media=medium) for medium in track_media}
    return SimpleNamespace(
        info=SimpleNamespace(media=album_media),
        mapping=mapping,
        distance=Distance(),
    )


def import_task(
    *,
    items: list[SimpleNamespace],
    candidates: list[SimpleNamespace],
    is_album: bool = True,
    recommendation: Recommendation = Recommendation.none,
) -> SimpleNamespace:
    return SimpleNamespace(
        is_album=is_album,
        items=items,
        candidates=candidates,
        rec=recommendation,
    )


def library_item(
    directory: Path,
    *,
    album: str,
    albumartist: str = "Artist",
    mb_albumid: str = "release-id",
    title: str = "Track",
    disc: int = 1,
    track: int = 1,
    media: str | None = "CD",
    bitdepth: int | None = 16,
    samplerate: int | None = 44_100,
) -> Item:
    return Item(
        path=directory / f"{disc:02d}-{track:02d}-{title}.flac",
        album=album,
        albumartist=albumartist,
        mb_albumid=mb_albumid,
        title=title,
        disc=disc,
        track=track,
        media=media,
        bitdepth=bitdepth,
        samplerate=samplerate,
    )


def add_library_album(
    lib: Library,
    directory: Path,
    *,
    album: str,
    albumartist: str = "Artist",
    mb_albumid: str = "release-id",
    items: list[dict[str, object]] | None = None,
) -> Album:
    track_values = items or [{}]
    return lib.add_album(
        [
            library_item(
                directory,
                album=album,
                albumartist=albumartist,
                mb_albumid=mb_albumid,
                track=index,
                **values,
            )
            for index, values in enumerate(track_values, start=1)
        ]
    )


@pytest.fixture
def plugin() -> NoHiResCdPlugin:
    instance = NoHiResCdPlugin()
    instance.config["max_bitdepth"].set(16)
    instance.config["max_samplerate"].set(44_100)
    instance.config["cd_media_pattern"].set(r"(?:^|[^A-Za-z0-9])CD(?:-R)?(?:$|[^A-Za-z0-9])")
    instance._log = Mock()
    return instance


@pytest.fixture
def library(tmp_path: Path) -> Iterator[Library]:
    instance = Library(
        tmp_path / "library.db",
        directory=str(tmp_path / "music"),
    )
    yield instance
    instance._close()


def test_registers_both_candidate_filter_events(
    plugin: NoHiResCdPlugin,
) -> None:
    assert plugin._filter_candidates in plugin._raw_listeners["import_task_before_choice"]
    assert plugin._filter_candidates in plugin._raw_listeners["before_choose_candidate"]


def test_registers_audit_command(plugin: NoHiResCdPlugin) -> None:
    command = plugin.commands()[0]

    assert command.name == "nohirescd"
    opts, args = command.parse_args(["--output", "audit.csv", "artist:Test"])
    assert opts.output == "audit.csv"
    assert opts.reimport is False
    assert args == ["artist:Test"]


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([source_item(16, 44_100)], False),
        ([source_item(None, None)], False),
        ([source_item(24, 44_100)], True),
        ([source_item(16, 96_000)], True),
        ([source_item(16, 44_100), source_item(24, 44_100)], True),
    ],
)
def test_hires_when_any_item_exceeds_a_limit(
    plugin: NoHiResCdPlugin,
    items: list[SimpleNamespace],
    expected: bool,
) -> None:
    assert plugin._is_hires(items) is expected


def test_hires_limits_are_configurable(plugin: NoHiResCdPlugin) -> None:
    plugin.config["max_bitdepth"].set(24)
    plugin.config["max_samplerate"].set(96_000)

    assert not plugin._is_hires([source_item(24, 96_000)])
    assert plugin._is_hires([source_item(32, 96_000)])


@pytest.mark.parametrize(
    "media",
    ["CD", "Enhanced CD", "8cm CD", "SHM-CD", "CD-R", "CD + DVD"],
)
def test_recognizes_cd_album_media(
    plugin: NoHiResCdPlugin,
    media: str,
) -> None:
    assert plugin._is_cd_candidate(candidate(media))


@pytest.mark.parametrize(
    "media",
    [None, "Media", "Digital Media", "Vinyl", "SACD", "CDDA"],
)
def test_does_not_misclassify_non_cd_media(
    plugin: NoHiResCdPlugin,
    media: str | None,
) -> None:
    assert not plugin._is_cd_candidate(candidate(media))


def test_checks_mapped_track_media_for_mixed_releases(
    plugin: NoHiResCdPlugin,
) -> None:
    match = candidate("Media", "Vinyl", "CD")

    assert plugin._is_cd_candidate(match)


def test_filters_a_real_beets_mixed_media_album_match(
    plugin: NoHiResCdPlugin,
) -> None:
    item = Item(title="Track", bitdepth=24, samplerate=96_000)
    track = TrackInfo(title="Track", media="CD")
    album = AlbumInfo(
        tracks=[track],
        album="Album",
        artist="Artist",
        media="Media",
    )
    match = AlbumMatch(Distance(), album, {item: track})
    task = ImportTask(None, None, [item])
    task.candidates = [match]
    task.rec = Recommendation.strong

    plugin._filter_candidates(task, Mock())

    assert task.candidates == []
    assert task.rec is Recommendation.none


def test_cd_pattern_is_configurable(plugin: NoHiResCdPlugin) -> None:
    plugin.config["cd_media_pattern"].set(r"^Compact Disc$")

    assert plugin._is_cd_candidate(candidate("Compact Disc"))
    assert not plugin._is_cd_candidate(candidate("CD"))


def test_filters_cd_candidates_and_recalculates_recommendation(
    plugin: NoHiResCdPlugin,
) -> None:
    cd_match = candidate("CD")
    digital_match = candidate("Digital Media")
    task = import_task(
        items=[source_item(24, 96_000)],
        candidates=[cd_match, digital_match],
    )

    plugin._filter_candidates(task, Mock())

    assert task.candidates == [digital_match]
    assert task.rec is Recommendation.strong
    plugin._log.warning.assert_called_once_with(
        "Rejected {} CD candidate(s) for hi-res input ({}-bit/{} Hz).",
        1,
        24,
        96_000,
    )


def test_recommendation_becomes_none_when_all_candidates_are_removed(
    plugin: NoHiResCdPlugin,
) -> None:
    task = import_task(
        items=[source_item(24, 48_000)],
        candidates=[candidate("CD"), candidate("SHM-CD")],
        recommendation=Recommendation.strong,
    )

    plugin._filter_candidates(task, Mock())

    assert task.candidates == []
    assert task.rec is Recommendation.none


def test_preserves_recommendation_when_no_candidate_is_removed(
    plugin: NoHiResCdPlugin,
) -> None:
    digital_match = candidate("Digital Media")
    task = import_task(
        items=[source_item(24, 96_000)],
        candidates=[digital_match],
        recommendation=Recommendation.medium,
    )

    plugin._filter_candidates(task, Mock())

    assert task.candidates == [digital_match]
    assert task.rec is Recommendation.medium
    plugin._log.warning.assert_not_called()


@pytest.mark.parametrize(
    "task",
    [
        import_task(
            items=[source_item(24, 96_000)],
            candidates=[candidate("CD")],
            is_album=False,
            recommendation=Recommendation.strong,
        ),
        import_task(
            items=[source_item(16, 44_100)],
            candidates=[candidate("CD")],
            recommendation=Recommendation.strong,
        ),
        import_task(
            items=[source_item(24, 96_000)],
            candidates=[],
            recommendation=Recommendation.none,
        ),
    ],
)
def test_leaves_inapplicable_tasks_unchanged(
    plugin: NoHiResCdPlugin,
    task: SimpleNamespace,
) -> None:
    original_candidates = list(task.candidates)
    original_recommendation = task.rec

    plugin._filter_candidates(task, Mock())

    assert task.candidates == original_candidates
    assert task.rec is original_recommendation
    plugin._log.warning.assert_not_called()


def test_audit_finds_cross_track_mixed_media_violation(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
) -> None:
    album = add_library_album(
        library,
        tmp_path / "Mixed Album",
        album="Mixed Album",
        items=[
            {
                "title": "Hi-Res Vinyl Track",
                "media": "Vinyl",
                "bitdepth": 24,
                "samplerate": 96_000,
            },
            {
                "title": "CD Track",
                "media": "CD",
                "bitdepth": 16,
                "samplerate": 44_100,
            },
        ],
    )

    violations = plugin._find_violations(library, None)

    assert len(violations) == 1
    violation = violations[0]
    assert violation.album.id == album.id
    assert violation.max_bitdepth == 24
    assert violation.max_samplerate == 96_000
    assert violation.media == ("CD", "Vinyl")
    assert violation.cd_media == ("CD",)
    assert violation.hires_tracks == ("1.1 Hi-Res Vinyl Track (24-bit/96000 Hz)",)
    assert violation.cd_tracks == ("1.2 CD Track (CD)",)


def test_audit_excludes_nonviolations_and_singletons(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
) -> None:
    add_library_album(
        library,
        tmp_path / "Standard CD",
        album="Standard CD",
    )
    add_library_album(
        library,
        tmp_path / "Hi-Res Digital",
        album="Hi-Res Digital",
        items=[{"media": "Digital Media", "bitdepth": 24}],
    )
    add_library_album(
        library,
        tmp_path / "Hi-Res SACD",
        album="Hi-Res SACD",
        items=[{"media": "SACD", "samplerate": 96_000}],
    )
    library.add(
        library_item(
            tmp_path / "Singleton",
            album="",
            bitdepth=24,
            samplerate=96_000,
        )
    )

    assert plugin._find_violations(library, None) == []


def test_audit_uses_query_and_custom_configuration(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
) -> None:
    wanted = add_library_album(
        library,
        tmp_path / "Wanted",
        album="Wanted",
        items=[{"media": "Compact Disc", "bitdepth": 24}],
    )
    add_library_album(
        library,
        tmp_path / "Other",
        album="Other",
        items=[{"media": "Compact Disc", "bitdepth": 32}],
    )
    plugin.config["cd_media_pattern"].set(r"^Compact Disc$")
    plugin.config["max_bitdepth"].set(20)
    plugin.config["max_samplerate"].set(96_000)

    violations = plugin._find_violations(library, ["album:Wanted"])

    assert [violation.album.id for violation in violations] == [wanted.id]


def test_audit_console_and_album_csv_report(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    album = add_library_album(
        library,
        tmp_path / "Álbum",
        album="Álbum",
        albumartist="Beyoncé",
        mb_albumid="musicbrainz-release-id",
        items=[
            {
                "title": "Résolution",
                "media": "Vinyl",
                "bitdepth": 24,
                "samplerate": 96_000,
            },
            {
                "title": "Compact",
                "media": "Enhanced CD",
                "bitdepth": 16,
                "samplerate": 44_100,
            },
        ],
    )
    output = tmp_path / "audit.csv"
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--output", str(output)])

    command.func(library, opts, args)

    stdout = capsys.readouterr().out
    assert f"Beyoncé — Álbum [album {album.id}] — 24-bit/96000 Hz — Enhanced CD" in stdout
    assert "1 violating album(s), 2 track(s)." in stdout
    assert f"Wrote 1 album row(s) to {output}." in stdout

    with output.open(encoding="utf-8", newline="") as output_file:
        reader = csv.DictReader(output_file)
        assert tuple(reader.fieldnames or ()) == CSV_FIELDS
        assert list(reader) == [
            {
                "album_id": str(album.id),
                "mb_albumid": "musicbrainz-release-id",
                "albumartist": "Beyoncé",
                "album": "Álbum",
                "path": str(tmp_path / "Álbum"),
                "track_count": "2",
                "max_bitdepth": "24",
                "max_samplerate": "96000",
                "media": "Enhanced CD; Vinyl",
                "hires_tracks": "1.1 Résolution (24-bit/96000 Hz)",
                "cd_tracks": "1.2 Compact (Enhanced CD)",
            }
        ]


def test_empty_audit_writes_no_default_file(
    plugin: NoHiResCdPlugin,
    library: Library,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    command = plugin.commands()[0]
    opts, args = command.parse_args([])

    command.func(library, opts, args)

    assert capsys.readouterr().out == "No nohirescd violations found.\n"
    assert list(tmp_path.glob("*.csv")) == []


def test_empty_audit_writes_header_when_output_is_requested(
    plugin: NoHiResCdPlugin,
    library: Library,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output = tmp_path / "empty.csv"
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--output", str(output)])

    command.func(library, opts, args)

    stdout = capsys.readouterr().out
    assert "No nohirescd violations found." in stdout
    assert "Wrote 0 album row(s)" in stdout
    assert output.read_text(encoding="utf-8").strip() == ",".join(CSV_FIELDS)


def test_output_error_becomes_user_error(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing" / "audit.csv"
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--output", str(output)])

    with pytest.raises(ui.UserError, match="Could not write nohirescd CSV"):
        command.func(library, opts, args)


def test_output_and_reimport_are_mutually_exclusive(
    plugin: NoHiResCdPlugin,
    library: Library,
) -> None:
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--output", "audit.csv", "--reimport"])

    with (
        patch.object(plugin, "_find_violations") as find_violations,
        pytest.raises(ui.UserError, match="cannot be used together"),
    ):
        command.func(library, opts, args)

    find_violations.assert_not_called()


def test_reimport_delegates_exact_violating_album_ids(
    plugin: NoHiResCdPlugin,
    library: Library,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wanted = add_library_album(
        library,
        tmp_path / "Wanted",
        album="Wanted",
        albumartist="Target Artist",
        items=[{"bitdepth": 24}],
    )
    add_library_album(
        library,
        tmp_path / "Other",
        album="Other",
        albumartist="Other Artist",
        items=[{"samplerate": 96_000}],
    )
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--reimport", "albumartist:Target Artist"])

    with patch("beetsplug.nohirescd.import_command.import_files") as import_files:
        command.func(library, opts, args)

    import_files.assert_called_once()
    called_lib, paths, query = import_files.call_args.args
    assert called_lib is library
    assert paths == []
    assert query.field_name == "id"
    assert query.pattern == [wanted.id]
    assert [album.id for album in library.albums(query)] == [wanted.id]
    stdout = capsys.readouterr().out
    assert stdout == "Reimporting 1 violating album(s).\n"
    assert "Target Artist" not in stdout


def test_reimport_does_not_start_session_without_violations(
    plugin: NoHiResCdPlugin,
    library: Library,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = plugin.commands()[0]
    opts, args = command.parse_args(["--reimport"])

    with patch("beetsplug.nohirescd.import_command.import_files") as import_files:
        command.func(library, opts, args)

    import_files.assert_not_called()
    assert capsys.readouterr().out == "No nohirescd violations found; nothing to reimport.\n"


def test_track_details_handle_missing_metadata(plugin: NoHiResCdPlugin) -> None:
    item = Item(id=7, bitdepth=24, samplerate=None, media="CD")

    assert plugin._track_label(item) == "item 7"
    assert plugin._hires_track_detail(item) == "item 7 (24-bit)"
    assert plugin._format_resolution(0, 0) == ""
