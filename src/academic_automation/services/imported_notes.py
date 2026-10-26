"""Immutable historical note bundles and an atomic active-revision registry.

The registry belongs to the private data directory. It does not create Moodle
sessions, processing jobs or ownership of remote Notion blocks.
"""

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from uuid import UUID

from filelock import FileLock
from sqlalchemy import select

from academic_automation.core.errors import StageError
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession, ProcessingJob
from academic_automation.notion.archive import canonical, read_json, source_hash, validate_snapshot
from academic_automation.notion.import_markdown import CONVERTER_VERSION, convert_week

SHA = re.compile(r"^[0-9a-f]{64}$")


def storage_root(settings):
    root = settings.data_dir.resolve() / "imported" / "notion"
    checked_path(root)
    return root


def checked_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise StageError("NOTION_IMPORT_PATH_INVALID")
    return path


def atomic_write(path, content):
    checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def registry(settings):
    root = storage_root(settings)
    path = checked_path(root / "registry.json")
    if not path.exists():
        return {"schema_version": 1, "weeks": []}
    data = read_json(path)
    try:
        if data["schema_version"] != 1 or not isinstance(data["weeks"], list):
            raise ValueError()
        positions, pages = set(), set()
        for entry in data["weeks"]:
            mid, week = entry["module_id"], entry["week"]
            if (type(mid) is not int or mid <= 0 or type(week) is not int or week not in range(1, 5)
                    or not isinstance(entry["cohort"], str) or not entry["cohort"]
                    or (mid, week) in positions or entry["page_id"] in pages
                    or str(UUID(entry["page_id"])) != entry["page_id"]
                    or type(entry["revision"]) is not int or entry["revision"] < 1
                    or not SHA.fullmatch(entry["bundle"]) or not SHA.fullmatch(entry["source_hash"])):
                raise ValueError()
            positions.add((mid, week))
            pages.add(entry["page_id"])
            parts = entry["parts"]
            if (not parts or any(type(p) is not int or p not in (1, 2) for p in parts)
                    or sorted(set(parts)) != parts):
                raise ValueError()
            allowed = {"source.json", "metadata.json", "context.md", *(f"class-{p:02d}.md" for p in parts)}
            required = allowed - {"context.md"}
            if (not required <= set(entry["files"]) <= allowed
                    or any(not SHA.fullmatch(h) for h in entry["files"].values())):
                raise ValueError()
            # Verify every artifact, including the preserved source and provenance.
            for name, expected in entry["files"].items():
                target = checked_path(root / "revisions" / entry["bundle"] / name)
                if not target.is_file() or target.stat().st_size > 40_000_000 or digest(target.read_bytes()) != expected:
                    raise StageError("NOTION_IMPORT_ARTIFACT_CHANGED")
        return data
    except (KeyError, TypeError, ValueError, OSError):
        raise StageError("NOTION_IMPORT_REGISTRY_INVALID") from None


def read_imported(settings):
    """Return verified active weeks keyed by module; paths stay private."""
    root = storage_root(settings)
    result = {}
    for entry in registry(settings)["weeks"]:
        bundle = root / "revisions" / entry["bundle"]
        metadata = read_json(bundle / "metadata.json")
        try:
            if ((metadata["module_id"], metadata["cohort"], metadata["week"], metadata["page_id"], metadata["source_hash"])
                    != (entry["module_id"], entry["cohort"], entry["week"], entry["page_id"], entry["source_hash"])):
                raise ValueError()
            classes = []
            for part in entry["parts"]:
                source = next(c for c in metadata["classes"] if c["part"] == part)
                content = (bundle / f"class-{part:02d}.md").read_text(encoding="utf-8")
                classes.append({"session_id": None, "note_id": "notion:" + digest(f"{entry['page_id']}:{part}"),
                                "source": "notion", "title": source["title"], "week": entry["week"],
                                "class_in_week": part, "number": (entry["week"] - 1) * 2 + part,
                                "date": None, "revision": entry["revision"],
                                "content_hash": digest(content), "markdown": content})
            context = (bundle / "context.md").read_text(encoding="utf-8") if "context.md" in entry["files"] else ""
        except (KeyError, ValueError, OSError, StopIteration):
            raise StageError("NOTION_IMPORT_REGISTRY_INVALID") from None
        result.setdefault(entry["module_id"], []).append({"week": entry["week"], "cohort": entry["cohort"], "classes": classes,
                                                       "context": context, "revision": entry["revision"]})
    return result


def local_slots(db, module_id):
    return {(s.week, s.class_in_week) for s in db.scalars(select(AcademicSession).where(
        AcademicSession.module_id == module_id, AcademicSession.output_path.is_not(None),
        AcademicSession.revision > 0))}


def import_snapshot(settings, db, snapshot_path, *, apply=False):
    snapshot = read_json(snapshot_path)
    mapping = validate_snapshot(snapshot)
    mapped = {m.module_id: m for m in mapping.modules}
    for mid, item in mapped.items():
        module = db.get(AcademicModule, mid)
        if module is None or module.program != "MIA" or module.cohort != item.cohort:
            raise StageError("NOTION_IMPORT_MODULE_MISMATCH")
        if module.export_number is not None and module.export_number != item.export_number:
            raise StageError("NOTION_IMPORT_NUMBER_MISMATCH")
    if db.scalar(select(ProcessingJob.id).where(ProcessingJob.module_id.in_(mapped),
                     ProcessingJob.status.in_(["RUNNING", "QUEUED", "RETRY_WAIT"]))):
        raise StageError("NOTION_IMPORT_MODULE_BUSY")
    prepared, applied_corrections = [], []
    for week in snapshot["weeks"]:
        try:
            converted = convert_week(week, mapping.corrections)
        except (KeyError, TypeError, ValueError, RecursionError):
            raise StageError("NOTION_IMPORT_TREE_INVALID") from None
        slots = local_slots(db, week["module_id"])
        if any((week["week"], c["part"]) in slots for c in converted["classes"]):
            raise StageError("NOTION_IMPORT_LOCAL_CONFLICT")
        files = {f"class-{c['part']:02d}.md": c["markdown"].encode() for c in converted["classes"]}
        if converted["context"]:
            files["context.md"] = converted["context"].encode()
        fingerprint = digest(canonical({"version": CONVERTER_VERSION, "source_hash": week["source_hash"],
            "module_id": week["module_id"], "cohort": mapped[week["module_id"]].cohort,
            "week": week["week"], "page_id": week["page_id"],
            "files": {name: digest(content) for name, content in files.items()}}))
        metadata = {"module_id": week["module_id"], "cohort": mapped[week["module_id"]].cohort,
                    "week": week["week"], "page_id": week["page_id"],
                    "source_hash": week["source_hash"], "converter_version": CONVERTER_VERSION,
                    "metrics": converted["metrics"], "corrections": converted["corrections"],
                    "classes": [{k: v for k, v in c.items() if k != "markdown"} for c in converted["classes"]]}
        files["source.json"] = (canonical(week) + "\n").encode()
        files["metadata.json"] = (canonical(metadata) + "\n").encode()
        prepared.append({"module_id": week["module_id"], "cohort": mapped[week["module_id"]].cohort,
                         "week": week["week"], "page_id": week["page_id"],
                         "source_hash": week["source_hash"], "bundle": fingerprint,
                         "parts": sorted(c["part"] for c in converted["classes"]), "contents": files})
        applied_corrections.extend(converted["corrections"])
    requested = [(str(c.block_id), c.find) for c in mapping.corrections]
    if sorted(requested) != sorted((c["block_id"], c["find"]) for c in applied_corrections):
        raise StageError("NOTION_IMPORT_CORRECTION_UNUSED")
    root = storage_root(settings)

    def prepare_commit():
        active = registry(settings)
        entries = {(e["module_id"], e["week"]): e for e in active["weeks"]}
        page_owners = {e["page_id"]: (e["module_id"], e["week"]) for e in active["weeks"]}
        changed, unchanged = 0, 0
        for item in prepared:
            key = item["module_id"], item["week"]
            previous = entries.get(key)
            if item["page_id"] in page_owners and page_owners[item["page_id"]] != key:
                raise StageError("NOTION_IMPORT_PAGE_CONFLICT")
            if previous and previous["page_id"] != item["page_id"]:
                raise StageError("NOTION_IMPORT_PAGE_CONFLICT")
            if previous and previous["bundle"] == item["bundle"]:
                unchanged += 1
                continue
            if previous and not set(previous["parts"]) <= set(item["parts"]):
                raise StageError("NOTION_IMPORT_CLASS_REMOVED")
            entry = {k: v for k, v in item.items() if k != "contents"}
            entry["revision"] = previous["revision"] + 1 if previous else 1
            entry["files"] = {name: digest(content) for name, content in item["contents"].items()}
            # Reactivating an earlier immutable bundle preserves its original capture.
            directory = checked_path(root / "revisions" / item["bundle"])
            if directory.exists():
                for name in entry["files"]:
                    path = checked_path(directory / name)
                    if not path.is_file():
                        raise StageError("NOTION_IMPORT_ARTIFACT_CHANGED")
                    existing = path.read_bytes()
                    if name != "source.json" and digest(existing) != entry["files"][name]:
                        raise StageError("NOTION_IMPORT_ARTIFACT_CHANGED")
                    if name == "source.json":
                        captured = read_json(path)
                        if ((captured.get("module_id"), captured.get("week"), captured.get("page_id")) !=
                                (item["module_id"], item["week"], item["page_id"]) or
                                source_hash(captured["blocks"]) != item["source_hash"]):
                            raise StageError("NOTION_IMPORT_ARTIFACT_CHANGED")
                    entry["files"][name] = digest(existing)
            entries[key] = entry
            changed += 1
        # Only after every conflict check do we write any artifact or active pointer.
        if apply:
            for item in prepared:
                directory = root / "revisions" / item["bundle"]
                if not directory.exists():
                    parent = checked_path(root / "revisions")
                    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with TemporaryDirectory(prefix=".bundle-", dir=parent) as stage:
                        for name, content in item["contents"].items():
                            atomic_write(Path(stage) / name, content)
                        Path(stage).rename(directory)
            if changed:
                active = {"schema_version": 1, "weeks": [entries[k] for k in sorted(entries)]}
                atomic_write(root / "registry.json", (canonical(active) + "\n").encode())
        coverage = []
        for mid, module in mapped.items():
            present = sorted((item["week"] - 1) * 2 + p for item in prepared
                             if item["module_id"] == mid for p in item["parts"])
            coverage.append({"module_id": mid, "export_number": module.export_number,
                             "classes": len(present), "missing": sorted(set(range(1, 9)) - set(present))})
        return {"status": "imported" if apply else "preview", "weeks": len(prepared),
                "classes": sum(len(i["parts"]) for i in prepared), "weeks_changed": changed,
                "weeks_unchanged": unchanged, "corrections": len(applied_corrections), "coverage": coverage,
                "missing_export_numbers": [mid for mid in mapped if db.get(AcademicModule, mid).export_number is None],
                "remote_writes": False, "database_changes": False}

    if not apply:
        return prepare_commit()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(root / ".import.lock")):
        return prepare_commit()
