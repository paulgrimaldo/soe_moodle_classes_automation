from datetime import date

from fastapi.testclient import TestClient

from apps.api.main import create_app
from academic_automation.core.config import Settings
from academic_automation.database.models import AcademicModule, AcademicSession, Base


def client_for(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'api.sqlite3'}",
                        admin_token="admin-test", n8n_token="n8n-test")
    app = create_app(settings)
    with app.state.sessions() as db:
        Base.metadata.create_all(db.get_bind())
    return app, TestClient(app)


def test_auth_and_queue_api(tmp_path):
    app, client = client_for(tmp_path)
    with client:
        assert client.get("/health").status_code == 200
        assert client.get("/modules").status_code == 401
        n8n = {"Authorization": "Bearer n8n-test"}
        admin = {"Authorization": "Bearer admin-test"}
        one = client.post("/sync/catalog", headers=n8n)
        assert one.status_code == 202
        assert client.post("/sync/catalog", headers=n8n).json()["id"] == one.json()["id"]
        with app.state.sessions() as db:
            db.add(AcademicModule(id=559, program="MIA", cohort="V1E4", module_number=14, name="MLOps"))
            db.commit()
        assert client.patch("/modules/559", json={"enabled": True}, headers=n8n).status_code == 403
        assert client.patch("/modules/559", json={"enabled": True, "mode": "NEW_ONLY"}, headers=admin).status_code == 200
        watermark = client.get("/modules/559", headers=admin).json()["activated_at"]
        client.patch("/modules/559", json={"enabled": False}, headers=admin)
        assert client.get("/modules/559", headers=admin).json()["activated_at"] == watermark
        assert client.patch("/modules/559", json={"mode": "INVALID"}, headers=admin).status_code == 422
        assert client.get("/modules/12345", headers=admin).status_code == 404


def test_dispatch_exclusions_manual_selection_and_publication_gate(tmp_path):
    app, client = client_for(tmp_path)
    headers = {"Authorization": "Bearer admin-test"}
    with client:
        with app.state.sessions() as db:
            db.add(AcademicModule(id=559, program="MIA", cohort="V1E4", module_number=14,
                                name="MLOps", enabled=True, mode="MANUAL"))
            db.commit()
            for n in (1, 2):
                db.add(AcademicSession(id=f"s{n}", module_id=559, resource_key=f"r{n}", title="Clase",
                                      class_date=date(2026, 10, n), number=n, week=1, class_in_week=n,
                                      discovery_status="VIDEO_IDENTIFIED", selected=n == 1))
            db.commit()
        result = client.post("/processing/dispatch", headers=headers).json()
        assert [j["session_id"] for j in result] == ["s1"]
        assert len(client.post("/processing/dispatch", headers=headers).json()) == 1
        assert client.post("/sessions/s2/publish", headers=headers).status_code == 409
        assert client.patch("/modules/559", json={"auto_publish": True}, headers=headers).status_code == 409
        client.patch("/sessions/s2", json={"excluded": True}, headers=headers)
        assert client.post("/sessions/s2/process", headers=headers).status_code == 409
        client.patch("/modules/559", json={"enabled": False}, headers=headers)
        assert client.post("/processing/dispatch", headers=headers).json() == []


def test_session_api_returns_all_parts_in_order(tmp_path):
    from academic_automation.database.models import Recording

    app, client = client_for(tmp_path)
    with client:
        with app.state.sessions() as db:
            db.add(AcademicModule(id=197, program="DCC", cohort="V1E1", module_number=8, name="Investigación"))
            db.commit()
            db.add(AcademicSession(id="s", module_id=197, resource_key="r", title="Grabación", class_date=date(2024, 5, 25)))
            db.commit()
            db.add_all([Recording(session_id="s", position=n, video_id=identifier, url=f"https://youtu.be/{identifier}", resource_url="r")
                        for n, identifier in [(2, "_W__qxvQA_4"), (1, "6dP-ykbwEIg")]])
            db.commit()
        response = client.get("/modules/197/sessions", headers={"Authorization": "Bearer admin-test"})
        assert response.status_code == 200
        entry = response.json()[0]
        assert [part["video_id"] for part in entry["recordings"]] == ["6dP-ykbwEIg", "_W__qxvQA_4"]
        assert entry["youtube_url"] == "https://youtu.be/6dP-ykbwEIg"
        with app.state.sessions() as db:
            s = db.get(AcademicSession, "s")
            s.discovery_status, s.week, s.number = "REVIEW_REQUIRED", 1, 1
            db.commit()
        response = client.post("/sessions/s/process", headers={"Authorization": "Bearer admin-test"})
        assert response.status_code == 409 and "revisar sus videos" in response.json()["detail"]
