"""Manual catalog read/sync using fresh host code, without the resident worker."""

import asyncio

from sqlalchemy import select, text

from academic_automation.core.errors import Conflict, StageError
from academic_automation.database.models import AcademicModule, ProcessingJob, ExecutionLog, now
from academic_automation.database.session import factory, make_engine
from academic_automation.moodle.client import MoodleClient
from academic_automation.orchestration.queue import ACTIVE
from academic_automation.services.catalog import recording_sync_result, sync_recordings


async def sync_module_now(settings, module_id):
    engine = make_engine(settings.database_url)
    started = now()
    try:
        with factory(engine)() as db:
            if db.get(AcademicModule, module_id) is None:
                raise StageError("MODULE_NOT_FOUND")
            if db.scalar(select(ProcessingJob.id).where(ProcessingJob.module_id == module_id,
                                                       ProcessingJob.status.in_(ACTIVE))):
                raise Conflict("MODULE_HAS_ACTIVE_JOBS")
        # Discovery only: no download, Codex, dispatch or publication. Moodle's
        # browser lock also applies while the resident worker is running.
        items = await asyncio.wait_for(MoodleClient(settings).recordings(module_id, allow_partial=True),
                                       timeout=settings.moodle_timeout * 10)
        with factory(engine)() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            if db.scalar(select(ProcessingJob.id).where(ProcessingJob.module_id == module_id,
                                                       ProcessingJob.status.in_(ACTIVE))):
                raise Conflict("MODULE_HAS_ACTIVE_JOBS")
            module = db.get(AcademicModule, module_id)
            count = sync_recordings(db, module, items, commit=False)
            result = recording_sync_result(items, count)
            status = "REVIEW_REQUIRED" if result.get("reviews") else "COMPLETED"
            error = "MOODLE_MULTIPLE_VIDEOS" if result.get("reviews") else None
            # Record only a terminal discovery job, so the resident worker can
            # never claim this command or repeat a partially completed read.
            job = ProcessingJob(kind="recordings", active_key=f"recordings:{module_id}", module_id=module_id,
                status=status, stage="moodle", attempts=1, started_at=started, finished_at=now(),
                result=result, error_code=error)
            db.add(job)
            db.flush()
            db.add(ExecutionLog(job_id=job.id, stage="moodle", event="manual_sync",
                                message=error or "MANUAL_RECORDING_SYNC_COMPLETED"))
            db.commit()
            return {"job_id": job.id, "module_id": module_id, "status": status, "error_code": error,
                    **result, "processing_started": False, "notion_writes": False}
    finally:
        engine.dispose()
