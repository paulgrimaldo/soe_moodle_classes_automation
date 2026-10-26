"""Read-only captures of explicitly mapped historical MIA pages."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from academic_automation.core.errors import StageError
from academic_automation.core.security import digest
from academic_automation.notion.client import NotionClient

MAX_CAPTURE_BYTES = 40_000_000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path):
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_CAPTURE_BYTES + 1)
        if len(raw) > MAX_CAPTURE_BYTES:
            raise ValueError()
        return json.loads(raw)
    except (OSError, ValueError, TypeError):
        raise StageError("NOTION_IMPORT_CAPTURE_INVALID") from None


def private_json(path, value):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise StageError("NOTION_IMPORT_PATH_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModuleMapping(Strict):
    module_id: int = Field(gt=0, strict=True)
    export_number: int = Field(gt=0, strict=True)
    cohort: str = Field(min_length=1)
    page_id: UUID


class CodeCorrection(Strict):
    block_id: UUID
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    find: str = Field(min_length=1)
    replace: str = Field(min_length=1)


class CaptureMapping(Strict):
    schema_version: int = Field(default=1, ge=1, le=1)
    root_page_id: UUID
    modules: list[ModuleMapping] = Field(min_length=1, max_length=30)
    corrections: list[CodeCorrection] = Field(default_factory=list, max_length=100)

    @field_validator("modules")
    @classmethod
    def unique_modules(cls, values):
        for field in ("module_id", "page_id"):
            if len({getattr(m, field) for m in values}) != len(values):
                raise ValueError("Módulos repetidos")
        return values


def mapping_from(value):
    try:
        return CaptureMapping.model_validate(value)
    except (ValidationError, ValueError):
        raise StageError("NOTION_IMPORT_MAPPING_INVALID") from None


def source_hash(blocks):
    """Ignore API bookkeeping, retaining block IDs, payloads and descendant order."""
    def clean(block):
        kind = block["type"]
        payload = block[kind]
        return {"id": block["id"], "type": kind, "content": payload,
                "children": [clean(child) for child in block.get("_children", [])]}
    return digest(canonical([clean(block) for block in blocks]))


def validate_snapshot(value):
    try:
        if value["schema_version"] != 1:
            raise ValueError()
        mapping = mapping_from(value["mapping"])
        mapped = {m.module_id: m for m in mapping.modules}
        positions, page_ids = set(), set()
        if not isinstance(value["weeks"], list) or len(value["weeks"]) > 120:
            raise ValueError()
        for week in value["weeks"]:
            module_id, number = week["module_id"], week["week"]
            if (type(module_id) is not int or type(number) is not int or number not in range(1, 5)
                    or module_id not in mapped or (module_id, number) in positions):
                raise ValueError()
            page = str(UUID(week["page_id"]))
            if page != week["page_id"] or page in page_ids or not isinstance(week["blocks"], list):
                raise ValueError()
            page_ids.add(page)
            positions.add((module_id, number))
            if source_hash(week["blocks"]) != week["source_hash"]:
                raise ValueError()
        if {w["module_id"] for w in value["weeks"]} != set(mapped):
            raise ValueError()
        return mapping
    except (KeyError, TypeError, ValueError, RecursionError):
        raise StageError("NOTION_IMPORT_CAPTURE_INVALID") from None


class ReadOnlyNotionClient(NotionClient):
    async def request(self, method, path, **kwargs):
        if method != "GET":
            raise StageError("NOTION_IMPORT_REMOTE_WRITE_FORBIDDEN")
        return await super().request(method, path, **kwargs)


async def capture(settings, mapping_path, output, *, client_factory=ReadOnlyNotionClient, progress=None):
    """Capture complete block trees. Existing completed weeks resume only at the same remote edit."""
    mapping = mapping_from(read_json(mapping_path))
    output = Path(output).absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise StageError("NOTION_IMPORT_PATH_INVALID")
    if (output / "snapshot.json").exists():
        raise StageError("NOTION_IMPORT_CAPTURE_EXISTS")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    weeks = []
    async with client_factory(settings) as client:
        await client.page(str(mapping.root_page_id))
        for module in mapping.modules:
            parent = await client.page(str(module.page_id))
            if parent.get("parent", {}).get("page_id") != str(mapping.root_page_id):
                raise StageError("NOTION_IMPORT_PARENT_MISMATCH")
            children = await client.children(str(module.page_id))
            found = set()
            for block in children:
                if block["type"] != "child_page":
                    continue
                match = re.fullmatch(r"Semana\s+([1-4])", block["child_page"]["title"].strip(), re.I)
                if not match:
                    raise StageError("NOTION_IMPORT_UNMAPPED_CHILD_PAGE")
                number = int(match[1])
                if number in found:
                    raise StageError("NOTION_IMPORT_WEEK_DUPLICATE")
                found.add(number)
                before = await client.page(block["id"])
                if before.get("parent", {}).get("page_id") != str(module.page_id):
                    raise StageError("NOTION_IMPORT_PARENT_MISMATCH")
                cache = output / f"week-{block['id']}.json"
                saved = read_json(cache) if cache.exists() else None
                if (saved and saved.get("last_edited_time") == before["last_edited_time"]
                        and saved.get("module_id") == module.module_id and saved.get("week") == number):
                    record = saved
                else:
                    count = 0
                    async def tree(identifier, depth=0):
                        nonlocal count
                        if depth > 32:
                            raise StageError("NOTION_IMPORT_TREE_TOO_DEEP")
                        nodes = await client.children(identifier)
                        for node in nodes:
                            count += 1
                            if count > 20_000:
                                raise StageError("NOTION_IMPORT_TREE_TOO_LARGE")
                            if node.get("has_children"):
                                node["_children"] = await tree(node["id"], depth + 1)
                        return nodes
                    blocks = await tree(block["id"])
                    record = {"module_id": module.module_id, "week": number,
                              "page_id": block["id"], "last_edited_time": before["last_edited_time"],
                              "captured_at": datetime.now(timezone.utc).isoformat(),
                              "blocks": blocks, "source_hash": source_hash(blocks)}
                after = await client.page(block["id"])
                if after["last_edited_time"] != before["last_edited_time"]:
                    raise StageError("NOTION_IMPORT_SOURCE_CHANGED")
                private_json(cache, record)
                weeks.append(record)
                if progress:
                    progress({"module_id": module.module_id, "week": number, "captured_weeks": len(weeks)})
            if not found:
                raise StageError("NOTION_IMPORT_MODULE_EMPTY")
    result = {"schema_version": 1, "mapping": mapping.model_dump(mode="json"), "weeks": weeks}
    validate_snapshot(result)
    private_json(output / "snapshot.json", result)
    return {"status": "captured", "weeks": len(weeks), "snapshot": str(output / "snapshot.json"),
            "remote_writes": False}
