import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path

from filelock import FileLock, Timeout
from sqlalchemy import select

from academic_automation.academic.processor import CodexAcademicProcessor
from academic_automation.academic.output import CodexOutputError
from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict, StageError
from academic_automation.core.schemas import CodexInput
from academic_automation.core.security import configure_logging, digest
from academic_automation.database.models import (
    AcademicModule, AcademicSession, ExecutionLog, NotionPage, NotionSection,
    Recording, TranscriptArtifact, now,
)
from academic_automation.database.session import factory, make_engine
from academic_automation.notion.client import NotionClient
from academic_automation.notion.resolver import NotionStructureResolver
from academic_automation.notion.sections import NotionSectionManager
from academic_automation.orchestration.queue import claim, recover
from academic_automation.services.catalog import authorized, sync_catalog, sync_recordings, recording_sync_result
from academic_automation.transcripts.adapter import TranscriptAdapter, valid_artifact
from academic_automation.transcripts.multipart import download_parts, verify_multipart

logger = logging.getLogger(__name__)


class Worker:
    """One durable host worker. Conservative serial default respects all stage concurrency limits."""

    def __init__(self, settings, sessions, *, moodle=None, transcripts=None, processor=None, notion_factory=None):
        self.settings, self.sessions = settings, sessions
        self.moodle = moodle
        self.transcripts = transcripts or TranscriptAdapter(settings)
        self.processor = processor or CodexAcademicProcessor(settings)
        self.notion_factory = notion_factory or (lambda: NotionClient(settings))

    def stage(self, db, job, stage):
        job.stage = stage
        db.add(ExecutionLog(job_id=job.id, stage=stage, event="started", message=f"STAGE_{stage.upper()}"))
        db.commit()

    async def moodle_client(self):
        if self.moodle is None:
            from academic_automation.moodle.client import MoodleClient
            self.moodle = MoodleClient(self.settings)
        return self.moodle

    async def publish(self, db, job, session, module):
        if not self.settings.publication_enabled:
            raise StageError("PUBLICATION_DISABLED")
        if not session.output_path or session.processing_status != "PROCESSED":
            raise StageError("ACADEMIC_OUTPUT_REQUIRED")
        path = Path(session.output_path).resolve()
        if not path.is_relative_to(self.settings.data_dir.resolve()):
            raise StageError("OUTPUT_PATH_INVALID")
        try:
            metadata = json.loads((path.parent / "metadata.json").read_text())
            if metadata.get("status") != "ready" or metadata.get("content_sha256") != session.content_hash:
                raise ValueError("Contrato inválido")
        except (OSError, ValueError):
            raise Conflict("ACADEMIC_BUNDLE_INVALID") from None
        self.stage(db, job, "notion")
        session.publication_status = "PUBLISHING"
        db.commit()
        async with self.notion_factory() as client:
            resolver = NotionStructureResolver(db, client, self.settings)
            page = await resolver.week(module, session.week)
            await NotionSectionManager(db, client).publish(session, page)
        session.publication_status = "PUBLISHED"
        db.commit()
        return {"notion_url": page.url, "page_id": page.page_id}

    async def processing(self, db, job, session, module):
        if not session.week or session.excluded or module.review_required:
            raise Conflict("SESSION_REQUIRES_REVIEW_OR_EXCLUDED")
        if session.discovery_status == "REVIEW_REQUIRED":
            raise Conflict("RECORDING_REQUIRES_REVIEW")
        self.stage(db, job, "transcript")
        recordings = list(db.scalars(select(Recording).where(Recording.session_id == session.id).order_by(Recording.position)))
        if not recordings:
            raise StageError("VIDEO_NOT_IDENTIFIED", retryable=True)
        artifact = db.scalar(select(TranscriptArtifact).where(TranscriptArtifact.session_id == session.id))
        if artifact:
            txt, vtt = Path(artifact.txt_path), Path(artifact.vtt_path)
            if (not valid_artifact(txt, vtt) or digest(txt.read_bytes()) != artifact.txt_hash
                    or digest(vtt.read_bytes()) != artifact.vtt_hash):
                raise Conflict("TRANSCRIPT_ARTIFACT_CHANGED")
            if len(recordings) > 1:
                combined = verify_multipart(self.settings, session.id, recordings)
                if combined["txt_hash"] != artifact.txt_hash or combined["vtt_hash"] != artifact.vtt_hash:
                    raise Conflict("TRANSCRIPT_ARTIFACT_CHANGED")
        else:
            session.transcript_status = "TRANSCRIPT_PENDING"
            db.commit()
            paths = (await download_parts(self.transcripts, self.settings, session.id, recordings) if len(recordings) > 1
                     else await self.transcripts.download(session.id, recordings[0].url))
            artifact = TranscriptArtifact(session_id=session.id, **paths)
            db.add(artifact)
        session.transcript_status = "TRANSCRIPT_READY"
        db.commit()
        if job.kind == "reprocess" or session.processing_status != "PROCESSED" or not session.output_path:
            self.stage(db, job, "codex")
            session.processing_status = "PROCESSING"
            db.commit()
            request = CodexInput(request_id=f"{job.id}-{job.attempts}", program=module.program,
                                 module_id=module.id, module_title=module.name, number=session.number,
                                 week=session.week, class_in_week=session.class_in_week,
                                 transcript_file=artifact.txt_path)
            result = await self.processor.process(request)
            session.output_path, session.content_hash = result["markdown_file"], result["content_hash"]
            session.processing_status, session.revision = "PROCESSED", session.revision + 1
            session.publication_status = "PENDING"
            job.model, job.skill_version, job.skill_hash = result["model"], result["skill_version"], result["skill_hash"]
            job.result = {"markdown_file": session.output_path, "content_hash": session.content_hash}
            db.commit()
        if job.automatic and module.enabled and module.auto_publish and self.settings.publication_enabled:
            job.result = {**(job.result or {}), **await self.publish(db, job, session, module)}

    async def reconcile(self, db, job, module):
        proposal = module.proposed_assignments
        if not proposal:
            return
        self.stage(db, job, "reconcile")
        changed = [p for p in proposal if (s := db.get(AcademicSession, p["id"]))
                   and (s.number, s.week, s.class_in_week) != (p["number"], p["week"], p["class_in_week"])]
        published = []
        has_remote = any(db.scalar(select(NotionSection).where(NotionSection.session_id == p["id"])) for p in changed)
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(self.notion_factory()) if has_remote else None
            manager = NotionSectionManager(db, client)
            # Check EVERY section before beginning a relocation, preserving edits on conflict.
            for p in changed:
                section = manager.section(p["id"])
                if section:
                    if not self.settings.publication_enabled:
                        raise StageError("PUBLICATION_DISABLED")
                    await manager.verify(section)
                    published.append(p["id"])
            touched = set()
            for sid in published:
                section = manager.section(sid)
                touched.add(section.page_id)
                await manager.remove(db.get(AcademicSession, sid))
            for page in db.scalars(select(NotionPage).where(NotionPage.page_id.in_(touched))):
                if page.divider_id:
                    await client.delete(page.divider_id)
                    page.divider_id = None
            for p in changed:
                s = db.get(AcademicSession, p["id"])
                s.number, s.week, s.class_in_week = p["number"], p["week"], p["class_in_week"]
                s.manual_assignment = p.get("manual_assignment", s.manual_assignment)
                if s.output_path:
                    original = Path(s.output_path)
                    content = re.sub(r"^# Clase \d+:", f"# Clase {s.number}:", original.read_text(), count=1)
                    work = self.settings.workdir("reconciled", job.id, s.id)
                    target = work / "notes.md"
                    target.write_text(content, encoding="utf-8")
                    metadata = json.loads((original.parent / "metadata.json").read_text())
                    metadata.update({"week": s.week, "session_number": s.number,
                                     "class_in_week": s.class_in_week, "class_numbers": [s.number],
                                     "page_title": f"Semana {s.week}",
                                     "page_key": f"{module.program}/moodle-{module.id}/semana-{s.week}",
                                     "content_sha256": digest(content), "reconciliation_job": job.id})
                    (work / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
                    s.output_path, s.content_hash = str(target), digest(content)
                    s.revision += 1
            for p in proposal:
                s = db.get(AcademicSession, p["id"])
                s.manual_assignment = p.get("manual_assignment", s.manual_assignment)
            db.commit()
            resolver = NotionStructureResolver(db, client, self.settings)
            for sid in sorted(published, key=lambda sid: db.get(AcademicSession, sid).number):
                s = db.get(AcademicSession, sid)
                page = await resolver.week(module, s.week)
                await manager.publish(s, page)
                s.publication_status = "PUBLISHED"
            module.review_required, module.proposed_assignments = False, None
            db.commit()

    async def execute(self, db, job):
        session = db.get(AcademicSession, job.session_id) if job.session_id else None
        module = db.get(AcademicModule, job.module_id) if job.module_id else None
        if job.automatic and module and not module.enabled:
            job.status, job.finished_at = "CANCELLED", now()
            db.commit()
            return
        if job.automatic and session and not authorized(module, session):
            job.status, job.finished_at = "CANCELLED", now()
            db.commit()
            return
        try:
            if job.kind == "catalog":
                self.stage(db, job, "moodle")
                count = sync_catalog(db, await asyncio.wait_for((await self.moodle_client()).catalog(),
                                                               timeout=self.settings.moodle_timeout * 10))
                job.result = {"modules": count}
            elif job.kind == "recordings":
                self.stage(db, job, "moodle")
                items = await asyncio.wait_for((await self.moodle_client()).recordings(module.id, allow_partial=True),
                                               timeout=self.settings.moodle_timeout * 10)
                count = sync_recordings(db, module, items)
                job.result = recording_sync_result(items, count)
                if job.result.get("reviews"):
                    db.commit()  # Keep discovered sessions/results even when some need review.
                    raise Conflict("MOODLE_MULTIPLE_VIDEOS")
            elif job.kind in {"process", "reprocess"}:
                await self.processing(db, job, session, module)
            elif job.kind == "publish":
                if module.review_required:
                    raise Conflict("MODULE_RECONCILIATION_REQUIRED")
                job.result = await self.publish(db, job, session, module)
            elif job.kind == "reconcile":
                await self.reconcile(db, job, module)
            else:
                raise StageError("UNKNOWN_JOB_KIND")
            job.status, job.finished_at, job.error_code = "COMPLETED", now(), None
            if session:
                session.error_code = None
            code = getattr(self.processor if job.stage == "codex" else self.transcripts,
                           "last_exit_code", None) if job.stage in {"codex", "transcript"} else None
            db.add(ExecutionLog(job_id=job.id, stage=job.stage or "worker", event="completed",
                                message="JOB_COMPLETED", exit_code=code))
            db.commit()
        except asyncio.CancelledError:
            # RUNNING remains persisted. Next exclusive worker recovers it.
            db.rollback()
            raise
        except Exception as error:
            db.rollback()
            db.refresh(job)
            if isinstance(error, TimeoutError):
                error = StageError("STAGE_TIMEOUT", retryable=True)
            known = isinstance(error, StageError)
            code = error.code if known else "UNEXPECTED_STAGE_FAILURE"
            review = (known and error.review) or job.stage == "reconcile"
            retryable = known and error.retryable and not review
            job.error_code = code
            if isinstance(error, CodexOutputError):
                job.result = {**(job.result or {}), "validation": error.diagnostic}
            job.status = "REVIEW_REQUIRED" if review else "FAILED"
            if retryable and job.attempts < self.settings.max_attempts:
                job.status = "RETRY_WAIT"
                job.available_at = now() + timedelta(seconds=self.settings.retry_base_seconds * 2 ** (job.attempts - 1))
            job.finished_at = now()
            if session:
                db.refresh(session)
                session.error_code = code
                field = {"transcript": "transcript_status", "codex": "processing_status", "notion": "publication_status"}.get(job.stage)
                if field:
                    setattr(session, field, "REVIEW_REQUIRED" if review else "FAILED")
            adapter = self.processor if job.stage == "codex" else self.transcripts
            if job.stage == "codex":
                job.model = self.settings.codex_model or None
                job.skill_hash = getattr(self.processor, "skill_hash", None)
                job.skill_version = "1.0" if job.skill_hash else None
            db.add(ExecutionLog(job_id=job.id, stage=job.stage or "worker", event="failed", message=code,
                                exit_code=getattr(adapter, "last_exit_code", None)))
            db.commit()
            # Unexpected exception messages can contain secrets. Log only type and stable error code.
            logger.error("job=%s stage=%s error=%s type=%s", job.id, job.stage, code, type(error).__name__)

    async def tick(self) -> bool:
        with self.sessions() as db:
            job = claim(db)
            if not job:
                return False
            await self.execute(db, job)
            return True

    async def run(self):
        lock = FileLock(str(self.settings.workdir("private") / "worker.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            raise SystemExit("Ya existe un worker para este directorio de datos") from None
        try:
            with self.sessions() as db:
                recover(db)
            while True:
                if not await self.tick():
                    await asyncio.sleep(2)
        finally:
            lock.release()


def main():
    configure_logging()
    settings = Settings()
    settings.prepare()
    engine = make_engine(settings.database_url)
    try:
        asyncio.run(Worker(settings, factory(engine)).run())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
