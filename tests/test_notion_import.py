import copy
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession, NotionSection, ProcessingJob
from academic_automation.notion.archive import ReadOnlyNotionClient, capture, source_hash
from academic_automation.notion.import_markdown import convert_week
from academic_automation.services.imported_notes import import_snapshot, read_imported, storage_root
from academic_automation.services.web_export import WebExportNumberingError, export_web
from test_web_export import add_note, snapshot


def rt(value, **annotations):
    return {"type": "text", "text": {"content": value}, "plain_text": value, "annotations": annotations}


def block(kind, value="", *, children=None, **fields):
    body = {"rich_text": [rt(value)], **fields}
    result = {"id": str(uuid4()), "type": kind, kind: body, "has_children": children is not None}
    if children is not None:
        result["_children"] = children
    return result


def make_snapshot(db, tmp_path, *, number=2, first=3, second=4):
    if not db.get(AcademicModule, 426):
        db.add(AcademicModule(id=426, program="MIA", cohort="V1", module_number=8,
                              export_number=8, name="Machine Learning"))
        db.commit()
    table = block("table", children=[
        block("table_row", cells=[[rt("Método")], [rt("Expresión")]]),
        block("table_row", cells=[[rt("PCA")], [{"type": "equation", "equation": {"expression": "x|y"}}]]),
    ], table_width=2, has_column_header=True)
    objective = block("callout", "Objetivo de la Semana", children=[block("paragraph", "Contexto compartido")])
    blocks = [objective, block("divider"), block("heading_1", f"Clase {first}: Árboles"),
              block("paragraph", "No ejecutar {{ user }} <script> ni $variables."),
              table, block("code", "flowchart LR\nA --> B", language="mermaid"),
              block("divider"), block("callout", "Objetivo de la Sesión", children=[
                  block("paragraph", "Objetivo exclusivo de la segunda clase")]),
              block("divider"), block("heading_1", f"Clase {second}: PCA"),
              block("paragraph", "Una lista", children=[block("bulleted_list_item", "Anidado")])]
    week = {"module_id": 426, "week": number, "page_id": str(uuid4()), "blocks": blocks,
            "captured_at": "2026-10-23T20:00:00Z", "last_edited_time": "2026-10-20T20:00:00Z"}
    week["source_hash"] = source_hash(blocks)
    data = {"schema_version": 1, "mapping": {"schema_version": 1, "root_page_id": str(uuid4()),
            "modules": [{"module_id": 426, "export_number": 8, "cohort": "V1", "page_id": str(uuid4())}],
            "corrections": []}, "weeks": [week]}
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(data))
    return data, path, Settings(data_dir=tmp_path / "data")


def test_capture_reads_descendants_and_never_writes_remote(db, tmp_path):
    data, _, settings = make_snapshot(db, tmp_path)
    mapping = data["mapping"]
    root, module, week = mapping["root_page_id"], mapping["modules"][0]["page_id"], data["weeks"][0]
    nodes = week["blocks"]
    responses = {root: {"id": root}, module: {"id": module, "parent": {"page_id": root}},
                 week["page_id"]: {"id": week["page_id"], "parent": {"page_id": module},
                                   "last_edited_time": week["last_edited_time"]}}
    children = {module: [block("child_page", title="Semana 2")], week["page_id"]: nodes}
    children[module][0]["id"] = week["page_id"]
    def collect(bs):
        for b in bs:
            if "_children" in b:
                children[b["id"]] = b["_children"]
                collect(b["_children"])
    collect(nodes)
    calls = []
    def transport(request):
        calls.append(request.method)
        assert request.method == "GET"
        parts = request.url.path.strip("/").split("/")
        if parts[1] == "pages":
            return httpx.Response(200, json=responses[parts[2]])
        return httpx.Response(200, json={"results": children[parts[2]], "has_more": False})
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping))
    async def execute():
        client_factory = lambda s: ReadOnlyNotionClient(s.model_copy(update={
            "notion_token": SecretStr("test")}), transport=httpx.MockTransport(transport))
        report = await capture(settings, mapping_path, tmp_path / "captured", client_factory=client_factory)
        assert report["remote_writes"] is False
        captured = json.loads((tmp_path / "captured/snapshot.json").read_text())
        assert captured["weeks"][0]["blocks"] == nodes
        async with client_factory(settings) as client:
            with pytest.raises(StageError, match="REMOTE_WRITE_FORBIDDEN"):
                await client.request("PATCH", "pages/test")
    asyncio.run(execute())
    assert calls and set(calls) == {"GET"}


def test_import_export_preserves_context_and_dcc_without_fake_sessions(db, tmp_path):
    add_note(db, tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    export_web(settings, db, tmp_path / "content", "DCC")
    dcc = snapshot(tmp_path / "content")
    data, path, settings = make_snapshot(db, tmp_path)
    assert import_snapshot(settings, db, path)["status"] == "preview"
    assert not storage_root(settings).exists()
    result = import_snapshot(settings, db, path, apply=True)
    assert result["classes"] == 2 and not result["database_changes"]
    assert db.scalar(select(func.count()).select_from(AcademicSession)) == 1
    assert db.scalar(select(func.count()).select_from(NotionSection)) == 0
    assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 0
    notes = read_imported(settings)[426][0]
    assert "Contexto compartido" in notes["context"]
    assert "Objetivo exclusivo" not in notes["classes"][0]["markdown"]
    assert "Objetivo exclusivo" in notes["classes"][1]["markdown"]
    assert "{{ user }}" not in notes["classes"][0]["markdown"]
    assert "<script>" not in notes["classes"][0]["markdown"]
    export_web(settings, db, tmp_path / "content", "MIA")
    catalog = json.loads((tmp_path / "content/mia/catalog.json").read_text())
    module = catalog["modules"][0]
    assert [s["number"] for s in module["sessions"]] == [3, 4]
    assert all(s["session_id"] is None and s["date"] is None for s in module["sessions"])
    assert len(module["contexts"]) == 1
    assert module["sessions"][0]["week_context"] == "/mia/modulo-426/semana-02.html"
    after = snapshot(tmp_path / "content")
    assert all(after[k] == v for k, v in dcc.items())
    before = snapshot(storage_root(settings))
    assert import_snapshot(settings, db, path, apply=True)["weeks_unchanged"] == 1
    assert snapshot(storage_root(settings)) == before


def test_new_revision_preserves_old_bundle_and_urls(db, tmp_path):
    data, path, settings = make_snapshot(db, tmp_path)
    import_snapshot(settings, db, path, apply=True)
    root = storage_root(settings)
    previous = json.loads((root / "registry.json").read_text())["weeks"][0]
    data["weeks"][0]["blocks"].append(block("paragraph", "Corrección en Notion"))
    data["weeks"][0]["source_hash"] = source_hash(data["weeks"][0]["blocks"])
    path.write_text(json.dumps(data))
    import_snapshot(settings, db, path, apply=True)
    current = json.loads((root / "registry.json").read_text())["weeks"][0]
    assert current["revision"] == 2 and current["bundle"] != previous["bundle"]
    assert (root / "revisions" / previous["bundle"] / "source.json").exists()
    assert "Corrección en Notion" in read_imported(settings)[426][0]["classes"][1]["markdown"]


@pytest.mark.parametrize("case", ["missing_class", "local_conflict", "source_hash", "page_replacement"])
def test_failed_import_preserves_registry_and_all_revisions(db, tmp_path, case):
    data, path, settings = make_snapshot(db, tmp_path)
    import_snapshot(settings, db, path, apply=True)
    before = snapshot(storage_root(settings))
    if case == "missing_class":
        data["weeks"][0]["blocks"] = data["weeks"][0]["blocks"][:6]
        data["weeks"][0]["source_hash"] = source_hash(data["weeks"][0]["blocks"])
    elif case == "local_conflict":
        add_note(db, tmp_path, program="MIA", module_id=426, number=3)
    elif case == "page_replacement":
        data["weeks"][0]["page_id"] = str(uuid4())
    else:
        data["weeks"][0]["source_hash"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(StageError):
        import_snapshot(settings, db, path, apply=True)
    assert snapshot(storage_root(settings)) == before


def test_tampered_artifact_and_registry_traversal_are_rejected(db, tmp_path):
    _, path, settings = make_snapshot(db, tmp_path)
    import_snapshot(settings, db, path, apply=True)
    root = storage_root(settings)
    data = json.loads((root / "registry.json").read_text())
    entry = data["weeks"][0]
    page = root / "revisions" / entry["bundle"] / "class-01.md"
    original = page.read_bytes()
    page.write_text("Edición externa")
    with pytest.raises(StageError, match="ARTIFACT_CHANGED"):
        export_web(settings, db, tmp_path / "content", "MIA")
    assert not (tmp_path / "content").exists()
    page.write_bytes(original)
    entry["files"]["../../escape.md"] = digest("escape")
    (root / "registry.json").write_text(json.dumps(data))
    with pytest.raises(StageError, match="REGISTRY_INVALID"):
        read_imported(settings)


def test_imported_only_module_requires_manual_export_number(db, tmp_path):
    _, path, settings = make_snapshot(db, tmp_path)
    db.get(AcademicModule, 426).export_number = None
    db.commit()
    import_snapshot(settings, db, path, apply=True)
    with pytest.raises(WebExportNumberingError):
        export_web(settings, db, tmp_path / "content", "MIA")


def test_weekly_local_labels_and_partial_week_keep_academic_positions(db, tmp_path):
    data, _, _ = make_snapshot(db, tmp_path, number=3, first=1, second=2)
    converted = convert_week(data["weeks"][0], [])
    assert [c["number"] for c in converted["classes"]] == [5, 6]
    assert "# Clase 5:" in converted["classes"][0]["markdown"]
    only_second = copy.deepcopy(data["weeks"][0])
    only_second["week"] = 1
    at = next(i for i, b in enumerate(only_second["blocks"]) if b["type"] == "heading_1" and
              "Clase 2:" in b["heading_1"]["rich_text"][0]["text"]["content"])
    only_second["blocks"] = only_second["blocks"][at:]
    assert convert_week(only_second, [])["classes"][0]["part"] == 2


def test_incomplete_tree_and_stale_corrections_fail_closed(db, tmp_path):
    from academic_automation.notion.archive import CodeCorrection
    data, _, _ = make_snapshot(db, tmp_path)
    week = data["weeks"][0]
    del week["blocks"][0]["_children"]
    with pytest.raises(StageError, match="TREE_INVALID"):
        convert_week(week, [])
    week["blocks"][0]["_children"] = []
    code = next(b for b in week["blocks"] if b["type"] == "code")
    correction = CodeCorrection(block_id=code["id"], expected_sha256="0" * 64, find="A", replace="B")
    with pytest.raises(StageError, match="CORRECTION_STALE"):
        convert_week(week, [correction])


def test_future_local_processing_conflicts_and_cohort_changes_block_export(db, tmp_path):
    _, path, settings = make_snapshot(db, tmp_path)
    import_snapshot(settings, db, path, apply=True)
    add_note(db, tmp_path, program="MIA", module_id=426, number=3)
    with pytest.raises(StageError, match="LOCAL_CONFLICT"):
        export_web(settings, db, tmp_path / "content", "MIA")
    db.get(AcademicModule, 426).cohort = "Different cohort"
    db.commit()
    with pytest.raises(StageError, match="MODULE_MISMATCH"):
        export_web(settings, db, tmp_path / "content", "MIA")
    assert not (tmp_path / "content").exists()


def test_symlinked_note_cannot_escape_private_storage(db, tmp_path):
    _, path, settings = make_snapshot(db, tmp_path)
    import_snapshot(settings, db, path, apply=True)
    root = storage_root(settings)
    entry = json.loads((root / "registry.json").read_text())["weeks"][0]
    note = root / "revisions" / entry["bundle"] / "class-01.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(note.read_bytes())
    note.unlink()
    note.symlink_to(outside)
    with pytest.raises(StageError, match="PATH_INVALID"):
        read_imported(settings)


def test_prose_does_not_create_markdown_blocks_or_lose_numbered_titles():
    from markdown_it import MarkdownIt
    from academic_automation.notion.import_markdown import text
    parser = MarkdownIt()
    heading = parser.parse("## " + text("1. Contexto"))
    assert heading[1].children[0].content == "1. Contexto"
    paragraph = parser.parse(text("---"))
    assert paragraph[0].type == "paragraph_open" and paragraph[1].children[0].content == "---"


def test_partial_capture_preserves_previously_imported_weeks(db, tmp_path):
    data, path, settings = make_snapshot(db, tmp_path)
    first = copy.deepcopy(data["weeks"][0])
    first["week"], first["page_id"] = 1, str(uuid4())
    # Local 1/2 labels remain valid in either week.
    for b in first["blocks"]:
        if b["type"] == "heading_1":
            b["heading_1"]["rich_text"][0]["text"]["content"] = \
                b["heading_1"]["rich_text"][0]["text"]["content"].replace("Clase 3", "Clase 1").replace("Clase 4", "Clase 2")
    first["source_hash"] = source_hash(first["blocks"])
    data["weeks"].append(first)
    path.write_text(json.dumps(data))
    import_snapshot(settings, db, path, apply=True)
    data["weeks"] = data["weeks"][:1]
    path.write_text(json.dumps(data))
    import_snapshot(settings, db, path, apply=True)
    assert sorted(w["week"] for w in read_imported(settings)[426]) == [1, 2]


def test_captured_code_cannot_instruct_vitepress_to_include_host_files(db, tmp_path):
    data, _, _ = make_snapshot(db, tmp_path)
    data["weeks"][0]["blocks"].append(block("code", "<!-- @include: /private/notes.md -->", language="html"))
    with pytest.raises(StageError, match="BUILD_DIRECTIVE_UNSUPPORTED"):
        convert_week(data["weeks"][0], [])
