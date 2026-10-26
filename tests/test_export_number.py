import json
from pathlib import Path

import pytest

from academic_automation.database.models import AcademicModule
from academic_automation.services.catalog import sync_catalog
from academic_automation.services.web_export import WebExportNumberingError
from test_api import client_for
from test_web_export import add_note, run_export, snapshot

ADMIN = {"Authorization": "Bearer admin-test"}


def test_manual_number_api_preserves_moodle_number_and_supports_clear(tmp_path):
    backend, client = client_for(tmp_path)
    with client:
        with backend.state.sessions() as db:
            db.add(AcademicModule(id=532, program="DCC", cohort="V1", module_number=11, name="IA"))
            db.commit()
        assert client.get("/modules/532", headers=ADMIN).json()["export_number"] is None
        assert client.patch("/modules/532", headers={"Authorization": "Bearer n8n-test"},
                            json={"export_number": 13}).status_code == 403
        saved = client.patch("/modules/532", headers=ADMIN, json={"export_number": 13})
        assert saved.status_code == 200
        assert saved.json()["export_number"] == 13 and saved.json()["module_number"] == 11
        # Patches to preferences must not erase the separate export number.
        assert client.patch("/modules/532", headers=ADMIN, json={"enabled": True}).json()["export_number"] == 13
        cleared = client.patch("/modules/532", headers=ADMIN, json={"export_number": None, "enabled": None})
        assert cleared.json()["export_number"] is None and cleared.json()["enabled"] is True
        assert client.get("/modules", headers=ADMIN).json()[0]["export_number"] is None


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "13"])
def test_api_rejects_non_positive_or_non_integer_numbers(tmp_path, value):
    backend, client = client_for(tmp_path)
    with client:
        with backend.state.sessions() as db:
            db.add(AcademicModule(id=532, program="DCC", cohort="V1", module_number=11, name="IA"))
            db.commit()
        response = client.patch("/modules/532", headers=ADMIN, json={"export_number": value})
        assert response.status_code == 422
        assert client.get("/modules/532", headers=ADMIN).json()["export_number"] is None


def test_manual_number_survives_catalog_refresh_and_new_courses_start_empty(db):
    db.add(AcademicModule(id=532, program="DCC", cohort="V1", module_number=11,
                         export_number=13, name="IA", enabled=True))
    db.commit()
    courses = [{"moodle_course_id": ident, "program": "DCC", "cohort": "V1",
                "module_number": number, "module_name": name}
               for ident, number, name in [(532, 12, "Nuevo título"), (505, 13, "Seguridad")]]
    sync_catalog(db, courses)
    assert db.get(AcademicModule, 532).module_number == 12
    assert db.get(AcademicModule, 532).export_number == 13
    assert db.get(AcademicModule, 532).enabled is True
    assert db.get(AcademicModule, 505).export_number is None


def test_export_uses_manual_order_and_labels_everywhere_without_changing_urls(db, tmp_path):
    add_note(db, tmp_path, module_id=197)
    add_note(db, tmp_path, module_id=532)
    first, second = db.get(AcademicModule, 197), db.get(AcademicModule, 532)
    first.module_number, first.export_number = 8, 2
    second.module_number, second.export_number = 11, 13
    db.commit()
    run_export(db, tmp_path)
    root = tmp_path / "content"
    before = json.loads((root / "dcc/catalog.json").read_text())
    assert [(m["id"], m["number"]) for m in before["modules"]] == [(197, 2), (532, 13)]
    assert 'module_number: 13' in (root / "dcc/modulo-532/semana-01.md").read_text()
    assert "Módulo 13" in (root / "dcc/modulo-532/index.md").read_text()
    assert "13 ·" in (root / "dcc/index.md").read_text()
    second.export_number, first.export_number = 1, 3
    db.commit()
    run_export(db, tmp_path)
    after = json.loads((root / "dcc/catalog.json").read_text())
    assert [m["id"] for m in after["modules"]] == [532, 197]
    assert {m["id"]: m["link"] for m in before["modules"]} == {m["id"]: m["link"] for m in after["modules"]}
    assert first.module_number == 8 and second.module_number == 11


@pytest.mark.parametrize("case,reason", [("missing", "missing"), ("duplicate", "duplicate"), ("invalid", "invalid")])
def test_numbering_preflight_preserves_entire_existing_snapshot(db, tmp_path, case, reason):
    add_note(db, tmp_path)
    run_export(db, tmp_path)
    before = snapshot(tmp_path / "content")
    module = db.get(AcademicModule, 532)
    if case == "duplicate":
        # Even a course without ready notes reserves its assigned number in the cohort.
        db.add(AcademicModule(id=505, program="DCC", cohort="V1", module_number=99,
                             export_number=13, name="Seguridad"))
    else:
        module.export_number = None if case == "missing" else 0
    db.commit()
    with pytest.raises(WebExportNumberingError) as error:
        run_export(db, tmp_path)
    assert error.value.code == "WEB_EXPORT_NUMBERING_INVALID"
    assert any(issue["reason"] == reason and issue["module_id"] == 532 for issue in error.value.issues)
    assert snapshot(tmp_path / "content") == before


def test_numbers_can_repeat_in_other_cohorts_and_programs(db, tmp_path):
    add_note(db, tmp_path, module_id=197)
    add_note(db, tmp_path, module_id=532)
    db.get(AcademicModule, 197).cohort = "V2"
    db.add(AcademicModule(id=559, program="MIA", cohort="V1", module_number=14,
                         export_number=13, name="MLOps"))
    db.commit()
    assert run_export(db, tmp_path)["sessions"] == 2


def test_missing_number_allowed_for_modules_without_exportable_notes(db, tmp_path):
    add_note(db, tmp_path, processing_status="PENDING")
    db.get(AcademicModule, 532).export_number = None
    db.commit()
    assert run_export(db, tmp_path)["sessions"] == 0


def test_export_number_migration_preserves_rows_and_starts_empty(tmp_path, monkeypatch):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, text
    from academic_automation.database.models import Base

    url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    monkeypatch.setenv("ACADEMIC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ACADEMIC_DATABASE_URL", url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "c3ad19e62b04")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO academic_programs VALUES ('DCC', 'Doctorado', 8, 1)"))
        connection.execute(text("INSERT INTO academic_modules "
            "(id,program,cohort,module_number,name,enabled,mode,auto_publish,review_required) "
            "VALUES (532,'DCC','V1',11,'IA',1,'ALL',0,0)"))
        original = connection.execute(text("SELECT * FROM academic_modules")).first()
    command.upgrade(cfg, "head")
    with engine.begin() as connection:
        row = connection.execute(text("SELECT * FROM academic_modules")).first()
        assert tuple(row[:-1]) == tuple(original) and row[-1] is None
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        connection.execute(text("UPDATE academic_modules SET export_number=13"))
    with pytest.raises(RuntimeError, match="Manual export numbers exist"):
        command.downgrade(cfg, "c3ad19e62b04")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT export_number FROM academic_modules")).scalar() == 13
        connection.execute(text("UPDATE academic_modules SET export_number=NULL"))
    command.downgrade(cfg, "c3ad19e62b04")
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT export_number FROM academic_modules")).scalar() is None
    engine.dispose()


def test_dashboard_saves_switches_and_clears_manual_export_number(tmp_path, monkeypatch):
    from urllib.parse import urlsplit
    from streamlit.testing.v1 import AppTest

    backend, client = client_for(tmp_path)

    def request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        kwargs["headers"] = ADMIN
        return client.request(method, urlsplit(url).path, **kwargs)

    with client:
        with backend.state.sessions() as db:
            db.add_all([AcademicModule(id=ident, program="DCC", cohort="V1", module_number=number, name=name)
                        for ident, number, name in [(197, 8, "Investigación"), (532, 11, "IA")]])
            db.commit()
        monkeypatch.setattr("httpx.request", request)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
        app.sidebar.radio[0].set_value("Módulos").run()

        def field():
            return next(item for item in app.number_input if item.label == "Número de módulo para web")

        def save():
            next(button for button in app.button if button.label == "Guardar preferencias").click().run()
            assert not app.exception

        assert field().value is None
        field().set_value(2)
        save()
        assert field().value == 2
        next(item for item in app.selectbox if item.label == "Módulo").select_index(1).run()
        assert field().value is None
        field().set_value(13)
        save()
        assert field().value == 13
        next(item for item in app.checkbox if item.label == "Borrar número para web al guardar").check()
        save()
        with backend.state.sessions() as db:
            assert db.get(AcademicModule, 197).export_number == 2
            assert db.get(AcademicModule, 532).export_number is None
            assert db.get(AcademicModule, 532).module_number == 11
