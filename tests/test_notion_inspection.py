import json
import stat
from copy import deepcopy
from pathlib import Path

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict
from academic_automation.database.models import NotionPage
from academic_automation.notion.inspection import inspect_section, save_inspection
from academic_automation.notion.sections import NotionSectionManager
from fakes import FakeNotion
from test_foundation import module
from test_notion import session


async def published(db, tmp_path):
    fake = FakeNotion()
    page_id = fake.add_page()
    m = module(db)
    page = NotionPage(module_id=m.id, week=1, page_id=page_id, url="p")
    db.add(page)
    s = session(db, m, tmp_path, 1)
    section = await NotionSectionManager(db, fake).publish(s, page)
    return fake, s, section


async def test_read_only_report_distinguishes_changed_content(db, tmp_path):
    fake, s, section = await published(db, tmp_path)
    original_hash, original_ids, writes = section.remote_hash, list(section.block_ids), fake.writes
    report = await inspect_section(db, fake, s.id)
    assert report["status"] == "UNCHANGED"
    assert report["stored_remote_hash"] == report["current_remote_hash"]
    # Response metadata alone is not a content edit.
    for identifier in original_ids:
        fake.blocks[identifier].update(last_edited_time="2026-10-17T12:00:00Z", created_by={"id": "user"})
    assert (await inspect_section(db, fake, s.id))["status"] == "UNCHANGED"

    fake.blocks[original_ids[-1]]["paragraph"]["rich_text"][0]["text"]["content"] = "Edición real"
    report = await inspect_section(db, fake, s.id)
    assert report["status"] == "NOTION_EXTERNAL_EDIT_CONFLICT"
    assert report["stored_remote_hash"] != report["current_remote_hash"]
    db.expire_all()
    assert section.remote_hash == original_hash
    assert section.block_ids == original_ids
    assert not section.pending
    assert fake.writes == writes


@pytest.mark.parametrize("problem,expected", [
    ("missing", "NOTION_OWNED_BLOCK_MISSING"),
    ("insertion", "NOTION_SECTION_BOUNDARIES_CHANGED"),
    ("pending", "NOTION_PARTIAL_WRITE_REQUIRES_REVIEW"),
])
async def test_inspection_keeps_evidence_of_structural_conflicts(db, tmp_path, problem, expected):
    fake, s, section = await published(db, tmp_path)
    if problem == "missing":
        fake.child_map[section.page_id].remove(section.block_ids[0])
    elif problem == "insertion":
        inserted = fake.create_block({"type": "divider", "divider": {}})
        fake.child_map[section.page_id].insert(1, inserted)
    else:
        section.pending = True
        db.commit()
    before = deepcopy(fake.blocks)
    report = await inspect_section(db, fake, s.id)
    assert report["status"] == expected
    assert fake.blocks == before
    assert report["missing_block_ids"] == ([section.block_ids[0]] if problem == "missing" else [])


async def test_save_inspection_private_file_without_content_on_stdout(db, tmp_path, monkeypatch):
    fake, s, section = await published(db, tmp_path)
    monkeypatch.setattr("academic_automation.notion.inspection.make_engine", lambda _: db.get_bind())
    monkeypatch.setattr("academic_automation.notion.inspection.NotionClient", lambda _: fake)
    baseline, writes = section.remote_hash, fake.writes
    result = await save_inspection(Settings(data_dir=tmp_path), s.id)
    path = Path(result["diagnostic_file"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    evidence = json.loads(path.read_text())
    assert evidence["owned_blocks"]
    assert evidence["stored_remote_hash"] == baseline
    assert "owned_blocks" not in result
    assert not result["remote_writes"] and not result["database_changes"]
    assert fake.writes == writes


async def test_missing_session_does_not_call_notion(db):
    fake = FakeNotion()
    with pytest.raises(Conflict, match="SESSION_NOT_FOUND"):
        await inspect_section(db, fake, "missing")
    assert fake.writes == 0
