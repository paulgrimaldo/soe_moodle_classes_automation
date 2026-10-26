from datetime import timedelta

from academic_automation.database.models import AcademicModule, AcademicSession, now
from academic_automation.orchestration.queue import claim, enqueue, recover
from academic_automation.services.catalog import assignment, authorized, sync_catalog


def module(db):
    m = AcademicModule(id=559, program="MIA", cohort="V1E4", module_number=14, name="MLOps")
    db.add(m)
    db.commit()
    return m


def test_assignment():
    assert [assignment("DCC", n) for n in range(1, 9)] == [(n, 1) for n in range(1, 9)]
    assert [assignment("MIA", n) for n in range(1, 9)] == [(w, c) for w in range(1, 5) for c in (1, 2)]


def test_catalog_preserves_preferences(db):
    m = module(db)
    m.enabled, m.mode = True, "ALL"
    db.commit()
    sync_catalog(db, [{"moodle_course_id": 559, "program": "MIA", "cohort": "V1E4", "module_number": 14,
                       "module_name": "Nuevo título"}])
    assert m.enabled and m.mode == "ALL" and m.name == "Nuevo título"


def test_selection(db):
    m = module(db)
    s = AcademicSession(week=1, excluded=False, selected=True, discovered_at=now())
    assert not authorized(m, s)
    m.enabled = True
    assert authorized(m, s)
    m.mode, s.selected = "ALL", False
    assert authorized(m, s)
    m.mode, m.activated_at = "NEW_ONLY", now() + timedelta(seconds=1)
    assert not authorized(m, s)
    m.activated_at = now() - timedelta(seconds=1)
    assert authorized(m, s)
    s.excluded = True
    assert not authorized(m, s)


def test_queue_durable_idempotent_and_recovery(db):
    j = enqueue(db, "catalog")
    assert enqueue(db, "catalog").id == j.id
    assert claim(db).attempts == 1
    assert claim(db) is None
    assert recover(db) == 1
    assert claim(db).id == j.id
    j.stage = "notion"
    db.commit()
    recover(db)
    assert j.status == "REVIEW_REQUIRED"
