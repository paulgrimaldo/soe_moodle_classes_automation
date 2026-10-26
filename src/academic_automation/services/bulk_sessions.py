"""Validate a homogeneous selection and atomically submit ordinary session jobs."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict, StageError
from academic_automation.core.schemas import BulkOperation, BulkSelection
from academic_automation.database.models import (
    AcademicModule, AcademicSession, ExecutionLog, ProcessingJob, Recording, TranscriptArtifact, now,
)
from academic_automation.orchestration.queue import ACTIVE
from academic_automation.services.catalog import assignment

STATE_FIELDS = ("discovery_status", "transcript_status", "processing_status", "publication_status")


class BulkRejected(Conflict):
    def __init__(self, issues: list[str]):
        super().__init__("BULK_INCOMPATIBLE")
        self.issues = issues


def load_selection(db: Session, module_id: int, selection: BulkSelection):
    module = db.get(AcademicModule, module_id)
    if module is None:
        raise StageError("MODULE_NOT_FOUND")
    sessions = list(db.scalars(select(AcademicSession).where(AcademicSession.module_id == module_id,
        AcademicSession.id.in_(selection.session_ids)).order_by(AcademicSession.number, AcademicSession.id)))
    if len(sessions) != len(selection.session_ids):
        raise BulkRejected(["Todas las sesiones deben existir y pertenecer al módulo elegido."])
    return module, sessions


def eligibility(db: Session, settings: Settings, module: AcademicModule, sessions: list[AcademicSession]) -> dict:
    states = {tuple(getattr(s, field) for field in STATE_FIELDS) for s in sessions}
    homogeneous = len(states) == 1
    ids = [s.id for s in sessions]
    recordings = set(db.scalars(select(Recording.session_id).where(Recording.session_id.in_(ids))))
    transcripts = set(db.scalars(select(TranscriptArtifact.session_id).where(TranscriptArtifact.session_id.in_(ids))))
    common = []
    if not homogeneous:
        common.append("Las sesiones deben tener el mismo estado de descubrimiento, transcripción, Codex y Notion.")
    if module.review_required:
        common.append("El módulo tiene una reconciliación pendiente.")
    active = db.scalar(select(ProcessingJob.id).where(ProcessingJob.status.in_(ACTIVE),
        (ProcessingJob.session_id.in_(ids)) | ((ProcessingJob.module_id == module.id)
            & ProcessingJob.kind.in_(("recordings", "reconcile")))))
    if active:
        common.append("Hay trabajos activos para la selección o una sincronización/reconciliación pendiente del módulo.")
    for s in sessions:
        label = f"Sesión {s.number or s.id}"
        if s.excluded:
            common.append(f"{label}: está excluida.")
        if (not s.number or not 1 <= s.number <= 8
                or assignment(module.program, s.number) != (s.week, s.class_in_week)):
            common.append(f"{label}: su asignación académica requiere revisión.")
        if s.discovery_status != "VIDEO_IDENTIFIED" or s.id not in recordings:
            common.append(f"{label}: sus videos deben estar identificados y sin conflictos.")
    operations = {}
    for operation in ("process", "reprocess", "publish"):
        issues = list(common)
        for s in sessions:
            label = f"Sesión {s.number or s.id}"
            if operation == "process":
                if (s.transcript_status not in {"TRANSCRIPT_PENDING", "TRANSCRIPT_READY", "FAILED"}
                        or s.processing_status not in {"PENDING", "FAILED"}
                        or s.publication_status != "PENDING"):
                    issues.append(f"{label}: Procesar requiere apuntes pendientes o fallidos y publicación pendiente, sin revisión abierta.")
            elif operation == "reprocess":
                if (s.transcript_status != "TRANSCRIPT_READY" or s.id not in transcripts
                        or s.processing_status not in {"PENDING", "FAILED", "PROCESSED"}
                        or s.publication_status not in {"PENDING", "FAILED", "PUBLISHED"}):
                    issues.append(f"{label}: Codex requiere transcripción guardada y lista, sin procesamiento activo ni revisión abierta.")
            else:
                if (s.transcript_status != "TRANSCRIPT_READY" or s.processing_status != "PROCESSED"
                        or not s.output_path or not s.content_hash
                        or s.publication_status not in {"PENDING", "FAILED", "PUBLISHED"}):
                    issues.append(f"{label}: publicar requiere apuntes procesados y guardados, sin conflicto de Notion.")
        if operation == "publish" and not settings.publication_enabled:
            issues.append("Publicación global deshabilitada.")
        operations[operation] = {"compatible": not issues, "issues": issues}
    return {"homogeneous": homogeneous, "operations": operations,
            "sessions": [{"id": s.id, "number": s.number, "class_date": s.class_date.isoformat(),
                          **{field: getattr(s, field) for field in STATE_FIELDS}} for s in sessions]}


def preview_bulk(db: Session, settings: Settings, module_id: int, request: BulkSelection) -> dict:
    module, sessions = load_selection(db, module_id, request)
    return eligibility(db, settings, module, sessions)


def receipt_result(db: Session, receipt: ProcessingJob, *, created: bool) -> dict:
    result = receipt.result
    jobs = [db.get(ProcessingJob, identifier) for identifier in result["job_ids"]]
    return {"batch_id": receipt.id, "created": created, "operation": result["operation"],
            "jobs": [{"id": job.id, "session_id": job.session_id, "module_id": job.module_id,
                      "kind": job.kind, "status": job.status, "automatic": job.automatic} for job in jobs]}


def enqueue_bulk(db: Session, settings: Settings, module_id: int, request: BulkOperation) -> dict:
    # All validation and writes share one lock. A worker cannot claim a new job
    # midway through the submission, and a failed write rolls back the whole lot.
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        identifier = str(request.request_id)
        receipt = db.get(ProcessingJob, identifier)
        if receipt is not None:
            if (receipt.kind != "bulk_dispatch" or receipt.module_id != module_id
                    or receipt.result["operation"] != request.operation
                    or receipt.result["session_ids"] != sorted(request.session_ids)):
                raise BulkRejected(["El identificador de solicitud ya pertenece a otro lote."])
            result = receipt_result(db, receipt, created=False)
            db.rollback()
            return result
        module, sessions = load_selection(db, module_id, request)
        validation = eligibility(db, settings, module, sessions)["operations"][request.operation]
        if not validation["compatible"]:
            raise BulkRejected(validation["issues"])
        jobs = [ProcessingJob(kind=request.operation, active_key=f"session:{s.id}",
            session_id=s.id, module_id=module.id, automatic=False) for s in sessions]
        db.add_all(jobs)
        db.flush()
        # A terminal job is an immutable receipt, never claimed by the worker.
        # Its UUID also provides durable request idempotency after jobs finish.
        receipt = ProcessingJob(id=identifier, kind="bulk_dispatch", active_key=f"bulk:{identifier}",
            module_id=module.id, status="COMPLETED", stage="queue", attempts=1,
            started_at=now(), finished_at=now(), result={"operation": request.operation,
                "session_ids": sorted(request.session_ids), "job_ids": [job.id for job in jobs]})
        db.add(receipt)
        db.add(ExecutionLog(job_id=identifier, stage="queue", event="completed", message="BULK_JOBS_QUEUED"))
        db.flush()
        result = receipt_result(db, receipt, created=True)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
