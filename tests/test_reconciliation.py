from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from academic_automation.core.config import Settings
from academic_automation.database.models import AcademicSession, NotionPage, NotionSection
from academic_automation.orchestration.worker import Worker
from academic_automation.services.catalog import sync_recordings
from fakes import FakeNotion
from test_foundation import module
from test_moodle import recording
from test_worker import FakeProcessor, FakeTranscript, run_job


async def test_confirm_late_recording_moves_published_sections(db, tmp_path):
    settings = Settings(data_dir=tmp_path, publication_enabled=True)
    settings.prepare()
    m = module(db)
    sync_recordings(db, m, [recording("r2", 9, "abcdefghijk"), recording("r3", 12, "bcdefghijkl")])
    fake = FakeNotion()
    parent = fake.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="module"))
    db.commit()
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=FakeTranscript(tmp_path),
                    processor=FakeProcessor(tmp_path), notion_factory=lambda: fake)
    original = list(db.scalars(select(AcademicSession).order_by(AcademicSession.number)))
    for s in original:
        await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
        await run_job(worker, db, "publish", session_id=s.id, module_id=m.id)
    sync_recordings(db, m, [recording("r1", 5, "cdefghijklm")])
    assert m.review_required and original[0].number == 1
    job = await run_job(worker, db, "reconcile", module_id=m.id)
    assert job.status == "COMPLETED", job.error_code
    assert not m.review_required
    assert original[0].number == 2 and original[0].week == 1
    assert original[1].number == 3 and original[1].week == 2
    assert Path(original[1].output_path).read_text().startswith("# Clase 3:")
    assert len(fake.pages) == 3  # existing module + weeks 1 and 2
    assert db.scalar(select(NotionSection).where(NotionSection.session_id == original[1].id)).page_id != db.scalar(
        select(NotionSection).where(NotionSection.session_id == original[0].id)).page_id


async def test_unpublished_reconcile_needs_no_notion_credentials(db, tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    m = module(db)
    sync_recordings(db, m, [recording("r2", 9, "abcdefghijk")])
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=FakeTranscript(tmp_path), processor=FakeProcessor(tmp_path))
    s = db.scalar(select(AcademicSession))
    await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    sync_recordings(db, m, [recording("r1", 5, "bcdefghijkl")])
    assert m.review_required
    job = await run_job(worker, db, "reconcile", module_id=m.id)
    assert job.status == "COMPLETED", job.error_code
    assert s.number == 2
