"""Local, audited recording associations. Never downloads or publishes content."""

from sqlalchemy import select, text

from academic_automation.core.errors import Conflict, StageError
from academic_automation.database.models import (
    AcademicModule, AcademicSession, ExecutionLog, NotionSection, ProcessingJob,
    Recording, TranscriptArtifact, now, uid,
)
from academic_automation.moodle.parsing import youtube
from academic_automation.orchestration.queue import ACTIVE
from academic_automation.services.catalog import assignment


def module_idle(db, module_id):
    session_ids = select(AcademicSession.id).where(AcademicSession.module_id == module_id)
    if db.scalar(select(ProcessingJob.id).where(
                                               (ProcessingJob.module_id == module_id) | ProcessingJob.session_id.in_(session_ids),
                                               ProcessingJob.status.in_(ACTIVE))):
        raise Conflict("MODULE_HAS_ACTIVE_JOBS")


def apply_links(db, settings, session, urls):
    old = list(db.scalars(select(Recording).where(Recording.session_id == session.id).order_by(Recording.position)))
    ids = [youtube(url)[0] for url in urls]  # Validated by RecordingLinks.
    previous = [part.video_id for part in old]
    changed = previous != ids
    foreign = db.scalar(select(Recording.id).where(Recording.video_id.in_(ids), Recording.session_id != session.id))
    if foreign:
        raise Conflict("VIDEO_LINKED_TO_OTHER_SESSION")
    if changed:
        directory = settings.data_dir / "transcripts" / session.id
        if (session.output_path or session.content_hash or session.revision
                or session.processing_status in {"PROCESSED", "PROCESSING"}
                or session.publication_status in {"PUBLISHED", "PUBLISHING"}
                or db.scalar(select(TranscriptArtifact.id).where(TranscriptArtifact.session_id == session.id))
                or db.scalar(select(NotionSection.id).where(NotionSection.session_id == session.id))
                or (directory.exists() and any(path.is_file() for path in directory.rglob("*")))):
            raise Conflict("MANUAL_RECORDINGS_ARTIFACTS_EXIST")
    pin_changed = not session.recordings_manual
    if changed:
        for part in old:
            db.delete(part)
        db.flush()  # Release video and position uniqueness before inserting replacements.
        resource_url = (old[0].resource_url if old else "") or urls[0]
        for position, (identifier, url) in enumerate(zip(ids, urls), 1):
            db.add(Recording(session_id=session.id, position=position, video_id=identifier,
                             url=url, resource_url=resource_url))
        session.transcript_status, session.processing_status = "TRANSCRIPT_PENDING", "PENDING"
        session.publication_status = "PENDING"
        session.error_code = None
    session.recordings_manual = True
    session.discovery_status = "VIDEO_IDENTIFIED"
    if session.error_code in {"MOODLE_MULTIPLE_VIDEOS", "RECORDING_REQUIRES_REVIEW", "MOODLE_RECORDING_PARTS_CHANGED"}:
        session.error_code = None
    return previous, ids, changed or pin_changed


def finish(db, session, previous, ids, changed, *, created=False):
    audit_id = None
    if changed or created:
        audit = ProcessingJob(kind="manual_recordings", active_key=f"manual_recordings:{session.id}",
            module_id=session.module_id, session_id=session.id, status="COMPLETED", stage="manual_recordings",
            attempts=1, started_at=now(), finished_at=now(), result={
                "previous_video_ids": previous, "video_ids": ids, "session_created": created,
                "downloads": 0, "codex_runs": 0, "remote_writes": False})
        db.add(audit)
        db.flush()
        audit_id = audit.id
        db.add(ExecutionLog(job_id=audit.id, stage="manual_recordings", event="completed",
                            message="MANUAL_RECORDINGS_LINKED"))
    db.commit()
    return {"session_id": session.id, "changed": changed or created, "created": created,
            "audit_job_id": audit_id, "video_ids": ids}


def link_recordings(db, settings, session_id, request):
    # Serialize with worker claims and other edits, rather than relying on UI state.
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        session = db.get(AcademicSession, session_id)
        if session is None:
            raise StageError("SESSION_NOT_FOUND")
        module_idle(db, session.module_id)
        return finish(db, session, *apply_links(db, settings, session, request.youtube_urls))
    except Exception:
        db.rollback()
        raise


def create_manual_session(db, settings, module_id, request):
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        module = db.get(AcademicModule, module_id)
        if module is None:
            raise StageError("MODULE_NOT_FOUND")
        module_idle(db, module.id)
        if module.review_required:
            raise Conflict("MODULE_RECONCILIATION_REQUIRED")
        week, cls = assignment(module.program, request.number)
        session = db.scalar(select(AcademicSession).where(AcademicSession.module_id == module.id,
                                                         AcademicSession.number == request.number))
        created = session is None
        if session is not None:
            old_ids = list(db.scalars(select(Recording.video_id).where(Recording.session_id == session.id)
                                      .order_by(Recording.position)))
            if (not session.recordings_manual or session.class_date != request.class_date
                    or old_ids != [youtube(url)[0] for url in request.youtube_urls]
                    or (request.title.strip() and request.title.strip() != session.title)):
                raise Conflict("SESSION_SLOT_OCCUPIED")
        else:
            if db.scalar(select(AcademicSession.id).where(AcademicSession.module_id == module.id,
                                                         AcademicSession.number.is_(None))):
                raise Conflict("MODULE_RECONCILIATION_REQUIRED")
            if len(list(db.scalars(select(AcademicSession.id).where(AcademicSession.module_id == module.id)))) >= 8:
                raise Conflict("MORE_THAN_EIGHT_SESSIONS")
            session = AcademicSession(id=uid(), module_id=module.id, resource_key=f"manual:{uid()}",
                title=request.title.strip() or f"Clase {request.number} — vinculación manual",
                class_date=request.class_date, number=request.number, week=week, class_in_week=cls,
                manual_assignment=True, recordings_manual=True)
            db.add(session)
            db.flush()
        return finish(db, session, *apply_links(db, settings, session, request.youtube_urls), created=created)
    except Exception:
        db.rollback()
        raise
