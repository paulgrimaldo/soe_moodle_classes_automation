import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.database.models import AcademicSession, NotionPage, NotionSection
from academic_automation.notion.sections import NotionSectionManager
from academic_automation.orchestration.worker import Worker
from academic_automation.services.catalog import sync_recordings
from fakes import FakeNotion
from test_foundation import module
from test_moodle import recording
from test_notion import session
from test_worker import FakeProcessor, FakeTranscript, run_job


async def test_codex_failure_retains_transcript_for_retry(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    sync_recordings(db, m, [recording("r1", 5, "abcdefghijk")])
    s = db.scalar(select(AcademicSession))
    transcripts = FakeTranscript(tmp_path)
    class BrokenCodex:
        async def process(self, request):
            raise StageError("CODEX_EXEC_FAILED")
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=transcripts, processor=BrokenCodex())
    job = await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    assert job.status == "FAILED" and s.transcript_status == "TRANSCRIPT_READY"
    assert s.processing_status == "FAILED" and s.publication_status == "PENDING"
    worker.processor = FakeProcessor(tmp_path)
    retry = await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    assert retry.status == "COMPLETED" and transcripts.calls == 1


async def test_partial_notion_write_blocks_second_append(db, tmp_path):
    m = module(db)
    fake = FakeNotion()
    pid = fake.add_page()
    page = NotionPage(module_id=m.id, week=1, page_id=pid, url="p")
    db.add(page)
    s = session(db, m, tmp_path, 1)
    manager = NotionSectionManager(db, fake)
    original_append = fake.append
    async def uncertain(*args, **kwargs):
        await original_append(*args, **kwargs)
        raise StageError("NOTION_WRITE_OUTCOME_UNKNOWN", review=True)
    fake.append = uncertain
    with pytest.raises(StageError, match="NOTION_WRITE_OUTCOME_UNKNOWN"):
        await manager.publish(s, page)
    section = db.scalar(select(NotionSection).where(NotionSection.session_id == s.id))
    assert section.pending
    writes = fake.writes
    fake.append = original_append
    with pytest.raises(StageError, match="NOTION_PARTIAL_WRITE_REQUIRES_REVIEW"):
        await manager.publish(s, page)
    assert fake.writes == writes


async def test_worker_persists_safe_codex_validation_diagnostic(db, tmp_path):
    from academic_automation.academic.output import CodexOutputError

    m = module(db)
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    sync_recordings(db, m, [recording("r1", 5, "abcdefghijk")])
    s = db.scalar(select(AcademicSession))
    diagnostic = {"stage": "academic_lint", "reason": "Se detectó contenido administrativo o una fecha en la salida.",
                  "findings": [{"field": "classes.0.markdown", "line": 12, "match": "examen del"}]}

    class RejectedOutput:
        async def process(self, request):
            raise CodexOutputError(diagnostic)

    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=FakeTranscript(tmp_path), processor=RejectedOutput())
    job = await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    assert job.status == "REVIEW_REQUIRED" and job.error_code == "CODEX_OUTPUT_INVALID"
    assert job.result["validation"] == diagnostic
    assert s.transcript_status == "TRANSCRIPT_READY" and s.output_path is None
