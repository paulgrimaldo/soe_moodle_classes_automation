"""Explicit local recovery when a linked Notion page was deleted/recreated."""

from datetime import datetime

from sqlalchemy import select, text

from academic_automation.core.errors import Conflict, StageError
from academic_automation.database.models import AcademicSession, ExecutionLog, NotionPage, NotionSection, ProcessingJob, now
from academic_automation.notion.client import page_id
from academic_automation.orchestration.queue import ACTIVE


def record(row):
    return {column.name: value.isoformat() if isinstance(value := getattr(row, column.name), datetime) else value
            for column in row.__table__.columns}


async def relink_page(db, client, module_id, request):
    """Validate remotely, then archive and replace local associations atomically.

    No remote mutations. A missing page can also mean lost access; explicit user
    acknowledgement is required and the old associations remain in the audit.
    """
    target_id, previous_id = page_id(request.page_id), page_id(request.previous_page_id)
    query = select(NotionPage).where(NotionPage.module_id == module_id, NotionPage.week == request.week)
    old = db.scalar(query)
    if old is None:
        raise Conflict("NOTION_PREVIOUS_LINK_REQUIRED")
    if old.page_id not in {previous_id, target_id}:
        raise Conflict("NOTION_LINK_CHANGED")
    remote = await client.page(target_id)
    parent_id = None
    if request.week:
        parent = db.scalar(select(NotionPage).where(NotionPage.module_id == module_id, NotionPage.week == 0))
        parent_id = parent.page_id if parent else None
        if (not parent_id or remote.get("parent", {}).get("type") != "page_id"
                or page_id(remote["parent"].get("page_id", "")) != parent_id):
            raise Conflict("NOTION_WEEK_PARENT_CHANGED")
    if old.page_id != target_id:
        try:
            await client.page(previous_id)
        except StageError as error:
            if error.code not in {"NOTION_OBJECT_UNAVAILABLE", "NOTION_PAGE_IN_TRASH"}:
                raise
        else:
            raise Conflict("NOTION_PREVIOUS_PAGE_STILL_AVAILABLE")
    # Don't hold a SQLite write lock while awaiting the network. Recheck state
    # under the lock so a worker cannot claim a queued job during this change.
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        old = db.scalar(query)
        if old is None or old.page_id not in {previous_id, target_id}:
            raise Conflict("NOTION_LINK_CHANGED")
        if db.scalar(select(ProcessingJob.id).where(ProcessingJob.module_id == module_id,
                                                   ProcessingJob.status.in_(ACTIVE))):
            raise Conflict("MODULE_HAS_ACTIVE_JOBS")
        if old.page_id == target_id:
            result = {"page": record(old), "affected_sessions": [], "audit_job_id": None, "changed": False}
            db.rollback()
            return result
        if parent_id:
            parent = db.scalar(select(NotionPage).where(NotionPage.module_id == module_id, NotionPage.week == 0))
            if parent is None or parent.page_id != parent_id:
                raise Conflict("NOTION_LINK_CHANGED")
        if db.scalar(select(NotionPage.id).where(NotionPage.page_id == target_id)):
            raise Conflict("NOTION_PAGE_ALREADY_LINKED")
        pages = list(db.scalars(select(NotionPage).where(NotionPage.module_id == module_id))) if request.week == 0 else [old]
        page_ids = [p.page_id for p in pages]
        sessions = list(db.scalars(select(AcademicSession).where(AcademicSession.module_id == module_id)))
        if request.week:
            sessions = [s for s in sessions if s.week == request.week]
        # Include managed sections even if a previous reconciliation changed a
        # session's assignment. Their old page ownership must not leak through.
        sections = list(db.scalars(select(NotionSection).join(AcademicSession,
            AcademicSession.id == NotionSection.session_id).where(
                AcademicSession.module_id == module_id, NotionSection.page_id.in_(page_ids))))
        affected_ids = sorted({s.id for s in sessions} | {s.session_id for s in sections})
        audit = ProcessingJob(kind="notion_relink", active_key=f"notion_relink:{module_id}:{request.week}",
            module_id=module_id, status="COMPLETED", stage="notion_relink", attempts=1,
            started_at=now(), finished_at=now(), result={"new_page_id": target_id, "week": request.week,
                "previous_pages": [record(p) for p in pages], "previous_sections": [record(s) for s in sections],
                "affected_sessions": affected_ids, "remote_writes": False})
        db.add(audit)
        db.flush()
        db.add(ExecutionLog(job_id=audit.id, stage="notion_relink", event="completed",
                            message="NOTION_DESTINATION_RELINKED_WITH_ACKNOWLEDGEMENT"))
        for section in sections:
            db.delete(section)
        for session_id in affected_ids:
            s = db.get(AcademicSession, session_id)
            s.publication_status = "PENDING"
            if s.error_code and s.error_code.startswith("NOTION_"):
                s.error_code = None
        for page in pages:
            if page is not old:
                db.delete(page)
        old.page_id, old.url, old.divider_id = target_id, remote.get("url", f"https://www.notion.so/{target_id}"), None
        db.commit()
        return {"page": record(old), "affected_sessions": affected_ids, "audit_job_id": audit.id, "changed": True}
    except Exception:
        db.rollback()
        raise
