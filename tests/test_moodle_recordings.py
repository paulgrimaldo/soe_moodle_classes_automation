from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
import json

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.moodle.client import MoodleClient

BASE = "https://soe.uagrm.edu.bo/virtual/"
COURSE_URL = BASE + "course/view.php?id=559"
SECTION_URL = COURSE_URL + "&section=2"
RESOURCE_URL = BASE + "mod/page/view.php?id=32389"
SECTION_LINK = {"title": "SESIONES SÍNCRONAS", "href": SECTION_URL}
RESOURCE_LINK = {"title": "Grabaciones de sesiones síncronas - 05/10/2026", "href": RESOURCE_URL}
SETUP = json.dumps({"techOrder": ["youtube"], "sources": [{"type": "video/youtube", "src": "https://youtu.be/7YR41cxhwR4"}]})


@pytest.fixture
def recording_client(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, moodle_selectors_file=tmp_path / "selectors.json")
    settings.prepare()
    client = MoodleClient(settings)
    page = AsyncMock()
    page.url = COURSE_URL
    page.title.return_value = "MIA-V1E4 - 14.ML-OPS"

    @asynccontextmanager
    async def browser(**kwargs):
        yield page

    async def open_page(page, url):
        page.url = url

    monkeypatch.setattr(client, "browser", browser)
    monkeypatch.setattr(client, "open", AsyncMock(side_effect=open_page))
    monkeypatch.setattr(client, "check_auth", AsyncMock())
    monkeypatch.setattr("academic_automation.moodle.client.asyncio.sleep", AsyncMock())
    return client, page


async def test_recordings_follow_observed_section_and_extract_lazy_player(recording_client, monkeypatch):
    client, page = recording_client

    async def links(page, container=""):
        return {COURSE_URL: [SECTION_LINK], SECTION_URL: [RESOURCE_LINK, RESOURCE_LINK], RESOURCE_URL: []}[page.url]

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = []  # YouTube iframe has not been created yet.
    lazy.evaluate_all.return_value = [SETUP]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)

    items = await client.recordings(559)

    assert len(items) == 1
    assert items[0]["resource_key"] == "/virtual/mod/page/view.php:32389"
    assert items[0]["video_id"] == "7YR41cxhwR4"
    assert items[0]["url"] == "https://www.youtube.com/watch?v=7YR41cxhwR4"
    assert items[0]["date"].isoformat() == "2026-10-05"
    assert [call.args[1] for call in client.open.await_args_list] == [COURSE_URL, SECTION_URL, RESOURCE_URL]


async def test_confirmed_false_positive_is_not_reimported_after_reconciliation(recording_client, monkeypatch, db, tmp_path):
    from sqlalchemy import select, delete
    from academic_automation.database.models import AcademicModule, AcademicSession, Recording
    from academic_automation.services.catalog import sync_recordings, reconcile

    client, page = recording_client
    course_url = BASE + "course/view.php?id=378"
    dates = [(22587, 6), (23341, 10), (23392, 13), (23429, 17), (23706, 20),
             (23759, 23), (23762, 24), (23880, 27), (23943, 31)]
    resources = [{"title": f"Grabaciones de sesiones síncronas - {day:02d}/10/2025",
                  "href": BASE + f"mod/page/view.php?id={identifier}"} for identifier, day in dates]

    async def links(page, container=""):
        return resources if page.url == course_url else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = []
    lazy.evaluate_all.side_effect = lambda _: [json.dumps({"sources": [{"src": "https://youtu.be/video" +
        page.url.rsplit("=", 1)[-1].zfill(6)}]})]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    configured = client.settings.moodle_ignored_resources_file
    client.settings.moodle_ignored_resources_file = tmp_path / "no-overrides.json"
    unfiltered = await client.recordings(378)
    assert len(unfiltered) == 9
    module = AcademicModule(id=378, program="MIA", cohort="V1E4", module_number=5, name="Estadística")
    db.add(module)
    db.commit()
    with pytest.raises(Conflict, match="MORE_THAN_EIGHT_SESSIONS"):
        sync_recordings(db, module, unfiltered)
    false_positive = db.scalar(select(AcademicSession).where(
        AcademicSession.resource_key == "/virtual/mod/page/view.php:23759"))
    stable = {s.resource_key: s.id for s in db.scalars(select(AcademicSession)) if s.id != false_positive.id}
    db.execute(delete(Recording).where(Recording.session_id == false_positive.id))
    db.delete(false_positive)
    db.flush()
    reconcile(db, module)
    db.commit()
    assert not module.review_required
    assert [(s.number, s.week, s.class_in_week) for s in db.scalars(
        select(AcademicSession).order_by(AcademicSession.class_date))] == [
        (n, (n + 1) // 2, (n - 1) % 2 + 1) for n in range(1, 9)]
    client.settings.moodle_ignored_resources_file = configured
    client.open.reset_mock()
    filtered = await client.recordings(378)
    assert len(filtered) == 8
    assert not any(call.args[1].endswith("id=23759") for call in client.open.await_args_list)
    assert sync_recordings(db, module, filtered) == 0
    assert {s.resource_key: s.id for s in db.scalars(select(AcademicSession))} == stable
    assert not module.review_required


@pytest.mark.parametrize("config", ["not json", "[]", '{"559": []}', '{"559": {"r1": ""}}'])
async def test_invalid_ignored_resources_stop_before_browser(recording_client, monkeypatch, tmp_path, config):
    client, _ = recording_client
    path = tmp_path / "ignored.json"
    path.write_text(config)
    client.settings.moodle_ignored_resources_file = path
    browser = MagicMock(side_effect=AssertionError("Invalid configuration must not open Moodle"))
    monkeypatch.setattr(client, "browser", browser)
    with pytest.raises(Conflict, match="MOODLE_IGNORED_RESOURCES_CONFIG_INVALID"):
        await client.recordings(559)
    browser.assert_not_called()


async def test_ignored_resources_are_scoped_and_can_leave_no_classes(recording_client, monkeypatch, tmp_path):
    client, _ = recording_client
    path = tmp_path / "ignored.json"
    client.settings.moodle_ignored_resources_file = path
    key = "/virtual/mod/page/view.php:32389"
    path.write_text(json.dumps({"559": {key: "Confirmed non-class"}}))
    monkeypatch.setattr(client, "links", AsyncMock(return_value=[RESOURCE_LINK]))
    assert await client.recordings(559) == []
    assert client.open.await_count == 1  # The excluded resource page is never visited.


async def test_module_505_recording_titles_without_de_are_discovered(recording_client, monkeypatch, db):
    from sqlalchemy import func, select
    from academic_automation.database.models import AcademicModule, AcademicSession, Recording
    from academic_automation.services.catalog import sync_recordings

    client, page = recording_client
    course_url = BASE + "course/view.php?id=505"
    # Titles and resource IDs replayed from the private module 505 inspection.
    resources = [{"title": f"Grabación sesión síncrona - {day}",
                  "href": BASE + f"mod/page/view.php?id={identifier}"}
                 for day, identifier in [("13/06/2026", 28359), ("27/06/2026", 29809),
                                         ("11/07/2026", 30060), ("25/07/2026", 30733)]]

    async def links(page, container=""):
        return resources * 2 if page.url == course_url else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = []
    video_ids = {28359: "abcdefghijk", 29809: "bcdefghijkl", 30060: "cdefghijklm", 30733: "defghijklmn"}
    lazy.evaluate_all.side_effect = lambda _: [json.dumps({"sources": [{"src": "https://youtu.be/" +
        video_ids[int(page.url.rsplit("=", 1)[-1])]}]})]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    items = await client.recordings(505)
    assert len(items) == 4
    assert [item["resource_key"] for item in items] == [
        f"/virtual/mod/page/view.php:{identifier}" for identifier in [28359, 29809, 30060, 30733]]
    assert [item["date"].isoformat() for item in items] == ["2026-06-13", "2026-06-27", "2026-07-11", "2026-07-25"]
    assert [item["video_id"] for item in items] == list(video_ids.values())  # Mock player IDs, not real course videos.
    module = AcademicModule(id=505, program="DCC", cohort="V1E1", module_number=13, name="Seguridad")
    db.add(module)
    db.commit()
    assert sync_recordings(db, module, items) == 4
    assert sync_recordings(db, module, items) == 0
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 4
    assert db.scalar(select(func.count()).select_from(Recording)) == 4


async def test_no_recordings_produces_review_with_safe_diagnostic(recording_client, monkeypatch):
    client, page = recording_client
    monkeypatch.setattr(client, "links", AsyncMock(return_value=[SECTION_LINK]))
    page.wait_for_function.side_effect = PlaywrightTimeout("https://private.invalid/?token=DO_NOT_EXPORT")

    with pytest.raises(Conflict, match="MOODLE_RECORDINGS_DOM_REQUIRES_INSPECTION"):
        await client.recordings(559)

    target = client.settings.workdir("private") / "moodle-recordings-559-inspection.json"
    report = json.loads(target.read_text())
    assert report["module_id"] == 559
    assert "DO_NOT_EXPORT" not in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600


async def test_ambiguous_sections_stop_instead_of_choosing_one(recording_client, monkeypatch):
    client, _ = recording_client
    monkeypatch.setattr(client, "links", AsyncMock(return_value=[SECTION_LINK, {
        "title": "SESIONES SÍNCRONAS", "href": COURSE_URL + "&section=7"}]))

    with pytest.raises(Conflict, match="MOODLE_RECORDINGS_SECTION_AMBIGUOUS"):
        await client.recordings(559)


@pytest.mark.parametrize("sources,configurations,expected_error", [
    (["https://www.youtube-nocookie.com/embed/7YR41cxhwR4"], [], None),
    ([], ["not json"], None),
    (["https://youtube.com/embed/abcdefghijk"], [SETUP], "MOODLE_MULTIPLE_VIDEOS"),
])
async def test_inline_resources_and_video_variants(recording_client, monkeypatch, sources, configurations, expected_error):
    client, page = recording_client

    async def links(page, container=""):
        return [RESOURCE_LINK] if page.url == COURSE_URL else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = sources
    lazy.evaluate_all.return_value = configurations
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    if expected_error:
        with pytest.raises(Conflict, match=expected_error):
            await client.recordings(559)
        report_path = client.settings.data_dir / "private/moodle-videos-559-inspection.json"
        report = json.loads(report_path.read_text())
        assert report["resource_key"] == "/virtual/mod/page/view.php:32389"
        assert {item["video_id"] for item in report["candidate_videos"]} == {"abcdefghijk", "7YR41cxhwR4"}
        assert next(item for item in report["candidate_videos"] if item["video_id"] == "abcdefghijk")["sources"] == ["media"]
        assert report_path.stat().st_mode & 0o777 == 0o600
    else:
        items = await client.recordings(559)
        assert len(items) == 1
        assert items[0].get("video_id") == ("7YR41cxhwR4" if sources else None)
        assert [call.args[1] for call in client.open.await_args_list] == [COURSE_URL, RESOURCE_URL]


def test_section_links_are_scoped_to_course_and_origin():
    from academic_automation.moodle.parsing import recording_section_urls

    links = [SECTION_LINK, SECTION_LINK,
             {"title": "SESIONES SÍNCRONAS", "href": BASE + "course/view.php?id=532&section=2"},
             {"title": "SESIONES SÍNCRONAS", "href": "https://example.org/course/view.php?id=559&section=2"},
             {"title": "SEMANA 1", "href": COURSE_URL + "&section=3"}]
    assert recording_section_urls(links, 559, BASE) == {SECTION_URL}


def test_player_sources_tolerate_malformed_configuration():
    from academic_automation.moodle.parsing import player_source_urls

    assert player_source_urls(["null", "[]", "broken", '{"sources": "bad"}', SETUP]) == ["https://youtu.be/7YR41cxhwR4"]


async def test_historical_dcc_recordings_are_discovered_inline_without_section_guess(recording_client, monkeypatch):
    from datetime import date

    client, page = recording_client
    course = BASE + "course/view.php?id=195"
    labels = [(9780, "Grabación de sesión síncrona - SEMANA 1 (23/03/24)"),
              (10148, "Grabación de sesión síncrona - SEMANA 4 (06/04/24)"),
              (10563, "Grabación de sesión síncrona - ENCUENTRO 3 (20/04/24)")]
    resources = [{"title": label, "href": BASE + f"mod/page/view.php?id={identifier}"}
                 for identifier, label in labels]
    attendance = {"title": "Asistencia a sesiones síncronas", "href": BASE + "mod/attendance/view.php?id=9771"}

    async def links(page, container=""):
        return [attendance, *resources] if page.url == course else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media = AsyncMock()
    media.evaluate_all.return_value = []
    page.locator = MagicMock(return_value=media)

    result = await client.recordings(195)

    assert len(result) == 3
    assert [item["date"] for item in result] == [date(2024, 3, 23), date(2024, 4, 6), date(2024, 4, 20)]
    assert [item["resource_key"] for item in result] == [f"/virtual/mod/page/view.php:{identifier}" for identifier, _ in labels]
    assert [call.args[1] for call in client.open.await_args_list] == [course, *(link["href"] for link in resources)]


async def test_same_video_in_multiple_formats_is_not_multiple_recordings(recording_client, monkeypatch):
    client, page = recording_client

    async def links(page, container=""):
        return [RESOURCE_LINK] if page.url == COURSE_URL else [{
            "title": "YouTube", "href": "https://youtube.com/watch?v=7YR41cxhwR4&token=DO_NOT_EXPORT"}]

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = ["https://www.youtube-nocookie.com/embed/7YR41cxhwR4"]
    lazy.evaluate_all.return_value = [SETUP]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    result = await client.recordings(559)
    assert len(result) == 1 and result[0]["video_id"] == "7YR41cxhwR4"


async def test_multiple_video_diagnostic_does_not_include_url_secrets(recording_client, monkeypatch):
    client, page = recording_client

    async def links(page, container=""):
        return [RESOURCE_LINK] if page.url == COURSE_URL else [{
            "title": "Ver video", "href": "https://youtube.com/watch?v=abcdefghijk&token=DO_NOT_EXPORT"}]

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = []
    lazy.evaluate_all.return_value = [SETUP]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    with pytest.raises(Conflict, match="MOODLE_MULTIPLE_VIDEOS"):
        await client.recordings(559)
    target = client.settings.data_dir / "private/moodle-videos-559-inspection.json"
    report = json.loads(target.read_text())
    assert report["module_id"] == 559 and report["resource_id"] == 32389
    assert {item["video_id"] for item in report["candidate_videos"]} == {"abcdefghijk", "7YR41cxhwR4"}
    assert "DO_NOT_EXPORT" not in target.read_text() and "token=" not in target.read_text()
    assert report["candidate_videos"][0]["url"].startswith("https://www.youtube.com/watch?v=")


async def test_recording_inspector_reports_conflict_file_without_creating_sessions(recording_client, monkeypatch):
    client, _ = recording_client
    monkeypatch.setattr(client, "recordings", AsyncMock(side_effect=Conflict("MOODLE_MULTIPLE_VIDEOS")))
    report = await client.inspect_recordings(197)
    assert report["diagnostic_file"].endswith("moodle-videos-197-inspection.json")
    assert report["error_code"] == "MOODLE_MULTIPLE_VIDEOS" and report["status"] == "failed"
    assert not report["database_changes"] and not report["processing_started"]


async def test_recording_inspector_success_reports_counts_without_synchronizing(recording_client, monkeypatch):
    client, _ = recording_client
    monkeypatch.setattr(client, "recordings", AsyncMock(return_value=[{"video_id": "abcdefghijk"}, {}]))
    report = await client.inspect_recordings(197)
    assert report["recordings_found"] == 2 and report["videos_identified"] == 1
    assert report["status"] == "completed"
    assert not report["database_changes"] and not report["processing_started"]


async def test_only_explicit_resource_parts_are_grouped_in_confirmed_order(recording_client, monkeypatch):
    client, page = recording_client
    configured = ["7YR41cxhwR4", "abcdefghijk"]
    config = client.settings.workdir("private") / "moodle-recording-parts.json"
    config.write_text(json.dumps({"559": {"/virtual/mod/page/view.php:32389": configured}}))

    async def links(page, container=""):
        return [RESOURCE_LINK] if page.url == COURSE_URL else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.return_value = ["https://youtube.com/embed/abcdefghijk"]  # DOM order differs.
    lazy.evaluate_all.return_value = [SETUP]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    items = await client.recordings(559)
    assert len(items) == 1
    assert [part["video_id"] for part in items[0]["videos"]] == configured
    config.write_text(json.dumps({"559": {"/virtual/mod/page/view.php:32389": [*configured, "bcdefghijkl"]}}))
    with pytest.raises(Conflict, match="MOODLE_RECORDING_PARTS_CHANGED"):
        await client.recordings(559)


async def test_partial_discovery_keeps_good_resources_and_collects_all_ambiguous_ones(recording_client, monkeypatch):
    client, page = recording_client
    resources = [{"title": f"Grabaciones de sesiones síncronas - {day:02d}/10/2026",
                  "href": BASE + f"mod/page/view.php?id={rid}"} for day, rid in [(5, 32389), (9, 32390), (12, 32391)]]

    async def links(page, container=""):
        return resources if page.url == COURSE_URL else []

    monkeypatch.setattr(client, "links", AsyncMock(side_effect=links))
    media, lazy = AsyncMock(), AsyncMock()
    media.evaluate_all.side_effect = lambda _: ([] if page.url == resources[0]["href"] else ["https://youtube.com/watch?v=abcdefghijk"])
    lazy.evaluate_all.return_value = [SETUP]
    page.locator = MagicMock(side_effect=lambda selector: lazy if selector == "[data-setup-lazy]" else media)
    result = await client.recordings(559, allow_partial=True)
    assert len(result) == 3
    assert result[0]["video_id"] == "7YR41cxhwR4"
    assert all(item["discovery_error"] == "MOODLE_MULTIPLE_VIDEOS" for item in result[1:])
    assert all(len(item["video_candidates"]) == 2 and "video_id" not in item for item in result[1:])
    for rid in [32390, 32391]:
        assert (client.settings.data_dir / f"private/moodle-videos-559-{rid}-inspection.json").is_file()
