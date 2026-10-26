from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from academic_automation.database.models import AcademicSession, ExecutionLog, ProcessingJob, now

ACTIVE = ("QUEUED", "RUNNING", "RETRY_WAIT")


def enqueue(db, kind: str, *, session_id: str | None = None, module_id: int | None = None,
            automatic: bool = False) -> ProcessingJob:
    # All session operations share a key: publication and generation cannot race.
    key = f"session:{session_id}" if session_id else f"{kind}:{module_id or 'all'}"
    existing = db.scalar(select(ProcessingJob).where(ProcessingJob.active_key == key,
                                                   ProcessingJob.status.in_(ACTIVE)))
    if existing:
        return existing
    job = ProcessingJob(kind=kind, active_key=key, session_id=session_id,
                        module_id=module_id, automatic=automatic)
    try:
        db.add(job)
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(ProcessingJob).where(ProcessingJob.active_key == key,
                                                   ProcessingJob.status.in_(ACTIVE)))
    return job


def claim(db) -> ProcessingJob | None:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.status.in_(("QUEUED", "RETRY_WAIT")),
                                               ProcessingJob.available_at <= now())
                    .order_by(ProcessingJob.created_at).limit(1))
    if not job:
        return None
    result = db.execute(update(ProcessingJob).where(ProcessingJob.id == job.id,
                                                   ProcessingJob.status.in_(("QUEUED", "RETRY_WAIT")))
                        .values(status="RUNNING", attempts=ProcessingJob.attempts + 1,
                                started_at=now(), finished_at=None))
    db.commit()
    if result.rowcount != 1:
        return None
    db.refresh(job)
    return job


def recover(db) -> int:
    jobs = list(db.scalars(select(ProcessingJob).where(ProcessingJob.status == "RUNNING")))
    for job in jobs:
        if job.stage in {"notion", "reconcile"}:
            job.status, job.error_code = "REVIEW_REQUIRED", "INTERRUPTED_REMOTE_WRITE"
            if job.session_id:
                db.get(AcademicSession, job.session_id).publication_status = "REVIEW_REQUIRED"
        else:
            job.status, job.available_at = "QUEUED", now()
        db.add(ExecutionLog(job_id=job.id, stage=job.stage or "worker", event="recovery",
                            message=job.error_code or "REQUEUED_AFTER_RESTART"))
    db.commit()
    return len(jobs)
