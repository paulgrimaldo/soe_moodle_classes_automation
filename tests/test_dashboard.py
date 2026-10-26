from pathlib import Path

import httpx
import pytest


def test_dashboard_views_without_external_calls(monkeypatch):
    pytest.importorskip("streamlit", minversion="1.37")
    from streamlit.testing.v1 import AppTest
    from datetime import date

    module = {"id": 559, "program": "MIA", "cohort": "V1E4", "module_number": 14, "name": "MLOps",
              "enabled": False, "mode": "MANUAL", "auto_publish": False, "review_required": False,
              "proposed_assignments": None}
    session = {"id": "session1", "module_id": 559, "number": 1, "week": 1, "class_in_week": 1,
               "class_date": date(2026, 10, 5).isoformat(), "youtube_url": "https://youtu.be/abcdefghijk",
               "transcript_status": "TRANSCRIPT_PENDING", "processing_status": "PENDING",
               "publication_status": "PENDING", "selected": False, "excluded": False,
               "title": "Grabación", "error_code": None, "notion_url": None}
    def request(method, url, **kwargs):
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=1,enabled=0,sessions=1,processed=0,published=0,
                                               pending=0,failed=0,last_sync=None))
        if url.endswith("/modules"):
            return httpx.Response(200, json=[module])
        if url.endswith("/sessions"):
            return httpx.Response(200, json=[session])
        return httpx.Response(200, json=[])
    monkeypatch.setattr("httpx.request", request)
    dashboard_path = Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "main.py"
    app = AppTest.from_file(dashboard_path).run(timeout=20)
    assert len(app.exception) == 0
    for view in ["Módulos", "Sesiones", "Apuntes", "Historial"]:
        app.sidebar.radio[0].set_value(view).run(timeout=20)
        assert len(app.exception) == 0, view


def test_dashboard_recovers_deleted_week_with_explicit_ack(monkeypatch):
    from streamlit.testing.v1 import AppTest

    module = {"id": 559, "program": "MIA", "cohort": "V1E4", "module_number": 14, "name": "MLOps",
              "enabled": False, "mode": "MANUAL", "auto_publish": False, "review_required": False}
    posted = []

    def request(method, url, **kwargs):
        if method == "POST":
            posted.append((url, kwargs["json"]))
            return httpx.Response(200, json={"audit_job_id": "relink-audit", "changed": True})
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=1, enabled=0, sessions=0, processed=0,
                                               published=0, pending=0, failed=0, last_sync=None))
        if url.endswith("/modules"):
            return httpx.Response(200, json=[module])
        if url.endswith("/pages"):
            return httpx.Response(200, json=[{"page_id": "old-page", "week": 2}])
        return httpx.Response(200, json=[])

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    app.sidebar.radio[0].set_value("Módulos").run()
    label = "Validar página nueva y recuperar vínculo"
    assert next(button for button in app.button if button.label == label).disabled
    next(box for box in app.checkbox if box.label.startswith("Confirmo que eliminé")).check().run()
    next(field for field in app.text_input if field.label == "URL o ID de la página nueva").set_value("new-page")
    next(button for button in app.button if button.label == label).click().run()
    assert posted == [("http://127.0.0.1:8000/notion/modules/559/relink", {
        "page_id": "new-page", "week": 2, "previous_page_id": "old-page", "acknowledge_replacement": True})]
    assert any("relink-audit" in message.value for message in app.success)
    assert not app.exception


def test_history_shows_error_and_retry_time(monkeypatch):
    from streamlit.testing.v1 import AppTest

    job = {"id": "catalog-test", "kind": "catalog", "status": "RETRY_WAIT", "stage": "moodle",
           "error_code": "MOODLE_CATALOG_READY_TIMEOUT", "attempts": 1,
           "created_at": "2026-10-17T04:26:00", "started_at": "2026-10-17T04:26:00",
           "finished_at": "2026-10-17T04:27:00", "available_at": "2026-10-17T04:42:00",
           "model": None, "skill_version": None, "result": None}

    def request(method, url, **kwargs):
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=0, enabled=0, sessions=0, processed=0,
                                               published=0, pending=1, failed=0, last_sync=None))
        return httpx.Response(200, json=[job] if url.endswith("/jobs") else job)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    app.sidebar.radio[0].set_value("Historial").run()

    assert not app.exception
    assert app.warning[0].value == "Último error: MOODLE_CATALOG_READY_TIMEOUT"
    assert list(app.dataframe[0].value.columns)[:4] == ["created_at", "kind", "status", "error_code"]
    assert any("2026-10-17T04:42:00" in element.value for element in app.markdown)


def test_history_displays_academic_validation_reason_and_location(monkeypatch):
    from streamlit.testing.v1 import AppTest

    job = {"id": "bad-output", "kind": "process", "status": "REVIEW_REQUIRED", "stage": "codex",
           "error_code": "CODEX_OUTPUT_INVALID", "attempts": 1, "created_at": "2026-10-20T13:41:16",
           "started_at": "2026-10-20T13:41:16", "finished_at": "2026-10-20T13:44:14",
           "available_at": "2026-10-20T13:41:16", "model": None, "skill_version": "1.0",
           "result": {"validation": {"stage": "academic_lint", "reason": "Contenido administrativo o fecha.",
                      "findings": [{"field": "classes.0.markdown", "line": 12, "match": "examen del"}]}}}

    def request(method, url, **kwargs):
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=0, enabled=0, sessions=0, processed=0,
                                               published=0, pending=0, failed=1, last_sync=None))
        return httpx.Response(200, json=[job] if url.endswith("/jobs") else job)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    app.sidebar.radio[0].set_value("Historial").run()
    assert any("academic_lint" in message.value and "Contenido administrativo" in message.value for message in app.info)
    assert app.dataframe[1].value.iloc[0].to_dict() == {"field": "classes.0.markdown", "line": 12, "match": "examen del"}
    assert not app.exception


@pytest.mark.parametrize("jobs", [[], [{"id": "recordings-job", "module_id": 559}]])
def test_recording_discovery_reports_empty_selection_or_queued_jobs(monkeypatch, jobs):
    from streamlit.testing.v1 import AppTest

    requested = []

    def request(method, url, **kwargs):
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=28, enabled=len(jobs), sessions=0, processed=0,
                                               published=0, pending=0, failed=0, last_sync=None))
        requested.append((method, url))
        return httpx.Response(200, json=jobs)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    next(button for button in app.button if button.label == "Descubrir grabaciones de módulos habilitados").click().run()

    assert not app.exception
    assert len(requested) == 1 and requested[0][0] == "POST" and requested[0][1].endswith("/sync/recordings")
    if jobs:
        assert any("recordings-job" in message.value for message in app.success)
    else:
        assert any("No hay módulos habilitados" in message.value for message in app.info)


def test_session_action_requires_explicit_choice_and_preserves_target_after_refresh(monkeypatch):
    from streamlit.testing.v1 import AppTest

    module = {"id": 559, "program": "MIA", "cohort": "V1E4", "module_number": 14, "name": "MLOps",
              "enabled": False, "mode": "MANUAL", "auto_publish": False, "review_required": False,
              "proposed_assignments": None}
    sessions = [{"id": f"s{n}", "module_id": 559, "number": n, "week": (n + 1) // 2,
                 "class_in_week": 2 if n == 2 else 1, "class_date": f"2026-10-{day:02d}",
                 "youtube_url": "https://youtu.be/abcdefghijk", "transcript_status": "TRANSCRIPT_PENDING",
                 "processing_status": "PENDING", "publication_status": "PENDING", "selected": n == 3,
                 "excluded": False, "title": f"Grabación {n}", "error_code": None, "notion_url": None}
                for n, day in [(1, 5), (2, 9), (3, 12)]]
    sessions[2]["recordings"] = [{"position": n, "video_id": identifier, "url": f"https://www.youtube.com/watch?v={identifier}"}
                                  for n, identifier in [(1, "6dP-ykbwEIg"), (2, "_W__qxvQA_4")]]
    posted = []

    def request(method, url, **kwargs):
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=1, enabled=0, sessions=3, processed=0,
                                               published=0, pending=0, failed=0, last_sync=None))
        if url.endswith("/modules"):
            return httpx.Response(200, json=[module])
        if method == "GET" and url.endswith("/sessions"):
            return httpx.Response(200, json=sessions)
        if method == "POST":
            posted.append(url)
            sessions[2].update(transcript_status="TRANSCRIPT_READY", processing_status="PROCESSED")
            return httpx.Response(202, json={"id": "test-job", "session_id": "s3", "status": "QUEUED"})
        raise AssertionError((method, url))

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    app.sidebar.radio[0].set_value("Sesiones").run()
    choose = next(box for box in app.selectbox if box.label == "Sesión para una acción")
    assert choose.value is None  # A checkbox in the table must not silently target class 1.
    assert not any(button.label == "Procesar" for button in app.button)
    choose.select_index(2).run()
    assert any("12/10/2026" in message.value for message in app.info)
    links = app.get("link_button")
    assert [link.proto.label for link in links] == ["YouTube · Parte 1", "YouTube · Parte 2"]
    assert "6dP-ykbwEIg" in links[0].proto.url and "_W__qxvQA_4" in links[1].proto.url
    next(button for button in app.button if button.label == "Procesar").click().run()
    next(button for button in app.sidebar.button if button.label == "Actualizar").click().run()
    assert next(box for box in app.selectbox if box.label == "Sesión para una acción").value == "s3"
    next(button for button in app.button if button.label == "Reprocesar Codex").click().run()
    assert [url.rsplit("/", 2)[-2:] for url in posted] == [["s3", "process"], ["s3", "reprocess"]]
    table = app.dataframe[0].value
    assert table.loc[table["Sesión"] == 3, "Codex"].iloc[0] == "PROCESSED"
    assert table.loc[table["Sesión"] == 1, "Codex"].iloc[0] == "PENDING"
    assert not app.exception
    sessions[2]["discovery_status"] = "REVIEW_REQUIRED"
    next(button for button in app.sidebar.button if button.label == "Actualizar").click().run()
    assert not any(button.label == "Procesar" for button in app.button)
    assert any("demás clases" in warning.value for warning in app.warning)


@pytest.mark.parametrize("has_notes", [True, False])
def test_notes_view_previews_and_downloads_without_external_writes(monkeypatch, has_notes):
    from streamlit.testing.v1 import AppTest

    module = {"id": 559, "program": "MIA", "cohort": "V1E4", "module_number": 14, "name": "MLOps",
              "enabled": False, "mode": "MANUAL", "auto_publish": False, "review_required": False,
              "proposed_assignments": None}
    session = {"id": "s3", "module_id": 559, "number": 3, "week": 2, "class_in_week": 1,
               "class_date": "2026-10-12", "title": "Grabación 3", "transcript_status": "TRANSCRIPT_READY",
               "processing_status": "PROCESSED" if has_notes else "PENDING", "publication_status": "PENDING",
               "output_path": "/private/processed/job/bundle/notes.md" if has_notes else None}
    content = "# Clase 3: Despliegue\n\nContenido **académico**.\n\n```mermaid\ngraph LR\nA --> B\n```\n\n\\[\nx^2\n\\]"
    requested = []

    def request(method, url, **kwargs):
        assert method == "GET"
        requested.append(url)
        if url.endswith("/stats"):
            return httpx.Response(200, json=dict(modules=1, enabled=0, sessions=1, processed=int(has_notes),
                                               published=0, pending=0, failed=0, last_sync=None))
        if url.endswith("/modules"):
            return httpx.Response(200, json=[module])
        if url.endswith("/sessions"):
            return httpx.Response(200, json=[session])
        if url.endswith("/sessions/s3/notes"):
            return httpx.Response(200, json={"session_id": "s3", "number": 3, "week": 2, "class_in_week": 1,
                "class_date": "2026-10-12", "revision": 1, "processing_status": "PROCESSED",
                "filename": "MIA-559-sesion-3.md", "markdown": content})
        raise AssertionError(url)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "apps/dashboard/main.py").run()
    app.sidebar.radio[0].set_value("Apuntes").run()
    if has_notes:
        preview = content.replace("\\[\nx^2\n\\]", "$$\nx^2\n$$")
        assert any(element.value == preview for element in app.markdown)
        assert any(element.value == content for element in app.code)
        assert app.get("download_button")[0].proto.label == "Descargar Markdown"
        assert any(url.endswith("/sessions/s3/notes") for url in requested)
    else:
        assert any("todavía no tiene apuntes" in element.value for element in app.info)
        assert not any(url.endswith("/notes") for url in requested)
    assert not app.exception


def test_manual_forms_use_real_api_without_external_operations(tmp_path, monkeypatch):
    from datetime import date
    from urllib.parse import urlsplit
    from streamlit.testing.v1 import AppTest
    from sqlalchemy import select
    from test_api import client_for
    from academic_automation.database.models import AcademicModule, AcademicSession, ProcessingJob

    backend, client = client_for(tmp_path)
    mutations = []

    def request(method, url, **kwargs):
        assert url.startswith('http://127.0.0.1:8000/')
        path = urlsplit(url).path
        kwargs.pop('timeout', None)
        kwargs['headers'] = {'Authorization': 'Bearer admin-test'}
        if method != 'GET':
            mutations.append((method, path))
            assert path in {'/modules/197/sessions/manual', '/sessions/review-class/recordings'}
        return client.request(method, path, **kwargs)

    with client:
        with backend.state.sessions() as db:
            db.add(AcademicModule(id=197, program='DCC', cohort='V1E1', module_number=8,
                                 name='Investigación', enabled=False))
            db.commit()
            db.add(AcademicSession(id='review-class', module_id=197, resource_key='r4', title='Semana 4',
                class_date=date(2024, 6, 8), number=4, week=4, class_in_week=1,
                discovery_status='REVIEW_REQUIRED', error_code='MOODLE_MULTIPLE_VIDEOS'))
            db.commit()
        monkeypatch.setattr('httpx.request', request)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'apps/dashboard/main.py').run()
        app.sidebar.radio[0].set_value('Sesiones').run()
        next(box for box in app.selectbox if box.label == 'Sesión para una acción').select_index(0).run()
        assert not any(button.label == 'Procesar' for button in app.button)
        next(field for field in app.text_area if field.label.startswith('Enlaces YouTube de esta sesión')).set_value(
            'https://youtu.be/22PANKY-2Fg\nhttps://www.youtube.com/watch?v=wqH05pvQnQ4&t=1s')
        next(button for button in app.button if button.label == 'Guardar vínculo manual').click().run()
        assert not app.exception
        assert any(button.label == 'Procesar' for button in app.button)
        assert any('Grabaciones vinculadas' in notice.value for notice in app.success)
        next(box for box in app.selectbox if box.label == 'Número de sesión').select_index(0)
        next(field for field in app.date_input if field.label == 'Fecha de la clase').set_value(date(2024, 5, 18))
        next(field for field in app.text_area if field.label.startswith('Enlaces YouTube de la nueva sesión')).set_value(
            'https://www.youtube-nocookie.com/embed/6dP-ykbwEIg')
        next(button for button in app.button if button.label == 'Crear sesión con grabaciones').click().run()
        assert not app.exception
        assert mutations == [('PUT', '/sessions/review-class/recordings'), ('POST', '/modules/197/sessions/manual')]
        with backend.state.sessions() as db:
            sessions = list(db.scalars(select(AcademicSession).order_by(AcademicSession.number)))
            assert [s.number for s in sessions] == [1, 4]
            assert all(s.recordings_manual and s.processing_status == 'PENDING' for s in sessions)
            assert all(j.kind == 'manual_recordings' and j.status == 'COMPLETED' for j in db.scalars(select(ProcessingJob)))


def test_bulk_selection_and_buttons_use_backend_eligibility_without_altering_manual_selection(tmp_path, monkeypatch):
    from urllib.parse import urlsplit
    from streamlit.testing.v1 import AppTest
    from test_api import client_for
    from academic_automation.database.models import AcademicModule, AcademicSession, ProcessingJob, Recording
    from sqlalchemy import select
    from datetime import date

    backend, client = client_for(tmp_path)
    calls = []
    def request(method, url, **kwargs):
        path = urlsplit(url).path
        kwargs.pop('timeout', None)
        kwargs['headers'] = {'Authorization': 'Bearer admin-test'}
        if method != 'GET':
            calls.append((method, path))
            assert path in {'/modules/559/sessions/bulk/preview', '/modules/559/sessions/bulk'}
        return client.request(method, path, **kwargs)

    with client:
        with backend.state.sessions() as db:
            db.add(AcademicModule(id=559, program='MIA', cohort='V1E4', module_number=14, name='MLOps'))
            db.commit()
            for n, identifier in [(1, '22PANKY-2Fg'), (2, 'wqH05pvQnQ4')]:
                db.add(AcademicSession(id=f's{n}', module_id=559, resource_key=f'r{n}', title=f'Clase {n}',
                    class_date=date(2026, 10, n), number=n, week=1, class_in_week=n,
                    discovery_status='VIDEO_IDENTIFIED', selected=n==1))
            db.commit()
            for n, identifier in [(1, '22PANKY-2Fg'), (2, 'wqH05pvQnQ4')]:
                db.add(Recording(session_id=f's{n}', video_id=identifier, url=f'https://youtu.be/{identifier}', resource_url='r'))
            db.commit()
        monkeypatch.setattr('httpx.request', request)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'apps/dashboard/main.py').run()
        app.sidebar.radio[0].set_value('Sesiones').run()
        assert next(box for box in app.selectbox if box.label == 'Sesión para una acción').value is None
        chooser = next(box for box in app.multiselect if box.label == 'Sesiones para el lote')
        chooser.set_value(['s1', 's2']).run()
        assert not app.exception
        assert not next(button for button in app.button if button.label == 'Procesar lote').disabled
        assert next(button for button in app.button if button.label == 'Procesar / reprocesar Codex en lote').disabled
        assert next(button for button in app.button if button.label == 'Publicar / actualizar Notion en lote').disabled
        # Mixed states disable the entire group; changing the multiselect never PATCHes session.selected.
        with backend.state.sessions() as db:
            db.get(AcademicSession, 's2').processing_status = 'FAILED'
            db.commit()
        app.sidebar.button[0].click().run()
        assert next(button for button in app.button if button.label == 'Procesar lote').disabled
        assert any('mismo estado' in notice.value for notice in app.warning)
        with backend.state.sessions() as db:
            db.get(AcademicSession, 's2').processing_status = 'PENDING'
            db.commit()
        app.sidebar.button[0].click().run()
        next(button for button in app.button if button.label == 'Procesar lote').click().run()
        assert not app.exception
        assert any('2 trabajos' in notice.value for notice in app.success)
        assert next(button for button in app.button if button.label == 'Procesar lote').disabled
        with backend.state.sessions() as db:
            assert [(s.id, s.selected) for s in db.scalars(select(AcademicSession).order_by(AcademicSession.id))] == [('s1', True), ('s2', False)]
            assert len(list(db.scalars(select(ProcessingJob).where(ProcessingJob.kind == 'process')))) == 2
        assert [path for method, path in calls if path.endswith('/bulk')] == ['/modules/559/sessions/bulk']
