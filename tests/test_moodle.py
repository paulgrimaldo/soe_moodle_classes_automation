from datetime import date

import pytest
from sqlalchemy import select, func

from academic_automation.database.models import AcademicSession, NotionSection, Recording
from academic_automation.moodle.parsing import course_metadata, resource_metadata, youtube
from academic_automation.services.catalog import sync_recordings
from test_foundation import module


@pytest.mark.parametrize("title,expected", [
    ("MIA-V1E4 - 14.ML-OPS Y PUESTA EN PRODUCCIÓN", ("MIA", "V1E4", 14)),
    ("DCC-V1E1 - 11. INTELIGENCIA ARTIFICIAL Y ...", ("DCC", "V1E1", 11)),
    ("Nombre del curso MIA-V1E4 - 14.ML-OPS Y PUESTA EN PRODUCCIÓN", ("MIA", "V1E4", 14)),
    ("MIA-V1E4 MIA-V1E4 - 14.ML-OPS Y PUESTA EN PRODUCCIÓN", ("MIA", "V1E4", 14)),
    ("DCC-V1E1 DCC-V1E1 - 11. INTELIGENCIA ARTIFICIAL Y RECONOCIMIENTO DE PATRONES CON MACHINE LEARNING",
     ("DCC", "V1E1", 11)),
])
def test_course(title, expected):
    item = course_metadata(title, "https://soe.uagrm.edu.bo/virtual/course/view.php?id=559")
    assert (item["program"], item["cohort"], item["module_number"]) == expected
    assert item["moodle_course_id"] == 559


@pytest.mark.parametrize("url", [
    "https://youtube.com/embed/abcdefghijk?start=2", "https://www.youtube.com/watch?v=abcdefghijk",
    "https://youtu.be/abcdefghijk?t=5", "https://www.youtube-nocookie.com/embed/abcdefghijk",
    "//www.youtube.com/embed/abcdefghijk",
])
def test_youtube(url):
    assert youtube(url) == ("abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk")


@pytest.mark.parametrize("url", ["https://youtube.com.attacker.org/watch?v=abcdefghijk", "https://youtu.be/x", "javascript:alert(1)"])
def test_bad_youtube(url):
    assert youtube(url) is None


def recording(key, day, video):
    return {"resource_key": key, "title": "Grabación", "date": date(2026, 10, day),
            "video_id": video, "url": f"https://youtu.be/{video}", "resource_url": f"https://example.org/{key}"}


def test_idempotence_and_late_reconciliation(db):
    m = module(db)
    items = [recording("resource2", 9, "abcdefghijk"), recording("resource3", 12, "bcdefghijkl")]
    assert sync_recordings(db, m, items) == 2
    assert sync_recordings(db, m, items) == 0
    first = db.scalar(select(AcademicSession).where(AcademicSession.number == 1))
    stable_id = first.id
    db.add(NotionSection(session_id=first.id, page_id="week1", block_ids=["block1"], remote_hash="hash"))
    db.commit()
    sync_recordings(db, m, [recording("resource1", 5, "cdefghijklm")])
    assert m.review_required and m.proposed_assignments
    assert db.get(AcademicSession, stable_id).number == 1
    assert next(p for p in m.proposed_assignments if p["id"] == stable_id)["number"] == 2
    assert db.scalar(select(func.count()).select_from(Recording)) == 3


def test_unpublished_reorders_and_same_video_not_duplicated(db):
    m = module(db)
    sync_recordings(db, m, [recording("b", 12, "abcdefghijk")])
    stable = db.scalar(select(AcademicSession)).id
    sync_recordings(db, m, [recording("a", 5, "bcdefghijkl"), recording("duplicate", 12, "abcdefghijk")])
    assert db.get(AcademicSession, stable).number == 2
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 2


def test_resource_metadata():
    item = resource_metadata("Grabaciones de sesiones síncronas - 05/10/2026",
                             "/virtual/mod/page/view.php?id=55", "https://soe.uagrm.edu.bo/virtual/my/courses.php")
    assert item["date"] == date(2026, 10, 5)
    assert item["resource_key"] == "/virtual/mod/page/view.php:55"


@pytest.mark.parametrize("title,expected_date", [
    ("Grabación de sesión síncrona - 23/03/2024", date(2024, 3, 23)),
    ("Grabaciones de sesiones síncronas - SEMANA 1 (23/03/2024)", date(2024, 3, 23)),
    ("Grabaciones de sesiones síncronas - 23/03/24", date(2024, 3, 23)),
    ("Grabación de sesión síncrona - SEMANA 1 (23/03/24)", date(2024, 3, 23)),
    ("Grabación de sesión síncrona - SEMANA 4 (06/04/24)", date(2024, 4, 6)),
    ("Grabación de sesión síncrona - ENCUENTRO 3 (20/04/24)", date(2024, 4, 20)),
    ("Grabacion de sesion sincrona - ENCUENTRO 3 (20/04/24)", date(2024, 4, 20)),
    ("Grabación sesión síncrona - 13/06/2026", date(2026, 6, 13)),
    ("Grabación sesión síncrona - 27/06/2026", date(2026, 6, 27)),
    ("Grabación sesión síncrona - 11/07/2026", date(2026, 7, 11)),
    ("Grabación sesión síncrona - 25/07/2026", date(2026, 7, 25)),
])
def test_historical_recording_labels(title, expected_date):
    from academic_automation.moodle.parsing import RECORDING

    item = resource_metadata(title, "/virtual/mod/page/view.php?id=9780",
                             "https://soe.uagrm.edu.bo/virtual/my/courses.php")
    assert item is not None
    assert RECORDING.search(title)  # Same pattern is passed to the browser's readiness check.
    assert item["date"] == expected_date
    assert item["resource_key"] == "/virtual/mod/page/view.php:9780"


@pytest.mark.parametrize("title", [
    "Grabación de sesión síncrona - SEMANA 1 (31/02/24)",
    "Grabaciones de sesiones síncronas - 05/10/20260",
    "Guía para el encuentro 1 - 23/03/24",
    "Asistencia a sesiones síncronas - 23/03/24",
])
def test_non_recording_or_invalid_date_not_accepted(title):
    assert resource_metadata(title, "/virtual/mod/page/view.php?id=9780",
                             "https://soe.uagrm.edu.bo/virtual/my/courses.php") is None
