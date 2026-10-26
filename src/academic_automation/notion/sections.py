import json
import re
from pathlib import Path

from sqlalchemy import select

from academic_automation.core.errors import Conflict
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicSession, NotionSection, now
from academic_automation.notion.markdown import batches, markdown_blocks


def canonical(value):
    """Exclude server bookkeeping; retain exact rich text, formatting and nested content."""
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        ignored = {"plain_text", "href"}
        if value.get("object") == "block" or "has_children" in value:
            ignored |= {"id", "object", "created_time", "last_edited_time", "created_by", "last_edited_by",
                        "parent", "request_id", "has_children", "archived", "in_trash"}
        return {k: canonical(v) for k, v in value.items() if k not in ignored}
    return value


class NotionSectionManager:
    def __init__(self, db, client):
        self.db, self.client = db, client

    async def tree(self, block):
        value = dict(block)
        if block.get("has_children"):
            value[block["type"]] = {**value[block["type"]], "children": [
                await self.tree(child) for child in await self.client.children(block["id"])]}
        return value

    async def snapshot(self, section, children=None):
        children = children if children is not None else await self.client.children(section.page_id)
        ids = [b["id"] for b in children]
        try:
            indexes = [ids.index(identifier) for identifier in section.block_ids]
        except ValueError:
            raise Conflict("NOTION_OWNED_BLOCK_MISSING") from None
        if not indexes or indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise Conflict("NOTION_SECTION_BOUNDARIES_CHANGED")
        owned = [await self.tree(children[i]) for i in indexes]
        return digest(json.dumps(canonical(owned), sort_keys=True, ensure_ascii=False))

    async def verify(self, section, children=None):
        if section.pending:
            raise Conflict("NOTION_PARTIAL_WRITE_REQUIRES_REVIEW")
        if await self.snapshot(section, children) != section.remote_hash:
            raise Conflict("NOTION_EXTERNAL_EDIT_CONFLICT")

    def section(self, session_id):
        return self.db.scalar(select(NotionSection).where(NotionSection.session_id == session_id))

    async def remove(self, session):
        section = self.section(session.id)
        if not section:
            return
        await self.verify(section)
        section.pending = True
        self.db.commit()
        for identifier in section.block_ids:
            await self.client.delete(identifier)
        self.db.delete(section)
        self.db.commit()

    async def publish(self, session, page):
        source = Path(session.output_path)
        markdown = source.read_text(encoding="utf-8")
        if digest(markdown) != session.content_hash:
            raise Conflict("LOCAL_MARKDOWN_CHANGED")
        # Source has global class number (1..8); the weekly page uses Clase 1 / Clase 2.
        markdown = re.sub(r"^# Clase \d+:", f"# Clase {session.class_in_week}:", markdown, count=1)
        desired = markdown_blocks(markdown)
        # Fingerprint the rendered payload too: source can stay unchanged across converter fixes.
        rendered_hash = digest(json.dumps(desired, sort_keys=True, ensure_ascii=False))
        children = await self.client.children(page.page_id)
        section = self.section(session.id)
        if section:
            if section.page_id != page.page_id:
                raise Conflict("NOTION_ASSIGNMENT_CHANGED")
            await self.verify(section, children)
            if section.content_hash == rendered_hash:
                return section
        sibling = self.db.scalar(select(NotionSection).join(AcademicSession, AcademicSession.id == NotionSection.session_id)
            .where(NotionSection.page_id == page.page_id, NotionSection.session_id != session.id))
        if sibling:
            # Detect insertions in the sibling but preserve its existing manual edits.
            await self.snapshot(sibling, children)
            if section:
                positions = [b["id"] for b in children]
                self_before = positions.index(section.block_ids[0]) < positions.index(sibling.block_ids[0])
                if self_before != (session.class_in_week == 1):
                    raise Conflict("NOTION_CLASS_ORDER_CHANGED")
        owned_ids = set(section.block_ids if section else []) | set(sibling.block_ids if sibling else [])
        for b in children:
            text = "".join(t.get("plain_text", t.get("text", {}).get("content", ""))
                           for t in b.get(b["type"], {}).get("rich_text", []))
            if b["id"] not in owned_ids and b["type"].startswith("heading_") and re.match(r"Clase\s+\d+\b", text):
                raise Conflict("NOTION_UNMANAGED_CLASS_SECTION")
        if section:
            positions = [b["id"] for b in children]
            first = positions.index(section.block_ids[0])
            after = positions[first - 1] if first else None
            start = first == 0
        elif session.class_in_week == 1:
            if sibling:
                positions = [b["id"] for b in children]
                first = positions.index(sibling.block_ids[0])
                after = positions[first - 1] if first else None
                start = first == 0
            else:
                after, start = None, False
        elif sibling:
            after, start = page.divider_id or sibling.block_ids[-1], False
        else:
            after, start = None, False
        previous_ids = list(section.block_ids) if section else []
        if not section:
            section = NotionSection(session_id=session.id, page_id=page.page_id, block_ids=[])
            self.db.add(section)
        section.pending = True
        self.db.commit()  # Durable write intent BEFORE the first remote mutation.
        new_ids = []
        for batch in batches(desired):
            created = await self.client.append(page.page_id, batch, after=after, start=start)
            new_ids += [b["id"] for b in created]
            after, start = new_ids[-1], False
        for identifier in previous_ids:
            await self.client.delete(identifier)
        section.block_ids = new_ids
        section.content_hash = rendered_hash
        section.remote_hash = await self.snapshot(section)
        # Divider has separate ownership from either class. Keep it between both sections.
        if sibling:
            first_section = section if session.class_in_week == 1 else sibling
            if page.divider_id:
                divider = await self.client.block(page.divider_id)
                if divider.get("type") != "divider" or divider.get("in_trash"):
                    raise Conflict("NOTION_DIVIDER_CHANGED")
                await self.client.delete(page.divider_id)
            created = await self.client.append(page.page_id, [{"object": "block", "type": "divider", "divider": {}}],
                                               after=first_section.block_ids[-1])
            page.divider_id = created[0]["id"]
        section.pending, section.updated_at = False, now()
        self.db.commit()
        return section
