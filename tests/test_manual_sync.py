from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.database.models import Base, AcademicSession, ProcessingJob, Recording
from academic_automation.database.session import make_engine, factory, seed
from academic_automation.orchestration.manual_sync import sync_module_now
from test_foundation import module
from test_recording_parts import multipart


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'manual.sqlite3'}")
    settings.prepare()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with factory(engine)() as db:
        seed(db)
        module(db)
    return settings, engine


async def test_manual_sync_saves_ready_class_and_review_without_model_or_publication(tmp_path, monkeypatch):
    settings, engine = setup(tmp_path)
    good = multipart()
    review = {"resource_key": "r4", "title": "Semana 4", "date": date(2024, 6, 8), "resource_url": "r",
              "discovery_error": "MOODLE_MULTIPLE_VIDEOS", "video_candidates": [
                  {"video_id": "22PANKY-2Fg", "url": "https://youtu.be/22PANKY-2Fg"},
                  {"video_id": "wqH05pvQnQ4", "url": "https://youtu.be/wqH05pvQnQ4"}]}
    read = AsyncMock(return_value=[good, review])
    monkeypatch.setattr("academic_automation.moodle.client.MoodleClient.recordings", read)
    one = await sync_module_now(settings, 559)
    two = await sync_module_now(settings, 559)
    assert one["status"] == "REVIEW_REQUIRED" and one["new_sessions"] == 2
    assert two["new_sessions"] == 0 and two["recordings_found"] == 2
    assert not one["processing_started"] and not one["notion_writes"]
    read.assert_awaited_with(559, allow_partial=True)
    with factory(engine)() as db:
        assert len(list(db.scalars(select(AcademicSession)))) == 2
        assert len(list(db.scalars(select(Recording)))) == 2
        assert db.get(ProcessingJob, one["job_id"]).result["reviews"][0]["resource_key"] == "r4"
        assert not list(db.scalars(select(ProcessingJob).where(ProcessingJob.kind.in_(["process", "publish"]))))
    engine.dispose()


async def test_manual_sync_does_not_interfere_with_active_module_job(tmp_path, monkeypatch):
    settings, engine = setup(tmp_path)
    read = AsyncMock()
    monkeypatch.setattr("academic_automation.moodle.client.MoodleClient.recordings", read)
    with factory(engine)() as db:
        db.add(ProcessingJob(kind="recordings", active_key="recordings:559", module_id=559))
        db.commit()
    with pytest.raises(Conflict, match="MODULE_HAS_ACTIVE_JOBS"):
        await sync_module_now(settings, 559)
    read.assert_not_awaited()
    engine.dispose()
