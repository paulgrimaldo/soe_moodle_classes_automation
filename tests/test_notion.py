from pathlib import Path

import httpx
import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicSession, NotionPage
from academic_automation.notion.client import NotionClient
from academic_automation.notion.markdown import markdown_blocks, batches
from academic_automation.notion.resolver import NotionStructureResolver
from academic_automation.notion.sections import NotionSectionManager
from fakes import FakeNotion
from test_foundation import module


def session(db, m, tmp_path, number):
    from datetime import date
    source = tmp_path / f"class{number}.md"
    content = f"# Clase {number}: Tema\n\nTexto original {number}.\n"
    source.write_text(content)
    s = AcademicSession(module_id=m.id, resource_key=f"r{number}", title="Grabación", class_date=date(2026, 10, number),
        number=number, week=1, class_in_week=number, output_path=str(source), content_hash=digest(content),
        processing_status="PROCESSED")
    db.add(s)
    db.commit()
    return s


async def test_week_resolution_reuses_and_rejects_ambiguous(db, tmp_path):
    m = module(db)
    remote = FakeNotion()
    parent = remote.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="parent"))
    db.commit()
    resolver = NotionStructureResolver(db, remote, Settings(data_dir=tmp_path))
    one = await resolver.week(m, 1)
    assert (await resolver.week(m, 1)).page_id == one.page_id
    assert remote.writes == 1
    remote.add_page(parent, "Semana 2")
    remote.add_page(parent, "Semana 2")
    with pytest.raises(Conflict, match="NOTION_WEEK_AMBIGUOUS"):
        await resolver.week(m, 2)


async def test_insert_class1_before_class2_update_preserves_other_edits(db, tmp_path):
    m = module(db)
    fake = FakeNotion()
    parent = fake.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="parent"))
    db.commit()
    page = await NotionStructureResolver(db, fake, Settings(data_dir=tmp_path)).week(m, 1)
    manager = NotionSectionManager(db, fake)
    s1, s2 = session(db, m, tmp_path, 1), session(db, m, tmp_path, 2)
    section2 = await manager.publish(s2, page)
    second_ids = list(section2.block_ids)
    fake.blocks[second_ids[-1]]["paragraph"]["rich_text"][0]["text"]["content"] = "Edición manual ajena"
    section1 = await manager.publish(s1, page)
    ids = [b["id"] for b in await fake.children(page.page_id)]
    assert ids.index(section1.block_ids[0]) < ids.index(page.divider_id) < ids.index(second_ids[0])
    assert fake.blocks[page.divider_id]["type"] == "divider"
    content = "# Clase 1: Tema actualizado\n\nNueva explicación.\n"
    Path(s1.output_path).write_text(content)
    s1.content_hash = digest(content)
    await manager.publish(s1, page)
    assert manager.section(s2.id).block_ids == second_ids
    assert fake.blocks[second_ids[-1]]["paragraph"]["rich_text"][0]["text"]["content"] == "Edición manual ajena"
    writes = fake.writes
    await manager.publish(s1, page)
    assert fake.writes == writes
    with pytest.raises(Conflict, match="NOTION_EXTERNAL_EDIT_CONFLICT"):
        await manager.publish(s2, page)


async def test_nested_table_edit_detected(db, tmp_path):
    m = module(db)
    fake = FakeNotion()
    pid = fake.add_page()
    page = NotionPage(module_id=m.id, week=1, page_id=pid, url="p")
    db.add(page)
    s = session(db, m, tmp_path, 1)
    content = "# Clase 1: Tabla\n\n|A|B|\n|-|-|\n|x|y|\n"
    Path(s.output_path).write_text(content)
    s.content_hash = digest(content)
    manager = NotionSectionManager(db, fake)
    section = await manager.publish(s, page)
    table = next(i for i in section.block_ids if fake.blocks[i]["type"] == "table")
    row = fake.child_map[table][1]
    fake.blocks[row]["table_row"]["cells"][0][0]["text"]["content"] = "editado"
    with pytest.raises(Conflict, match="NOTION_EXTERNAL_EDIT_CONFLICT"):
        await manager.publish(s, page)


def test_markdown_fallbacks_and_limits():
    markdown = "# Título\n\n> Objetivo\n\n- Elemento\n\n```mermaid\nflowchart LR\n A --> B\n```\n\n$$x^2$$\n\n---\n"
    blocks = markdown_blocks(markdown)
    assert [b["type"] for b in blocks] == ["heading_1", "callout", "bulleted_list_item", "code", "equation", "divider"]
    assert blocks[3]["code"]["caption"][0]["text"]["content"] == "Mermaid"
    assert all(len(batch) <= 50 for batch in batches(blocks * 50))


async def test_write_503_is_not_retried():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(503, json={"code": "service_unavailable"})
    settings = Settings(notion_token="dummy")
    async with NotionClient(settings, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(Conflict, match="NOTION_WRITE_OUTCOME_UNKNOWN"):
            await client.append("parent", [{"type": "divider", "divider": {}}])
    assert len(calls) == 1
    body = __import__("json").loads(calls[0].content)
    assert body["position"] == {"type": "end"}


async def test_renderer_upgrade_republishes_same_source_once_and_preserves_sibling(db, tmp_path, monkeypatch):
    from academic_automation.notion.markdown import block

    m = module(db)
    fake = FakeNotion()
    pid = fake.add_page()
    page = NotionPage(module_id=m.id, week=1, page_id=pid, url="p")
    db.add(page)
    first, second = session(db, m, tmp_path, 1), session(db, m, tmp_path, 2)
    content = "# Clase 1: Matemáticas\n\n\\[\nM = \\mathcal{T}(C,D)\n\\]\n"
    Path(first.output_path).write_text(content)
    first.content_hash = digest(content)
    manager = NotionSectionManager(db, fake)
    sibling = await manager.publish(second, page)
    sibling_ids = list(sibling.block_ids)
    with monkeypatch.context() as context:
        context.setattr("academic_automation.notion.sections.markdown_blocks", lambda source: [
            block("heading_1", "Clase 1: Matemáticas"), block("paragraph", "[ M = \\mathcal{T}(C,D) ]")])
        old = await manager.publish(first, page)
    # Rows created by the previous publisher stored the source hash.
    old.content_hash = first.content_hash
    db.commit()
    writes = fake.writes

    repaired = await manager.publish(first, page)

    assert fake.writes > writes
    assert any(fake.blocks[identifier]["type"] == "equation" for identifier in repaired.block_ids)
    assert manager.section(second.id).block_ids == sibling_ids
    writes = fake.writes
    await manager.publish(first, page)
    assert fake.writes == writes
