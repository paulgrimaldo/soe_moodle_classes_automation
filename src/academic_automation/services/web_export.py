"""Export a reproducible, public-safe snapshot of committed academic notes."""

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from filelock import FileLock
from markdown_it import MarkdownIt
from sqlalchemy import select

from academic_automation.core.errors import StageError
from academic_automation.core.markdown_math import math_for_preview
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession
from academic_automation.services.artifacts import read_notes
from academic_automation.services.imported_notes import local_slots, read_imported


class WebExportNumberingError(StageError):
    def __init__(self, issues):
        super().__init__("WEB_EXPORT_NUMBERING_INVALID")
        self.issues = issues


def _validate_numbers(db, rows, imported_modules=()):
    ready = set(db.scalars(select(AcademicSession.module_id).where(
        AcademicSession.processing_status == "PROCESSED", AcademicSession.excluded.is_(False),
        AcademicSession.output_path.is_not(None), AcademicSession.revision > 0)))
    ready.update(imported_modules)
    issues, positions = [], {}
    for module in rows:
        identity = {"module_id": module.id, "module_name": module.name, "cohort": module.cohort}
        number = module.export_number
        if number is None:
            if module.id in ready and not module.review_required:
                issues.append({**identity, "reason": "missing", "message": "Asigne el número de módulo para web."})
        elif not isinstance(number, int) or isinstance(number, bool) or number < 1:
            issues.append({**identity, "reason": "invalid", "message": "El número para web debe ser un entero positivo."})
        else:
            positions.setdefault((module.program, module.cohort, number), []).append(identity)
    for (_, _, number), identities in positions.items():
        if len(identities) > 1:
            issues.extend({**identity, "reason": "duplicate", "export_number": number,
                           "message": "Número para web repetido en el mismo programa y cohorte."}
                          for identity in identities)
    if issues:
        raise WebExportNumberingError(issues)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _frontmatter(values):
    # JSON scalars are also valid YAML; titles cannot introduce additional fields.
    return "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                              for key, value in values.items()) + "---\n\n"


def _label(value):
    return re.sub(r"([\\`*\[\]<>])", r"\\\1", value.replace("\n", " "))


def _title(markdown):
    tokens = MarkdownIt().parse(markdown)
    for index, token in enumerate(tokens[:-1]):
        if token.type == "heading_open" and token.tag == "h1":
            return re.sub(r"^Clase\s+\d+\s*:\s*", "", tokens[index + 1].content, flags=re.I)
    raise StageError("WEB_EXPORT_TITLE_MISSING")


def _owned_path(root, relative, program):
    path = Path(relative)
    prefix = program.lower()
    if (path.is_absolute() or ".." in path.parts or "\\" in relative
            or not (relative.startswith(f"{prefix}/") or relative.startswith(f"public/notes/{prefix}/"))):
        raise StageError("WEB_EXPORT_MANIFEST_INVALID")
    target = root / path
    if any(part.is_symlink() for part in (target, *target.parents)):
        raise StageError("WEB_EXPORT_SYMLINK")
    return target


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def export_web(settings, db, destination: Path, program="DCC", *, overwrite=False):
    """Read current revisions only. Never update SQLite, Notion, or source artifacts.

    The per-program manifest owns exact paths and hashes. Preflight all artifacts
    and conflicts before changing the snapshot; leave unrelated files untouched.
    """
    if program not in {"DCC", "MIA"}:
        raise ValueError("Programa desconocido")
    destination = destination.absolute()
    if any(part.is_symlink() for part in (destination, *destination.parents)):
        raise StageError("WEB_EXPORT_SYMLINK")
    root = destination.resolve()
    private = settings.data_dir.resolve()
    if root.is_relative_to(private) or private.is_relative_to(root):
        raise StageError("WEB_EXPORT_DESTINATION_INVALID")
    root.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root.parent / f".{root.name}-export.lock")):
        return _export(settings, db, root, program, overwrite=overwrite)


def _export(settings, db, root, program, *, overwrite):
    files, modules, skipped = {}, [], []
    prefix = program.lower()
    rows = db.scalars(select(AcademicModule).where(AcademicModule.program == program)
                      .order_by(AcademicModule.cohort, AcademicModule.export_number, AcademicModule.id)).all()
    imported = read_imported(settings) if program == "MIA" else {}
    if set(imported) - {module.id for module in rows}:
        raise StageError("NOTION_IMPORT_MODULE_MISMATCH")
    _validate_numbers(db, rows, imported)
    for module in rows:
        sessions = db.scalars(select(AcademicSession).where(AcademicSession.module_id == module.id)
                             .order_by(AcademicSession.week, AcademicSession.class_in_week,
                                       AcademicSession.id)).all()
        entries, positions, notes, contexts = [], set(), [], []
        module_path = f"{prefix}/modulo-{module.id}"
        for session in sessions:
            if (module.review_required or session.excluded or session.processing_status != "PROCESSED"
                    or not session.output_path or session.revision < 1):
                skipped.append(session.id)
                continue
            week, part = session.week, session.class_in_week
            if (not week or not part or not session.number or week not in range(1, 9 if program == "DCC" else 5)
                    or part not in range(1, 2 if program == "DCC" else 3)
                    or session.number != (week if program == "DCC" else (week - 1) * 2 + part)):
                raise StageError("WEB_EXPORT_ASSIGNMENT_INVALID")
            if (week, part) in positions:
                raise StageError("WEB_EXPORT_DUPLICATE_POSITION")
            positions.add((week, part))
            artifact = read_notes(settings, session, module)
            notes.append({"session_id": session.id, "week": week, "class_in_week": part,
                          "number": session.number, "date": session.class_date.isoformat(),
                          "revision": artifact.revision, "content_hash": artifact.content_hash,
                          "markdown": artifact.markdown})
        occupied = local_slots(db, module.id) if module.id in imported else set()
        for week in imported.get(module.id, []):
            if week["cohort"] != module.cohort:
                raise StageError("NOTION_IMPORT_MODULE_MISMATCH")
            if module.review_required:
                skipped.extend(note["note_id"] for note in week["classes"])
                continue
            for note in week["classes"]:
                if (note["week"], note["class_in_week"]) in occupied:
                    raise StageError("NOTION_IMPORT_LOCAL_CONFLICT")
                notes.append(note)
            if week["context"]:
                path = f"{module_path}/semana-{week['week']:02d}"
                download = f"public/notes/{path}.md"
                title = f"Contexto previo · Semana {week['week']}"
                context = {"title": title, "week": week["week"], "link": f"/{path}.html",
                           "download": f"/notes/{path}.md", "revision": week["revision"],
                           "content_hash": digest(week["context"])}
                contexts.append(context)
                fm = {"title": title, "academic": True, "program": program, "module": module.name,
                      "module_number": module.export_number, "label": f"Semana {week['week']}",
                      "date": None, "source": "notion", "prev": False, "next": False, **context}
                files[f"{path}.md"] = (_frontmatter(fm) + f"# {title}\n\n" +
                                       math_for_preview(week["context"])).encode()
                files[download] = week["context"].encode()
        notes.sort(key=lambda note: (note["week"], note["class_in_week"]))
        for note in notes:
            week, part = note["week"], note["class_in_week"]
            title = _title(note["markdown"])
            stem = f"semana-{week:02d}" + (f"-clase-{part:02d}" if program == "MIA" else "")
            path = f"{module_path}/{stem}"
            download = f"public/notes/{path}.md"
            label = f"Semana {week}" + (f" · Clase {part}" if program == "MIA" else "")
            entry = {"session_id": note["session_id"], "title": title, "label": label,
                     "week": week, "class_in_week": part, "number": note["number"],
                     "date": note["date"], "revision": note["revision"],
                     "content_hash": note["content_hash"], "link": f"/{path}.html",
                     "download": f"/notes/{path}.md"}
            if note.get("source") == "notion":
                entry.update({"note_id": note["note_id"], "source": "notion"})
                context = next((c for c in contexts if c["week"] == week), None)
                if context:
                    entry["week_context"] = context["link"]
            entries.append(entry)
            frontmatter = {"title": title, "description": f"{label} · {module.name}",
                           "academic": True, "program": program, "module": module.name,
                           "module_number": module.export_number, **entry}
            files[f"{path}.md"] = (_frontmatter(frontmatter) + math_for_preview(note["markdown"])).encode()
            files[download] = note["markdown"].encode()
        if not entries:
            continue
        for index, entry in enumerate(entries):
            page = f"{module_path}/" + Path(entry["link"]).stem + ".md"
            previous = entries[index - 1] if index else None
            following = entries[index + 1] if index + 1 < len(entries) else None
            navigation = _frontmatter({
                "prev": {"text": previous["label"], "link": previous["link"]} if previous else False,
                "next": {"text": following["label"], "link": following["link"]} if following else False,
            })
            # Merge the navigation into the existing YAML block.
            files[page] = files[page].replace(b"---\n\n", navigation[4:].encode(), 1)
        item = {"id": module.id, "number": module.export_number, "title": module.name,
                "cohort": module.cohort, "link": f"/{module_path}/", "sessions": entries}
        if contexts:
            item["contexts"] = sorted(contexts, key=lambda c: c["week"])
        modules.append(item)
        index_md = _frontmatter({"title": module.name, "prev": False, "next": False})
        index_md += f"# {_label(module.name)}\n\nMódulo {module.export_number} · {program} · {len(entries)} sesiones disponibles.\n\n"
        for context in item.get("contexts", []):
            index_md += f"- [{context['title']}]({context['link']})\n"
        for entry in entries:
            index_md += f"- [{entry['label']} · {_label(entry['title'])}]({entry['link']})\n"
        files[f"{module_path}/index.md"] = index_md.encode()
    catalog = {"schema_version": 1, "program": program, "modules": modules}
    files[f"{prefix}/catalog.json"] = _json(catalog).encode()
    program_md = _frontmatter({"title": program, "prev": False, "next": False}) + f"# {program}\n\n"
    program_md += "Apuntes organizados por módulo y semana.\n\n"
    for module in modules:
        program_md += f"- [{module['number']:02d} · {_label(module['title'])}]({module['link']}) — {len(module['sessions'])} sesiones\n"
    if not modules:
        program_md += "Aún no hay sesiones exportadas para este programa.\n"
    files[f"{prefix}/index.md"] = program_md.encode()

    manifest = root / f".export-{prefix}.json"
    if manifest.is_symlink():
        raise StageError("WEB_EXPORT_SYMLINK")
    try:
        previous = json.loads(manifest.read_text()) if manifest.exists() else {"files": {}}
        owned = previous["files"]
        if not isinstance(owned, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                               for k, v in owned.items()):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise StageError("WEB_EXPORT_MANIFEST_INVALID") from None
    targets = {relative: _owned_path(root, relative, program) for relative in set(owned) | set(files)}
    for relative, target in targets.items():
        if target.exists():
            if not target.is_file():
                raise StageError("WEB_EXPORT_PATH_CONFLICT")
            current = target.read_bytes()
            if relative not in owned:
                raise StageError("WEB_EXPORT_UNMANAGED_FILE")
            if digest(current) != owned[relative] and not overwrite:
                raise StageError("WEB_EXPORT_LOCAL_CHANGES")
    changed = 0
    for relative, content in files.items():
        target = _owned_path(root, relative, program)
        if not target.exists() or target.read_bytes() != content:
            _write(target, content)
            changed += 1
    stale = set(owned) - set(files)
    for relative in stale:
        _owned_path(root, relative, program).unlink(missing_ok=True)
    manifest_bytes = _json({"schema_version": 1, "files": {key: digest(value)
                           for key, value in sorted(files.items())}}).encode()
    if not manifest.exists() or manifest.read_bytes() != manifest_bytes:
        _write(manifest, manifest_bytes)
    return {"status": "exported", "program": program, "modules": len(modules),
            "sessions": sum(len(module["sessions"]) for module in modules),
            "skipped": len(skipped), "files_changed": changed, "files_removed": len(stale)}
