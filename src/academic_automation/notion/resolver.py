import re

from sqlalchemy import select

from academic_automation.core.errors import Conflict
from academic_automation.database.models import NotionPage
from academic_automation.notion.client import page_id


def title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", t.get("text", {}).get("content", "")) for t in prop["title"])
    return ""


class NotionStructureResolver:
    def __init__(self, db, client, settings):
        self.db, self.client, self.settings = db, client, settings

    def association(self, module_id, week):
        return self.db.scalar(select(NotionPage).where(NotionPage.module_id == module_id, NotionPage.week == week))

    def save(self, module_id, week, remote):
        row = NotionPage(module_id=module_id, week=week, page_id=page_id(remote["id"]),
                         url=remote.get("url", f"https://www.notion.so/{remote['id']}"))
        self.db.add(row)
        self.db.commit()
        return row

    async def module(self, module):
        linked = self.association(module.id, 0)
        if linked:
            await self.client.page(linked.page_id)
            return linked
        root = self.settings.notion_dcc_root if module.program == "DCC" else self.settings.notion_mia_root
        if not root:
            raise Conflict("NOTION_MODULE_LINK_REQUIRED")
        root = page_id(root)
        matches = []
        for remote in await self.client.search(module.name):
            if (title(remote).strip().casefold() == module.name.strip().casefold()
                    and remote.get("parent", {}).get("type") == "page_id"
                    and page_id(remote["parent"]["page_id"]) == root
                    and not remote.get("in_trash")):
                matches.append(remote)
        if len(matches) != 1:
            raise Conflict("NOTION_MODULE_AMBIGUOUS_OR_MISSING")
        return self.save(module.id, 0, await self.client.page(matches[0]["id"]))

    async def week(self, module, week):
        parent = await self.module(module)
        linked = self.association(module.id, week)
        if linked:
            remote = await self.client.page(linked.page_id)
            if remote.get("parent", {}).get("type") != "page_id" or page_id(remote["parent"]["page_id"]) != parent.page_id:
                raise Conflict("NOTION_WEEK_PARENT_CHANGED")
            return linked
        matches = [b for b in await self.client.children(parent.page_id)
                   if b["type"] == "child_page" and re.fullmatch(rf"Semana\s+{week}", b["child_page"]["title"].strip(), re.I)]
        if len(matches) > 1:
            raise Conflict("NOTION_WEEK_AMBIGUOUS")
        remote = await self.client.page(matches[0]["id"]) if matches else await self.client.create_week(parent.page_id, week)
        return self.save(module.id, week, remote)
