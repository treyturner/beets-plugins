from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from beets.autotag import AlbumInfo, AlbumMatch, Recommendation, TrackInfo
from beets.autotag.distance import Distance
from beets.importer import ImportTask
from beets.library import Item

from beetsplug.nohirescd import NoHiResCdPlugin


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


@pytest.fixture
def plugin() -> NoHiResCdPlugin:
    instance = NoHiResCdPlugin()
    instance.config["max_bitdepth"].set(16)
    instance.config["max_samplerate"].set(44_100)
    instance.config["cd_media_pattern"].set(r"(?:^|[^A-Za-z0-9])CD(?:-R)?(?:$|[^A-Za-z0-9])")
    instance._log = Mock()
    return instance


def test_registers_both_candidate_filter_events(
    plugin: NoHiResCdPlugin,
) -> None:
    assert plugin._filter_candidates in plugin._raw_listeners["import_task_before_choice"]
    assert plugin._filter_candidates in plugin._raw_listeners["before_choose_candidate"]


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
