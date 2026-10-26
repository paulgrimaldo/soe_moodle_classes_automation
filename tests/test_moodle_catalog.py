from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.moodle.client import MoodleClient
from academic_automation.moodle.parsing import course_from_link


@pytest.fixture
def catalog_client(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, moodle_selectors_file=tmp_path / "selectors.json")
    settings.prepare()
    settings.moodle_state.write_text("{}")
    client = MoodleClient(settings)
    page = AsyncMock()
    page.url = settings.moodle_url
    page.title.return_value = "Mis cursos | soevirtual"

    @asynccontextmanager
    async def browser(**kwargs):
        yield page

    monkeypatch.setattr(client, "browser", browser)
    monkeypatch.setattr(client, "open", AsyncMock())
    return client, page


async def test_real_catalog_labels_keep_complete_name(catalog_client, monkeypatch):
    client, page = catalog_client
    full = "INTELIGENCIA ARTIFICIAL Y RECONOCIMIENTO DE PATRONES CON MACHINE LEARNING"
    links = [
        {"title": f"DCC-V1E1 DCC-V1E1 - 11. {full}",
         "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=532"},
        {"title": "Nombre del curso DCC-V1E1 - 11. INTELIGENCIA ARTIFICIAL Y ...",
         "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=532"},
        {"title": "Nombre del curso MIA-V1E4 - 14.ML-OPS Y PUESTA EN PRODUCCIÓN",
         "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=559"},
        {"title": "MIA-V1E4 - 99.CURSO AJENO", "href": "https://example.org/virtual/course/view.php?id=999"},
        {"title": "Nombre del curso TAM-V1E1- 1.TALLER DE ARTICULACIÓN METODOLOGICA",
         "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=518"},
    ]
    monkeypatch.setattr(client, "links", AsyncMock(return_value=links))

    result = {course["moodle_course_id"]: course for course in await client.catalog()}

    assert set(result) == {532, 559}
    assert result[532]["module_name"] == full
    page.wait_for_function.assert_awaited()


async def test_empty_catalog_persists_safe_inspection(catalog_client, monkeypatch):
    client, _ = catalog_client
    links = [
        {"title": "Nombre del curso sin formato académico", "href":
         "https://soe.uagrm.edu.bo/virtual/course/view.php?id=559&sesskey=DO_NOT_EXPORT"},
        {"title": "Cerrar sesión", "href":
         "https://soe.uagrm.edu.bo/virtual/login/logout.php?sesskey=DO_NOT_EXPORT"},
    ]
    monkeypatch.setattr(client, "links", AsyncMock(return_value=links))

    with pytest.raises(Conflict, match="MOODLE_CATALOG_DOM_REQUIRES_INSPECTION"):
        await client.catalog()

    report_file = client.settings.data_dir / "private/moodle-catalog-inspection.json"
    report = json.loads(report_file.read_text())
    assert len(report["course_links"]) == 1
    assert report["course_links"][0]["moodle_course_id"] == 559
    assert "sesskey" not in report_file.read_text() and "DO_NOT_EXPORT" not in report_file.read_text()


def test_accessibility_and_image_labels_prefer_full_title():
    item = course_from_link({
        "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=532",
        "title": "Nombre del curso DCC-V1E1 - 11. INTELIGENCIA ARTIFICIAL Y ...",
        "labels": ["DCC-V1E1 DCC-V1E1 - 11. INTELIGENCIA ARTIFICIAL Y RECONOCIMIENTO DE PATRONES"],
    })
    assert item["module_name"] == "INTELIGENCIA ARTIFICIAL Y RECONOCIMIENTO DE PATRONES"


async def test_catalog_selects_observed_all_courses_filter(catalog_client, monkeypatch):
    client, page = catalog_client
    grouping = "Menú desplegable de agrupación"
    all_courses = "Mostrar todos los cursos excepto los cursos archivados"
    client.selectors.update(catalog_grouping_label=grouping, catalog_all_courses_label=all_courses)
    button, option, _ = catalog_controls(client, page)
    monkeypatch.setattr(client, "links", AsyncMock(return_value=[{
        "title": "Nombre del curso MIA-V1E4 - 14.ML-OPS Y PUESTA EN PRODUCCIÓN",
        "href": "https://soe.uagrm.edu.bo/virtual/course/view.php?id=559",
    }]))

    result = await client.catalog()

    assert len(result) == 1
    page.get_by_role.assert_any_call("button", name=grouping, exact=True)
    page.get_by_role.assert_any_call("menuitem", name=all_courses, exact=True, include_hidden=True)
    button.click.assert_awaited_once()
    option.click.assert_awaited_once()
    page.wait_for_function.assert_awaited_once()


def catalog_controls(client, page, *, selected=False, hydrated=True):
    """Model the observed dropdown: clicks before data-init do not open its menu."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    grouping = "Menú desplegable de agrupación"
    all_courses = "Mostrar todos los cursos excepto los cursos archivados"
    ready_selector = '[data-region="myoverview"][data-init="true"]'
    client.selectors.update(catalog_grouping_label=grouping,
                            catalog_all_courses_label=all_courses,
                            catalog_ready_selector=ready_selector)
    state = {"ready": False, "expanded": False}
    button, option, ready = AsyncMock(), AsyncMock(), AsyncMock()

    async def wait_ready(**kwargs):
        if not hydrated:
            raise PlaywrightTimeout("initialization pending")
        state["ready"] = True

    async def click_button():
        state["expanded"] = state["ready"]

    async def click_option():
        if not state["expanded"]:
            raise PlaywrightTimeout("menu item is hidden")

    ready.wait_for.side_effect = wait_ready
    button.click.side_effect = click_button
    button.get_attribute.side_effect = lambda name: str(state["expanded"]).lower()
    option.click.side_effect = click_option
    option.get_attribute.return_value = "true" if selected else None
    controls = {grouping: button, all_courses: option}
    page.get_by_label = MagicMock(side_effect=lambda label, **kwargs: controls[label])
    page.get_by_role = MagicMock(side_effect=lambda role, *, name, **kwargs: controls[name])
    page.locator = MagicMock(return_value=ready)
    return button, option, ready


async def test_catalog_waits_for_javascript_before_using_dropdown(catalog_client):
    client, page = catalog_client
    button, option, ready = catalog_controls(client, page)

    await client.prepare_catalog(page)

    ready.wait_for.assert_awaited_once()
    button.click.assert_awaited_once()
    option.click.assert_awaited_once()


async def test_catalog_preserves_already_selected_all_filter(catalog_client):
    client, page = catalog_client
    button, option, _ = catalog_controls(client, page, selected=True)

    await client.prepare_catalog(page)

    button.click.assert_not_awaited()
    option.click.assert_not_awaited()
    page.wait_for_function.assert_awaited_once()


@pytest.mark.parametrize("operation", ["ready", "filter", "courses"])
async def test_catalog_timeout_reports_exact_operation(catalog_client, monkeypatch, operation):
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from academic_automation.core.errors import StageError

    client, page = catalog_client
    button, _, _ = catalog_controls(client, page, hydrated=operation != "ready")
    if operation == "filter":
        button.click.side_effect = PlaywrightTimeout("button hidden https://secret.invalid/?token=DO_NOT_EXPORT")
    if operation == "courses":
        page.wait_for_function.side_effect = PlaywrightTimeout("no courses")
    monkeypatch.setattr(client, "check_auth", AsyncMock())
    monkeypatch.setattr(client, "links", AsyncMock(return_value=[]))

    with pytest.raises(StageError) as error:
        await client.prepare_catalog(page)

    expected = {"ready": "MOODLE_CATALOG_READY_TIMEOUT", "filter": "MOODLE_CATALOG_FILTER_TIMEOUT",
                "courses": "MOODLE_CATALOG_DOM_REQUIRES_INSPECTION"}
    assert error.value.code == expected[operation]
    report_file = client.settings.workdir("private") / "moodle-catalog-inspection.json"
    report = json.loads(report_file.read_text())
    assert report["operation"] == {"ready": "catalog_ready", "filter": "catalog_filter_open",
                                   "courses": "catalog_courses"}[operation]
    assert "DO_NOT_EXPORT" not in report_file.read_text()
    assert report_file.stat().st_mode & 0o777 == 0o600


async def test_navigation_timeout_has_runtime_revision_and_exact_operation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from academic_automation.core.errors import StageError

    settings = Settings(data_dir=tmp_path, moodle_selectors_file=tmp_path / "selectors.json")
    settings.prepare()
    client = MoodleClient(settings)
    page = AsyncMock()
    page.goto.side_effect = PlaywrightTimeout("navigation https://private.invalid/?token=DO_NOT_EXPORT")
    context = AsyncMock()
    context.set_default_timeout = MagicMock()
    context.new_page.return_value = page
    browser = AsyncMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__aenter__ = AsyncMock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(return_value=browser))))
    playwright.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("academic_automation.moodle.client.async_playwright", lambda: playwright)

    with pytest.raises(StageError, match="MOODLE_NAVIGATION_TIMEOUT"):
        async with client.browser() as opened:
            await client.open(opened, settings.moodle_url)

    progress_file = settings.workdir("private") / "moodle-progress.json"
    progress = json.loads(progress_file.read_text())
    assert progress["operation"] == "navigation"
    assert progress["error_code"] == "MOODLE_NAVIGATION_TIMEOUT"
    assert progress["client_revision"] and progress["pid"] > 0
    assert "DO_NOT_EXPORT" not in progress_file.read_text()
    assert progress_file.stat().st_mode & 0o777 == 0o600
    browser.close.assert_awaited_once()
