from datetime import date

import pytest
from sqlalchemy import select

from academic_automation.core.errors import Conflict
from academic_automation.database.models import AcademicModule, AcademicSession, NotionPage, NotionSection, ProcessingJob
from fakes import FakeNotion
from test_api import client_for


def setup_case(tmp_path, monkeypatch):
    app, client = client_for(tmp_path)
    remote = FakeNotion()
    parent = remote.add_page()
    old = remote.add_page(parent, "Semana 2")
    replacement = remote.add_page(parent, "Semana 2")
    with app.state.sessions() as db:
        # Tests normally seed on lifespan entry; this setup runs before it.
        from academic_automation.database.session import seed
        seed(db)
        db.add(AcademicModule(id=559, program="MIA", cohort="V1E4", module_number=14, name="MLOps"))
        db.commit()
        db.add_all([NotionPage(module_id=559, week=0, page_id=parent, url="parent"),
                    NotionPage(module_id=559, week=2, page_id=old, url="old", divider_id="old-divider"),
                    AcademicSession(id="s3", module_id=559, resource_key="r3", title="Grabación",
                        class_date=date(2026, 10, 12), number=3, week=2, class_in_week=1,
                        transcript_status="TRANSCRIPT_READY", processing_status="PROCESSED",
                        publication_status="REVIEW_REQUIRED", error_code="NOTION_OBJECT_UNAVAILABLE",
                        output_path="/saved/notes.md", content_hash="unchanged")])
        db.commit()
        db.add(NotionSection(session_id="s3", page_id=old, block_ids=["old-block"], remote_hash="old-hash", pending=True))
        db.commit()
    original_page = remote.page

    async def page(identifier):
        if identifier == old and identifier not in remote.pages:
            raise Conflict("NOTION_OBJECT_UNAVAILABLE")
        return await original_page(identifier)

    remote.page = page
    del remote.pages[old]
    monkeypatch.setattr("academic_automation.notion.client.NotionClient", lambda _: remote)
    payload = {"page_id": replacement, "week": 2, "previous_page_id": old, "acknowledge_replacement": True}
    return app, client, remote, parent, old, replacement, payload


def test_relink_deleted_week_archives_associations_and_preserves_notes(tmp_path, monkeypatch):
    app, client, remote, _, old, replacement, payload = setup_case(tmp_path, monkeypatch)
    with client:
        response = client.post("/notion/modules/559/relink", headers={"Authorization": "Bearer admin-test"}, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["affected_sessions"] == ["s3"]
        assert remote.writes == 0
        with app.state.sessions() as db:
            page = db.scalar(select(NotionPage).where(NotionPage.week == 2))
            assert page.page_id == replacement and page.divider_id is None
            assert db.scalar(select(NotionSection)) is None
            s = db.get(AcademicSession, "s3")
            assert (s.transcript_status, s.processing_status, s.publication_status) == (
                "TRANSCRIPT_READY", "PROCESSED", "PENDING")
            assert s.output_path == "/saved/notes.md" and s.content_hash == "unchanged" and s.error_code is None
            audit = db.get(ProcessingJob, response.json()["audit_job_id"])
            assert audit.status == "COMPLETED" and audit.kind == "notion_relink"
            assert audit.result["previous_pages"][0]["page_id"] == old
            assert audit.result["previous_sections"][0]["block_ids"] == ["old-block"]
        again = client.post("/notion/modules/559/relink", headers={"Authorization": "Bearer admin-test"}, json=payload)
        assert again.status_code == 200 and not again.json()["changed"]
        with app.state.sessions() as db:
            assert len(list(db.scalars(select(ProcessingJob)))) == 1


@pytest.mark.parametrize("problem,expected", [
    ("old_available", "NOTION_PREVIOUS_PAGE_STILL_AVAILABLE"),
    ("wrong_parent", "NOTION_WEEK_PARENT_CHANGED"),
    ("network", "NOTION_NETWORK_ERROR"),
    ("queued_job", "MODULE_HAS_ACTIVE_JOBS"),
])
def test_relink_rejection_preserves_old_associations(tmp_path, monkeypatch, problem, expected):
    from academic_automation.core.errors import StageError

    app, client, remote, parent, old, replacement, payload = setup_case(tmp_path, monkeypatch)
    if problem == "old_available":
        remote.pages[old] = {"id": old, "parent": {"type": "page_id", "page_id": parent}}
    elif problem == "wrong_parent":
        remote.pages[replacement]["parent"]["page_id"] = remote.add_page()
    elif problem == "network":
        page = remote.page

        async def error(identifier):
            if identifier == old:
                raise StageError("NOTION_NETWORK_ERROR", retryable=True)
            return await page(identifier)

        remote.page = error
    else:
        with app.state.sessions() as db:
            db.add(ProcessingJob(kind="publish", module_id=559, session_id="s3", active_key="session:s3"))
            db.commit()
    with client:
        response = client.post("/notion/modules/559/relink", headers={"Authorization": "Bearer admin-test"}, json=payload)
        assert response.status_code == 409 and response.json()["detail"] == expected
        with app.state.sessions() as db:
            assert db.scalar(select(NotionPage).where(NotionPage.week == 2)).page_id == old
            assert db.scalar(select(NotionSection)).pending
            assert db.get(AcademicSession, "s3").publication_status == "REVIEW_REQUIRED"
        assert remote.writes == 0


def test_relink_module_clears_old_weeks_but_not_academic_artifacts(tmp_path, monkeypatch):
    app, client, remote, parent, old, _, _ = setup_case(tmp_path, monkeypatch)
    replacement = remote.add_page(title="MLOps nuevo")
    remote.pages[parent]["in_trash"] = True
    original = remote.page

    async def page(identifier):
        if identifier == parent:
            raise Conflict("NOTION_PAGE_IN_TRASH")
        return await original(identifier)

    remote.page = page
    with client:
        response = client.post("/notion/modules/559/relink", headers={"Authorization": "Bearer admin-test"}, json={
            "page_id": replacement, "previous_page_id": parent, "week": 0, "acknowledge_replacement": True})
        assert response.status_code == 200, response.text
        with app.state.sessions() as db:
            pages = list(db.scalars(select(NotionPage)))
            assert len(pages) == 1 and pages[0].week == 0 and pages[0].page_id == replacement
            assert db.scalar(select(NotionSection)) is None
            assert db.get(AcademicSession, "s3").processing_status == "PROCESSED"
            audit = db.get(ProcessingJob, response.json()["audit_job_id"])
            assert {p["page_id"] for p in audit.result["previous_pages"]} == {parent, old}
        assert remote.writes == 0


def test_relink_requires_explicit_ack_admin_and_current_association(tmp_path, monkeypatch):
    app, client, remote, _, _, _, payload = setup_case(tmp_path, monkeypatch)
    with client:
        url = "/notion/modules/559/relink"
        assert client.post(url, headers={"Authorization": "Bearer n8n-test"}, json=payload).status_code == 403
        admin = {"Authorization": "Bearer admin-test"}
        assert client.post(url, headers=admin, json={**payload, "acknowledge_replacement": False}).status_code == 422
        stale = client.post(url, headers=admin, json={**payload, "previous_page_id": remote.add_page()})
        assert stale.status_code == 409 and stale.json()["detail"] == "NOTION_LINK_CHANGED"
        assert remote.writes == 0


def test_publish_after_relink_reuses_notes_and_new_destination(tmp_path, monkeypatch):
    import asyncio
    import json

    from academic_automation.core.security import digest
    from academic_automation.orchestration.worker import Worker

    app, client, remote, _, _, replacement, payload = setup_case(tmp_path, monkeypatch)
    app.state.settings.publication_enabled = True
    content = "# Clase 3: Tema\n\n\\[\nx^2\n\\]\n"
    source = tmp_path / "bundle" / "notes.md"
    source.parent.mkdir()
    source.write_text(content)
    (source.parent / "metadata.json").write_text(json.dumps({"status": "ready", "content_sha256": digest(content)}))
    with app.state.sessions() as db:
        s = db.get(AcademicSession, "s3")
        s.output_path, s.content_hash = str(source), digest(content)
        db.commit()
    worker = Worker(app.state.settings, app.state.sessions, notion_factory=lambda: remote,
                    transcripts=object(), processor=object())
    with client:
        headers = {"Authorization": "Bearer admin-test"}
        assert client.post("/notion/modules/559/relink", headers=headers, json=payload).status_code == 200
        assert remote.writes == 0
        response = client.post("/sessions/s3/publish", headers=headers)
        assert response.status_code == 202
        assert asyncio.run(worker.tick())
        with app.state.sessions() as db:
            assert db.get(ProcessingJob, response.json()["id"]).status == "COMPLETED"
            s = db.get(AcademicSession, "s3")
            assert s.publication_status == "PUBLISHED" and s.content_hash == digest(content)
            section = db.scalar(select(NotionSection))
            assert section.page_id == replacement and not section.pending
            assert any(remote.blocks[i]["type"] == "equation" for i in section.block_ids)
        writes = remote.writes
        client.post("/sessions/s3/publish", headers=headers)
        assert asyncio.run(worker.tick())
        assert remote.writes == writes
