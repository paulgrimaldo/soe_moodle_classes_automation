from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from academic_automation.core.config import Settings
from academic_automation.database.models import AcademicModule, AcademicSession, NotionPage
from academic_automation.orchestration.worker import Worker
from academic_automation.services.catalog import sync_recordings
from fakes import FakeNotion
from test_moodle import recording
from test_worker import FakeProcessor, FakeTranscript, run_job


async def test_eight_dcc_classes_use_eight_weeks(db, tmp_path):
    settings = Settings(data_dir=tmp_path, publication_enabled=True)
    settings.prepare()
    m = AcademicModule(id=532, program="DCC", cohort="V1E1", module_number=11, name="Inteligencia artificial")
    db.add(m)
    db.commit()
    sync_recordings(db, m, [recording(f"r{n}", n, f"video{n:06d}") for n in range(1, 9)])
    fake = FakeNotion()
    parent = fake.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="module"))
    db.commit()
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=FakeTranscript(tmp_path),
                    processor=FakeProcessor(tmp_path), notion_factory=lambda: fake)
    sessions = list(db.scalars(select(AcademicSession).order_by(AcademicSession.number)))
    for s in sessions:
        assert s.number == s.week and s.class_in_week == 1
        assert (await run_job(worker, db, "process", session_id=s.id, module_id=m.id)).status == "COMPLETED"
        assert (await run_job(worker, db, "publish", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert len(fake.pages) == 9  # Module + eight weeks, with no per-class pages.
    assert all(s.publication_status == "PUBLISHED" for s in sessions)
