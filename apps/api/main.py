import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.schemas import (
    AcademicReviewApproval, AcademicReviewDraft, BulkOperation, BulkSelection,
    ManualSessionCreate, ModulePatch, NotionLink, NotionRelink, RecordingLinks,
    SessionPatch, SectionResolution, SessionNotes,
)
from academic_automation.database.models import (
    AcademicModule, AcademicSession, ExecutionLog, MonitorEvent, NotionPage, NotionSection,
    ProcessingJob, Recording, now,
)
from academic_automation.database.session import factory, make_engine, seed
from academic_automation.orchestration.queue import ACTIVE, enqueue
from academic_automation.services.catalog import assignment, authorized
from academic_automation.services.artifacts import read_notes
from academic_automation.services.manual_recordings import create_manual_session, link_recordings
from academic_automation.services.bulk_sessions import BulkRejected, enqueue_bulk, preview_bulk
from academic_automation.services.academic_review import (
    AcademicReviewRejected, approve_review, latest_generation, preview_review, review_available,
)


def serialize(row):
    return jsonable_encoder({c.name: getattr(row, c.name) for c in row.__table__.columns})


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    config.prepare()
    engine = make_engine(config.database_url)
    sessions = factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        if config.auth_enabled and (not config.admin_token.get_secret_value() or not config.n8n_token.get_secret_value()):
            raise RuntimeError("Configure ADMIN_TOKEN y N8N_TOKEN antes de iniciar")
        with sessions() as db:
            seed(db)  # Schema is owned by Alembic; missing migration fails visibly.
        yield
        engine.dispose()

    app = FastAPI(title="Academic Automation", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.sessions = config, sessions
    bearer = HTTPBearer(auto_error=False)

    def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        if not config.auth_enabled:
            return "admin"
        if credentials:
            token = credentials.credentials
            for role, expected in (("admin", config.admin_token), ("n8n", config.n8n_token)):
                if expected.get_secret_value() and secrets.compare_digest(token, expected.get_secret_value()):
                    return role
        raise HTTPException(401, "Token inválido")

    def admin(role=Depends(auth)):
        if role != "admin":
            raise HTTPException(403, "Requiere token administrativo")

    def database():
        with sessions() as db:
            yield db

    def get(db, model, identifier):
        result = db.get(model, identifier)
        if result is None:
            raise HTTPException(404, "Registro inexistente")
        return result

    def idle(db, module_id):
        if db.scalar(select(ProcessingJob).where(ProcessingJob.module_id == module_id,
                                               ProcessingJob.status == "RUNNING")):
            raise HTTPException(409, "Espere a que termine el trabajo del módulo")

    @app.get("/health")
    def health(db=Depends(database)):
        db.execute(select(1))
        return {"status": "ok"}

    @app.get("/stats", dependencies=[Depends(auth)])
    def stats(db=Depends(database)):
        def count(model, *conditions):
            return db.scalar(select(func.count()).select_from(model).where(*conditions))
        return {"modules": count(AcademicModule), "enabled": count(AcademicModule, AcademicModule.enabled),
                "sessions": count(AcademicSession),
                "processed": count(AcademicSession, AcademicSession.processing_status == "PROCESSED"),
                "published": count(AcademicSession, AcademicSession.publication_status == "PUBLISHED"),
                "pending": count(ProcessingJob, ProcessingJob.status.in_(ACTIVE)),
                "failed": count(ProcessingJob, ProcessingJob.status.in_(("FAILED", "REVIEW_REQUIRED"))),
                "last_sync": db.scalar(select(func.max(AcademicModule.last_catalog_sync)))}

    @app.post("/sync/catalog", status_code=202, dependencies=[Depends(auth)])
    def catalog(db=Depends(database)):
        return serialize(enqueue(db, "catalog"))

    @app.post("/sync/modules/{id}", status_code=202, dependencies=[Depends(auth)])
    def recordings(id: int, db=Depends(database)):
        get(db, AcademicModule, id)
        return serialize(enqueue(db, "recordings", module_id=id))

    @app.post("/sync/recordings", status_code=202, dependencies=[Depends(auth)])
    def enabled_recordings(db=Depends(database)):
        return [serialize(enqueue(db, "recordings", module_id=m.id, automatic=True))
                for m in db.scalars(select(AcademicModule).where(AcademicModule.enabled))]

    @app.get("/modules", dependencies=[Depends(auth)])
    def modules(program: str | None = None, q: str = "", db=Depends(database)):
        stmt = select(AcademicModule).where(AcademicModule.name.icontains(q))
        if program:
            stmt = stmt.where(AcademicModule.program == program)
        return [serialize(m) for m in db.scalars(stmt.order_by(AcademicModule.id))]

    @app.get("/modules/{id}", dependencies=[Depends(auth)])
    def module(id: int, db=Depends(database)):
        return serialize(get(db, AcademicModule, id))

    @app.patch("/modules/{id}", dependencies=[Depends(admin)])
    def patch_module(id: int, patch: ModulePatch, db=Depends(database)):
        m = get(db, AcademicModule, id)
        if patch.auto_publish and not config.publication_enabled:
            raise HTTPException(409, "Publicación global deshabilitada")
        if patch.mode == "NEW_ONLY" and m.mode != "NEW_ONLY":
            m.activated_at = now()
        values = patch.model_dump(exclude_none=True)
        if "export_number" in patch.model_fields_set:
            values["export_number"] = patch.export_number
        for key, value in values.items():
            setattr(m, key, value)
        db.commit()
        return serialize(m)

    @app.get("/modules/{id}/sessions", dependencies=[Depends(auth)])
    def module_sessions(id: int, db=Depends(database)):
        get(db, AcademicModule, id)
        result = []
        for s in db.scalars(select(AcademicSession).where(AcademicSession.module_id == id)
                            .order_by(AcademicSession.class_date, AcademicSession.resource_key)):
            item = serialize(s)
            recordings = list(db.scalars(select(Recording).where(Recording.session_id == s.id).order_by(Recording.position)))
            section = db.scalar(select(NotionSection).where(NotionSection.session_id == s.id))
            item["youtube_url"] = recordings[0].url if recordings else None
            item["recordings"] = [{"position": part.position, "video_id": part.video_id, "url": part.url} for part in recordings]
            item["notion_url"] = f"https://www.notion.so/{section.page_id.replace('-', '')}" if section else None
            item["academic_review_available"] = review_available(s, latest_generation(db, s.id))
            result.append(item)
        return result

    @app.get("/sessions/{id}/notes", response_model=SessionNotes, dependencies=[Depends(admin)])
    def session_notes(id: str, db=Depends(database)):
        session = get(db, AcademicSession, id)
        module = get(db, AcademicModule, session.module_id)
        try:
            return read_notes(config, session, module)
        except StageError as error:
            status = 404 if error.code in {"ACADEMIC_NOTES_NOT_READY", "ACADEMIC_NOTES_FILE_MISSING"} else 409
            if error.code == "ACADEMIC_NOTES_TOO_LARGE":
                status = 413
            raise HTTPException(status, error.code) from None

    def academic_review_result(operation, db, identifier, request=None):
        try:
            return operation(db, config, identifier, request) if request else operation(db, config, identifier)
        except AcademicReviewRejected as error:
            raise HTTPException(409, {"code":error.code, "validation":error.diagnostic}) from None
        except StageError as error:
            raise HTTPException(404 if error.code == "SESSION_NOT_FOUND" else 409, error.code) from None

    @app.get("/sessions/{id}/academic-review", dependencies=[Depends(admin)])
    def academic_review(id: str, db=Depends(database)):
        return academic_review_result(preview_review, db, id)

    @app.post("/sessions/{id}/academic-review/validate", dependencies=[Depends(admin)])
    def validate_review(id: str, request: AcademicReviewDraft, db=Depends(database)):
        return academic_review_result(preview_review, db, id, request)

    @app.post("/sessions/{id}/academic-review/approve", dependencies=[Depends(admin)])
    def approve_academic_review(id: str, request: AcademicReviewApproval, db=Depends(database)):
        return academic_review_result(approve_review, db, id, request)

    def manual_link_result(operation, db, identifier, request):
        try:
            return operation(db, config, identifier, request)
        except StageError as error:
            status = 404 if error.code in {"SESSION_NOT_FOUND", "MODULE_NOT_FOUND"} else 409
            raise HTTPException(status, error.code) from None

    @app.post("/modules/{id}/sessions/manual", dependencies=[Depends(admin)])
    def manual_session(id: int, request: ManualSessionCreate, db=Depends(database)):
        return manual_link_result(create_manual_session, db, id, request)

    @app.put("/sessions/{id}/recordings", dependencies=[Depends(admin)])
    def manual_recordings(id: str, request: RecordingLinks, db=Depends(database)):
        return manual_link_result(link_recordings, db, id, request)

    @app.patch("/sessions/{id}", dependencies=[Depends(admin)])
    def patch_session(id: str, patch: SessionPatch, db=Depends(database)):
        s = get(db, AcademicSession, id)
        m = get(db, AcademicModule, s.module_id)
        idle(db, m.id)
        values = patch.model_dump(exclude_none=True)
        if any(k in values for k in ("week", "class_in_week", "class_date")):
            w, c = values.get("week", s.week), values.get("class_in_week", s.class_in_week)
            if w is None or c is None:
                raise HTTPException(422, "Indique semana y clase")
            number = w if m.program == "DCC" else 2 * (w - 1) + c
            if not 1 <= number <= 8 or assignment(m.program, number) != (w, c):
                raise HTTPException(422, "Semana/clase inválida")
            collision = db.scalar(select(AcademicSession).where(AcademicSession.module_id == m.id,
                                                               AcademicSession.id != id, AcademicSession.number == number))
            if s.output_path or collision:
                proposal = []
                for item in db.scalars(select(AcademicSession).where(AcademicSession.module_id == m.id)):
                    n = number if item.id == id else (s.number if collision and item.id == collision.id else item.number)
                    if n is None:
                        raise HTTPException(409, "Resuelva primero la reconciliación cronológica pendiente")
                    week_value, class_value = assignment(m.program, n)
                    proposal.append({"id": item.id, "number": n, "week": week_value,
                                     "class_in_week": class_value,
                                     "manual_assignment": item.manual_assignment or item.id == id or (collision is not None and item.id == collision.id)})
                m.review_required, m.proposed_assignments = True, proposal
                db.commit()
                return {**serialize(s), "proposal_pending": True}
            s.number, s.manual_assignment = number, True
        for key, value in values.items():
            setattr(s, key, value)
        db.commit()
        return serialize(s)

    def bulk_result(operation, db, module_id, request):
        try:
            return operation(db, config, module_id, request)
        except BulkRejected as error:
            raise HTTPException(409, {"code": error.code,
                "message": "No se encoló el lote. Revise la selección.", "issues": error.issues}) from None
        except StageError as error:
            raise HTTPException(404 if error.code == "MODULE_NOT_FOUND" else 409, error.code) from None

    @app.post("/modules/{id}/sessions/bulk/preview", dependencies=[Depends(admin)])
    def bulk_preview(id: int, request: BulkSelection, db=Depends(database)):
        return bulk_result(preview_bulk, db, id, request)

    @app.post("/modules/{id}/sessions/bulk", status_code=202, dependencies=[Depends(admin)])
    def bulk_dispatch(id: int, request: BulkOperation, db=Depends(database)):
        return bulk_result(enqueue_bulk, db, id, request)

    def session_job(id, kind, db):
        s = get(db, AcademicSession, id)
        m = get(db, AcademicModule, s.module_id)
        if s.excluded or m.review_required or s.week is None:
            raise HTTPException(409, "Sesión excluida o asignación pendiente de revisión")
        if s.discovery_status == "REVIEW_REQUIRED":
            raise HTTPException(409, "Esta grabación requiere revisar sus videos; las demás sesiones siguen disponibles")
        if kind == "publish" and not config.publication_enabled:
            raise HTTPException(409, "Publicación global deshabilitada")
        job = enqueue(db, kind, session_id=id, module_id=s.module_id)
        if job.kind != kind:
            raise HTTPException(409, f"La sesión tiene un trabajo activo de tipo {job.kind}")
        return serialize(job)

    @app.post("/sessions/{id}/process", status_code=202, dependencies=[Depends(admin)])
    def process(id: str, db=Depends(database)):
        return session_job(id, "process", db)

    @app.post("/sessions/{id}/retry", status_code=202, dependencies=[Depends(admin)])
    def retry(id: str, db=Depends(database)):
        last = db.scalar(select(ProcessingJob).where(ProcessingJob.session_id == id)
                         .order_by(ProcessingJob.created_at.desc()))
        if last and last.status == "REVIEW_REQUIRED":
            raise HTTPException(409, "Resuelva primero el conflicto o la salida académica")
        return session_job(id, last.kind if last and last.kind == "publish" else "process", db)

    @app.post("/sessions/{id}/reprocess", status_code=202, dependencies=[Depends(admin)])
    def reprocess(id: str, db=Depends(database)):
        return session_job(id, "reprocess", db)

    @app.post("/sessions/{id}/publish", status_code=202, dependencies=[Depends(admin)])
    def publish(id: str, db=Depends(database)):
        return session_job(id, "publish", db)

    @app.post("/processing/dispatch", status_code=202, dependencies=[Depends(auth)])
    def dispatch(db=Depends(database)):
        result = []
        for s in db.scalars(select(AcademicSession).where(AcademicSession.processing_status == "PENDING",
                                                        AcademicSession.discovery_status == "VIDEO_IDENTIFIED")):
            if authorized(db.get(AcademicModule, s.module_id), s):
                result.append(serialize(enqueue(db, "process", session_id=s.id, module_id=s.module_id, automatic=True)))
        return result

    @app.get("/jobs", dependencies=[Depends(auth)])
    def jobs(status: str | None = None, limit: int = 100, db=Depends(database)):
        stmt = select(ProcessingJob)
        if status:
            stmt = stmt.where(ProcessingJob.status == status)
        return [serialize(j) for j in db.scalars(stmt.order_by(ProcessingJob.created_at.desc()).limit(min(max(limit, 1), 500)))]

    @app.get("/jobs/{id}", dependencies=[Depends(auth)])
    def job(id: str, db=Depends(database)):
        result = serialize(get(db, ProcessingJob, id))
        result["logs"] = [serialize(log) for log in db.scalars(select(ExecutionLog).where(ExecutionLog.job_id == id))]
        return result

    @app.get("/notion/modules/{id}/pages", dependencies=[Depends(admin)])
    def notion_pages(id: int, db=Depends(database)):
        get(db, AcademicModule, id)
        return [serialize(page) for page in db.scalars(select(NotionPage).where(
            NotionPage.module_id == id).order_by(NotionPage.week))]

    @app.post("/notion/modules/{id}/relink", dependencies=[Depends(admin)])
    async def relink(id: int, request: NotionRelink, db=Depends(database)):
        from academic_automation.notion.client import NotionClient
        from academic_automation.notion.relink import relink_page
        m = get(db, AcademicModule, id)
        if request.week > (8 if m.program == "DCC" else 4):
            raise HTTPException(422, "Semana inválida")
        try:
            async with NotionClient(config) as client:
                return await relink_page(db, client, id, request)
        except (StageError, ValueError) as error:
            db.rollback()
            raise HTTPException(409, str(error)) from None

    @app.post("/notion/modules/{id}/link", dependencies=[Depends(admin)])
    async def link(id: int, link: NotionLink, db=Depends(database)):
        from academic_automation.notion.client import NotionClient, page_id
        from academic_automation.core.errors import StageError
        m = get(db, AcademicModule, id)
        idle(db, id)
        if link.week > (8 if m.program == "DCC" else 4):
            raise HTTPException(422, "Semana inválida")
        try:
            pid = page_id(link.page_id)
            async with NotionClient(config) as client:
                remote = await client.page(pid)
                if link.week:
                    parent = db.scalar(select(NotionPage).where(NotionPage.module_id == id, NotionPage.week == 0))
                    if not parent or page_id(remote.get("parent", {}).get("page_id", "")) != parent.page_id:
                        raise HTTPException(409, "Semana debe pertenecer al módulo vinculado")
        except (StageError, ValueError) as e:
            raise HTTPException(409, str(e)) from None
        row = db.scalar(select(NotionPage).where(NotionPage.module_id == id, NotionPage.week == link.week))
        if row and row.page_id != pid:
            raise HTTPException(409, "Destino ya vinculado; revise asociaciones existentes")
        if not row:
            row = NotionPage(module_id=id, week=link.week, page_id=pid, url=remote.get("url", f"https://www.notion.so/{pid}"))
            db.add(row)
        db.commit()
        return serialize(row)

    @app.post("/modules/{id}/reconcile", status_code=202, dependencies=[Depends(admin)])
    def confirm_reconcile(id: int, db=Depends(database)):
        m = get(db, AcademicModule, id)
        idle(db, id)
        if not m.proposed_assignments:
            raise HTTPException(409, "No hay propuesta pendiente")
        if not config.publication_enabled and db.scalar(select(NotionSection).join(
                AcademicSession, AcademicSession.id == NotionSection.session_id).where(AcademicSession.module_id == id)):
            raise HTTPException(409, "Reconciliación publicada requiere habilitar publicación")
        return serialize(enqueue(db, "reconcile", module_id=id))

    @app.post("/monitor/events", dependencies=[Depends(auth)])
    def monitor(db=Depends(database)):
        events = []
        from datetime import timedelta
        for j in db.scalars(select(ProcessingJob).where(
            (ProcessingJob.status.in_(("FAILED", "REVIEW_REQUIRED"))) |
            ((ProcessingJob.status.in_(ACTIVE)) & (ProcessingJob.created_at < now() - timedelta(hours=3))))):
            key = f"{j.id}:{j.status}:{j.attempts}"
            if not db.get(MonitorEvent, key):
                db.add(MonitorEvent(key=key))
                events.append({"job_id": j.id, "status": j.status, "error_code": j.error_code})
        db.commit()
        return events

    @app.get("/sessions/{id}/notion/review", dependencies=[Depends(admin)])
    async def notion_review(id: str, db=Depends(database)):
        from academic_automation.notion.client import NotionClient
        from academic_automation.notion.sections import NotionSectionManager
        from academic_automation.core.errors import StageError
        get(db, AcademicSession, id)
        section = db.scalar(select(NotionSection).where(NotionSection.session_id == id))
        if not section:
            raise HTTPException(404, "No existe sección administrada")
        try:
            async with NotionClient(config) as client:
                children = await client.children(section.page_id)
                manager = NotionSectionManager(db, client)
                blocks = [await manager.tree(b) for b in children]
        except StageError as error:
            raise HTTPException(409, error.code) from None
        return {"section": serialize(section), "page_blocks": blocks}

    @app.post("/sessions/{id}/notion/resolve", dependencies=[Depends(admin)])
    async def notion_resolve(id: str, resolution: SectionResolution, db=Depends(database)):
        from academic_automation.notion.client import NotionClient, page_id
        from academic_automation.notion.sections import NotionSectionManager
        from academic_automation.core.errors import StageError
        s = get(db, AcademicSession, id)
        idle(db, s.module_id)
        section = db.scalar(select(NotionSection).where(NotionSection.session_id == id))
        if not section:
            raise HTTPException(404, "No existe sección administrada")
        try:
            ids = [page_id(i) for i in resolution.block_ids]
            if len(set(ids)) != len(ids):
                raise ValueError("IDs repetidos")
            for other in db.scalars(select(NotionSection).where(NotionSection.page_id == section.page_id,
                                                               NotionSection.session_id != id)):
                if set(ids) & set(other.block_ids):
                    raise ValueError("Bloques pertenecen a otra clase")
            section.block_ids = ids
            async with NotionClient(config) as client:
                section.remote_hash = await NotionSectionManager(db, client).snapshot(section)
            section.content_hash, section.pending = None, False
            s.publication_status, s.error_code = "PENDING", None
            db.commit()
        except (StageError, ValueError) as error:
            db.rollback()
            raise HTTPException(409, str(error)) from None
        return serialize(section)

    return app


app = create_app()
