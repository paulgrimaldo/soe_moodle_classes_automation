import json
from datetime import date

import pytest
from sqlalchemy import select, func

from academic_automation.core.errors import Conflict
from academic_automation.database.models import AcademicSession, Recording
from academic_automation.services.catalog import sync_recordings
from test_foundation import module


def multipart():
    return {"resource_key": "/virtual/mod/page/view.php:11143", "title": "Semana 2", "date": date(2024, 5, 25),
            "resource_url": "https://soe.uagrm.edu.bo/virtual/mod/page/view.php?id=11143",
            "video_id": "6dP-ykbwEIg", "url": "https://www.youtube.com/watch?v=6dP-ykbwEIg",
            "videos": [{"video_id": identifier, "url": f"https://www.youtube.com/watch?v={identifier}"}
                       for identifier in ("6dP-ykbwEIg", "_W__qxvQA_4")]}


def test_parts_are_one_stable_session_and_two_ordered_recordings(db):
    m = module(db)
    item = multipart()
    assert sync_recordings(db, m, [item]) == 1
    sid = db.scalar(select(AcademicSession.id))
    assert sync_recordings(db, m, [item]) == 0
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
    assert [(p.position, p.video_id) for p in db.scalars(select(Recording).order_by(Recording.position))] == [
        (1, "6dP-ykbwEIg"), (2, "_W__qxvQA_4")]
    assert db.scalar(select(AcademicSession.id)) == sid
    swapped = json.loads(json.dumps(item, default=str))
    swapped["date"] = item["date"]
    swapped["videos"].reverse()
    with pytest.raises(Conflict, match="RECORDING_VIDEO_CHANGED"):
        sync_recordings(db, m, [swapped])
    db.rollback()
    assert db.scalar(select(Recording).where(Recording.position == 1)).video_id == "6dP-ykbwEIg"


def test_video_cannot_be_reused_as_part_of_another_session(db):
    m = module(db)
    item = multipart()
    sync_recordings(db, m, [item])
    duplicate = {**item, "resource_key": "alias"}
    assert sync_recordings(db, m, [duplicate]) == 0
    with pytest.raises(Conflict, match="VIDEO_LINKED_TO_OTHER_SESSION"):
        sync_recordings(db, m, [{**item, "resource_key": "different", "videos": item["videos"][1:]}])


def test_multipart_migration_preserves_existing_single_recording(tmp_path, monkeypatch):
    from alembic.config import Config
    from alembic import command
    from academic_automation.database.session import make_engine, factory, seed
    from pathlib import Path

    monkeypatch.setenv("ACADEMIC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ACADEMIC_DATABASE_URL", f"sqlite:///{tmp_path / 'migrations.sqlite3'}")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "fa6dafc81276")
    engine = make_engine(f"sqlite:///{tmp_path / 'migrations.sqlite3'}")
    with factory(engine)() as db:
        seed(db)
        # Insert against the historical schema, independently of today's ORM columns.
        from sqlalchemy import MetaData, Table
        from academic_automation.database.models import uid, now
        historical_modules = Table("academic_modules", MetaData(), autoload_with=db.get_bind())
        db.execute(historical_modules.insert().values(id=559, program="MIA", cohort="V1E4", module_number=14,
            name="MLOps", enabled=False, mode="MANUAL", auto_publish=False, review_required=False))
        sid = uid()
        historical = Table("academic_sessions", MetaData(), autoload_with=db.get_bind())
        db.execute(historical.insert().values(id=sid, module_id=559, resource_key="r1", title="Grabación",
            class_date=date(2024, 5, 25), discovered_at=now(), manual_assignment=False, selected=False,
            excluded=False, discovery_status="DISCOVERED", transcript_status="TRANSCRIPT_PENDING",
            processing_status="PENDING", publication_status="PENDING", revision=0))
        from sqlalchemy import text
        db.execute(text("INSERT INTO recordings (session_id,video_id,url,resource_url) VALUES (:sid,'6dP-ykbwEIg','u','r')"), {"sid": sid})
        db.commit()
    command.upgrade(cfg, "head")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from academic_automation.database.models import Base
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    with factory(engine)() as db:
        first = db.scalar(select(Recording))
        assert first.session_id == sid and first.position == 1 and first.video_id == "6dP-ykbwEIg"
        assert db.get(AcademicSession, sid).recordings_manual is False
        db.add(Recording(session_id=sid, position=2, video_id="_W__qxvQA_4", url="u2", resource_url="r"))
        db.commit()
    with pytest.raises(RuntimeError, match="downgrade would lose"):
        command.downgrade(cfg, "fa6dafc81276")
    engine.dispose()
