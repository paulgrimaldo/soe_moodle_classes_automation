"""Read-only evidence for publication conflicts; never accept a new baseline here."""

import json
import os
from uuid import UUID

from sqlalchemy import select

from academic_automation.core.errors import Conflict
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicSession, NotionSection, now
from academic_automation.database.session import factory, make_engine
from academic_automation.notion.client import NotionClient
from academic_automation.notion.sections import NotionSectionManager, canonical


async def inspect_section(db, client, session_id: str) -> dict:
    """Capture actual API responses without changing blocks, jobs or stored hashes."""
    session = db.get(AcademicSession, session_id)
    if session is None:
        raise Conflict("SESSION_NOT_FOUND")
    section = db.scalar(select(NotionSection).where(NotionSection.session_id == session_id))
    if section is None:
        raise Conflict("NOTION_SECTION_NOT_FOUND")
    manager = NotionSectionManager(db, client)
    children = await client.children(section.page_id)
    # Fetch only this class's descendants; the other class's content is unnecessary.
    owned_ids = set(section.block_ids)
    owned = [await manager.tree(block) for block in children if block["id"] in owned_ids]
    positions = {block["id"]: index for index, block in enumerate(children)}
    indexes = [positions[identifier] for identifier in section.block_ids if identifier in positions]
    missing = [identifier for identifier in section.block_ids if identifier not in positions]
    contiguous = bool(indexes) and indexes == list(range(indexes[0], indexes[0] + len(indexes)))
    remote_hash = digest(json.dumps(canonical(owned), sort_keys=True, ensure_ascii=False))
    if section.pending:
        status = "NOTION_PARTIAL_WRITE_REQUIRES_REVIEW"
    elif missing:
        status = "NOTION_OWNED_BLOCK_MISSING"
    elif not contiguous:
        status = "NOTION_SECTION_BOUNDARIES_CHANGED"
    elif remote_hash != section.remote_hash:
        status = "NOTION_EXTERNAL_EDIT_CONFLICT"
    else:
        status = "UNCHANGED"
    return {
        "captured_at": now().isoformat(), "session_id": session_id, "module_id": session.module_id,
        "week": session.week, "class_in_week": session.class_in_week, "page_id": section.page_id,
        "status": status, "pending": section.pending, "stored_remote_hash": section.remote_hash,
        "current_remote_hash": remote_hash, "stored_content_hash": section.content_hash,
        "source_hash": session.content_hash, "section_updated_at": section.updated_at.isoformat(),
        "owned_block_ids": section.block_ids, "missing_block_ids": missing,
        "page_block_count": len(children), "owned_block_count": len(owned),
        "page_block_order": [block["id"] for block in children], "owned_blocks": owned,
    }


async def save_inspection(settings, session_id: str) -> dict:
    session_id = str(UUID(session_id))
    engine = make_engine(settings.database_url)
    try:
        with factory(engine)() as db:
            async with NotionClient(settings) as client:
                report = await inspect_section(db, client, session_id)
    finally:
        engine.dispose()
    filename = f"{session_id}-{now():%Y%m%dT%H%M%S%f}.json"
    path = settings.workdir("private", "notion-inspections") / filename
    # Never emit academic content or credentials to stdout; keep evidence private.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(report, output, ensure_ascii=False, indent=2)
    return {key: report[key] for key in ("session_id", "status", "owned_block_count", "page_block_count")} | {
        "diagnostic_file": str(path), "remote_writes": False, "database_changes": False,
    }
