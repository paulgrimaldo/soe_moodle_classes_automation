from datetime import date

import pytest

from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession
from test_api import client_for

ADMIN = {"Authorization": "Bearer admin-test"}
MARKDOWN = "# Clase 3: Despliegue\n\nTexto **académico**.\n\n$$x^2$$\n\n```mermaid\ngraph LR\nA --> B\n```\n"


def add_notes(app, tmp_path, *, output=True, processing_status="PROCESSED"):
    path = tmp_path / "processed" / "job-1" / "bundle" / "notes.md"
    path.parent.mkdir(parents=True)
    path.write_text(MARKDOWN)
    with app.state.sessions() as db:
        db.add(AcademicModule(id=559, program="MIA", cohort="V1E4", module_number=14, name="MLOps"))
        db.commit()
        db.add(AcademicSession(id="class3", module_id=559, resource_key="resource3", title="Grabación",
                              class_date=date(2026, 10, 12), number=3, week=2, class_in_week=1,
                              processing_status=processing_status, revision=1,
                              output_path=str(path) if output else None,
                              content_hash=digest(MARKDOWN) if output else None))
        db.commit()
    return path


@pytest.mark.parametrize("state", ["PROCESSED", "PROCESSING", "FAILED"])
def test_notes_returns_saved_revision_with_admin_auth(tmp_path, state):
    app, client = client_for(tmp_path)
    with client:
        add_notes(app, tmp_path, processing_status=state)
        assert client.get("/sessions/class3/notes").status_code == 401
        assert client.get("/sessions/class3/notes", headers={"Authorization": "Bearer n8n-test"}).status_code == 403
        response = client.get("/sessions/class3/notes", headers=ADMIN)
        assert response.status_code == 200
        data = response.json()
        assert data["markdown"] == MARKDOWN
        assert data["session_id"] == "class3" and data["number"] == 3
        assert data["revision"] == 1 and data["week"] == 2 and data["class_in_week"] == 1
        assert data["filename"] == "MIA-559-sesion-3.md"
        assert str(tmp_path) not in response.text
        assert "output_path" not in data


def test_notes_not_ready_and_unknown_session(tmp_path):
    app, client = client_for(tmp_path)
    with client:
        add_notes(app, tmp_path, output=False)
        assert client.get("/sessions/class3/notes", headers=ADMIN).status_code == 404
        assert client.get("/sessions/unknown/notes", headers=ADMIN).status_code == 404


@pytest.mark.parametrize("case,expected", [("outside", 409), ("symlink", 409), ("changed", 409),
                                           ("missing", 404), ("invalid_utf8", 409)])
def test_notes_rejects_untrusted_or_invalid_artifacts(tmp_path, case, expected):
    app, client = client_for(tmp_path)
    with client:
        path = add_notes(app, tmp_path)
        if case in {"outside", "symlink"}:
            private_file = tmp_path / "private" / "notes.md"
            private_file.parent.mkdir()
            private_file.write_text("DO_NOT_EXPORT")
            if case == "outside":
                with app.state.sessions() as db:
                    db.get(AcademicSession, "class3").output_path = str(private_file)
                    db.commit()
            else:
                path.unlink()
                path.symlink_to(private_file)
            with app.state.sessions() as db:
                db.get(AcademicSession, "class3").content_hash = digest(private_file.read_bytes())
                db.commit()
        elif case == "changed":
            path.write_text("Modified outside pipeline")
        elif case == "missing":
            path.unlink()
        else:
            data = b"\xff\xfe"
            path.write_bytes(data)
            with app.state.sessions() as db:
                db.get(AcademicSession, "class3").content_hash = digest(data)
                db.commit()
        response = client.get("/sessions/class3/notes", headers=ADMIN)
        assert response.status_code == expected
        assert "DO_NOT_EXPORT" not in response.text and str(tmp_path) not in response.text


def test_notes_reconciled_revision_and_size_limit(tmp_path, monkeypatch):
    app, client = client_for(tmp_path)
    with client:
        path = add_notes(app, tmp_path)
        reconciled = tmp_path / "reconciled" / "job" / "class3" / "notes.md"
        reconciled.parent.mkdir(parents=True)
        path.rename(reconciled)
        with app.state.sessions() as db:
            db.get(AcademicSession, "class3").output_path = str(reconciled)
            db.commit()
        assert client.get("/sessions/class3/notes", headers=ADMIN).status_code == 200
        monkeypatch.setattr("academic_automation.services.artifacts.MAX_NOTES_BYTES", 10)
        assert client.get("/sessions/class3/notes", headers=ADMIN).status_code == 413
