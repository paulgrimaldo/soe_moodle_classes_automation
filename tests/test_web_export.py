import json
import sys
from datetime import date

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession
from academic_automation.services.web_export import export_web

MARKDOWN = "# Clase 1: Grafos y modelos\n\nTexto con \\(x^2\\).\n\n```mermaid\ngraph LR\nA --> B\n```\n"


def add_note(db, tmp_path, *, program="DCC", module_id=532, number=1, **kwargs):
    if not db.get(AcademicModule, module_id):
        db.add(AcademicModule(id=module_id, program=program, cohort="V1", module_number=2,
                             export_number=13, name="Modelos"))
        db.commit()
    source = tmp_path / "data" / "processed" / f"job-{module_id}-{number}" / "bundle" / "notes.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(MARKDOWN)
    session = AcademicSession(id=f"s-{module_id}-{number}", module_id=module_id,
                              resource_key=f"resource-{number}", title="Grabación",
                              number=number, week=number if program == "DCC" else (number + 1) // 2,
                              class_in_week=1 if program == "DCC" else (number - 1) % 2 + 1,
                              class_date=date(2026, 10, 1), revision=1, output_path=str(source),
                              content_hash=digest(MARKDOWN), processing_status="PROCESSED")
    for key, value in kwargs.items():
        setattr(session, key, value)
    db.add(session)
    db.commit()
    return session, source


def run_export(db, tmp_path, program="DCC", **kwargs):
    return export_web(Settings(data_dir=tmp_path / "data"), db, tmp_path / "content", program, **kwargs)


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_exports_current_revision_ordered_and_idempotent(db, tmp_path):
    session, source = add_note(db, tmp_path, number=2)
    add_note(db, tmp_path, number=1)
    old = source.parent.parent.parent / "obsolete" / "notes.md"
    old.parent.mkdir()
    old.write_text("# Clase 2: Obsoleto")
    report = run_export(db, tmp_path)
    root = tmp_path / "content"
    catalog = json.loads((root / "dcc/catalog.json").read_text())
    assert report["sessions"] == 2 and report["modules"] == 1
    entries = catalog["modules"][0]["sessions"]
    assert [entry["week"] for entry in entries] == [1, 2]
    assert (root / "public/notes/dcc/modulo-532/semana-02.md").read_bytes() == source.read_bytes()
    exported = (root / "dcc/modulo-532/semana-02.md").read_text()
    assert "$x^2$" in exported and "```mermaid\ngraph LR" in exported
    assert '"Semana 1"' in exported and "Obsoleto" not in exported
    assert str(tmp_path) not in exported and "file://" not in exported
    first = snapshot(root)
    assert run_export(db, tmp_path)["files_changed"] == 0
    assert snapshot(root) == first
    assert session.output_path == str(source) and source.read_text() == MARKDOWN


def test_new_revision_updates_same_url_and_download(db, tmp_path):
    session, source = add_note(db, tmp_path)
    run_export(db, tmp_path)
    source.write_text(MARKDOWN + "\nNueva explicación.\n")
    session.content_hash = digest(source.read_bytes())
    session.revision += 1
    db.commit()
    run_export(db, tmp_path)
    exported = tmp_path / "content/dcc/modulo-532/semana-01.md"
    assert "revision: 2" in exported.read_text() and "Nueva explicación." in exported.read_text()
    assert (tmp_path / "content/public/notes/dcc/modulo-532/semana-01.md").read_bytes() == source.read_bytes()


@pytest.mark.parametrize("state", ["REVIEW_REQUIRED", "PROCESSING", "FAILED", "PENDING"])
def test_excludes_unready_and_excluded_sessions(db, tmp_path, state):
    add_note(db, tmp_path, number=1, processing_status=state)
    add_note(db, tmp_path, number=2, excluded=True)
    report = run_export(db, tmp_path)
    assert report["sessions"] == 0 and report["skipped"] == 2
    assert not (tmp_path / "content/dcc/modulo-532").exists()


def test_module_review_blocks_export_and_other_program_survives(db, tmp_path):
    add_note(db, tmp_path)
    add_note(db, tmp_path, program="MIA", module_id=559, number=1)
    add_note(db, tmp_path, program="MIA", module_id=559, number=2)
    run_export(db, tmp_path, "MIA")
    mia = snapshot(tmp_path / "content/mia")
    assert (tmp_path / "content/mia/modulo-559/semana-01-clase-02.md").exists()
    db.get(AcademicModule, 532).review_required = True
    db.commit()
    assert run_export(db, tmp_path)["sessions"] == 0
    assert snapshot(tmp_path / "content/mia") == mia


def test_preflights_hashes_before_changing_any_export(db, tmp_path):
    session, source = add_note(db, tmp_path)
    run_export(db, tmp_path)
    before = snapshot(tmp_path / "content")
    source.write_text("Corrupto")
    with pytest.raises(StageError, match="ACADEMIC_NOTES_CHANGED"):
        run_export(db, tmp_path)
    assert snapshot(tmp_path / "content") == before


def test_refuses_local_edits_and_unmanaged_collisions(db, tmp_path):
    add_note(db, tmp_path)
    path = tmp_path / "content/dcc/modulo-532/semana-01.md"
    path.parent.mkdir(parents=True)
    path.write_text("Apunte manual")
    with pytest.raises(StageError, match="WEB_EXPORT_UNMANAGED_FILE"):
        run_export(db, tmp_path, overwrite=True)
    path.unlink()
    run_export(db, tmp_path)
    path.write_text("Mi corrección")
    before = snapshot(tmp_path / "content")
    with pytest.raises(StageError, match="WEB_EXPORT_LOCAL_CHANGES"):
        run_export(db, tmp_path)
    assert snapshot(tmp_path / "content") == before
    run_export(db, tmp_path, overwrite=True)
    assert "Mi corrección" not in path.read_text()


def test_removes_only_owned_stale_pages(db, tmp_path):
    session, source = add_note(db, tmp_path)
    run_export(db, tmp_path)
    custom = tmp_path / "content/dcc/personal.md"
    custom.write_text("Mis apuntes personales")
    session.excluded = True
    db.commit()
    assert run_export(db, tmp_path)["files_removed"] == 3
    assert not (tmp_path / "content/dcc/modulo-532/semana-01.md").exists()
    assert not (tmp_path / "content/public/notes/dcc/modulo-532/semana-01.md").exists()
    assert custom.read_text() == "Mis apuntes personales" and source.exists()


@pytest.mark.parametrize("case", ["symlink", "manifest"])
def test_rejects_symlinks_and_manifest_traversal(db, tmp_path, case):
    add_note(db, tmp_path)
    run_export(db, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Privado")
    if case == "symlink":
        path = tmp_path / "content/dcc/modulo-532/semana-01.md"
        path.unlink()
        path.symlink_to(outside)
    else:
        manifest = tmp_path / "content/.export-dcc.json"
        manifest.write_text(json.dumps({"files": {"dcc/../../outside.md": digest("Privado")}}))
    with pytest.raises(StageError, match="WEB_EXPORT_(SYMLINK|MANIFEST_INVALID)"):
        run_export(db, tmp_path, overwrite=True)
    assert outside.read_text() == "Privado"


def test_rejects_duplicate_positions_before_writing(db, tmp_path):
    add_note(db, tmp_path)
    add_note(db, tmp_path, number=2, week=1)
    # Set a second resource to the same valid academic position.
    db.get(AcademicSession, "s-532-2").number = 1
    db.commit()
    with pytest.raises(StageError, match="WEB_EXPORT_DUPLICATE_POSITION"):
        run_export(db, tmp_path)
    assert not (tmp_path / "content").exists()


@pytest.mark.parametrize("corrupt", [False, True])
def test_cli_exports_snapshot_or_reports_integrity_failure(db, tmp_path, monkeypatch, capsys, corrupt):
    from academic_automation.cli import main

    _, source = add_note(db, tmp_path)
    settings = Settings(data_dir=tmp_path / "data", database_url=str(db.get_bind().url))
    monkeypatch.setattr("academic_automation.cli.Settings", lambda: settings)
    monkeypatch.setattr("academic_automation.cli.configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["academic", "export-web", "--program", "DCC",
                                    "--output", str(tmp_path / "content")])
    if corrupt:
        source.write_text("Modificado fuera del procesamiento")
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
        assert json.loads(capsys.readouterr().out) == {
            "status": "failed", "error_code": "ACADEMIC_NOTES_CHANGED"}
        assert not (tmp_path / "content").exists()
    else:
        main()
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "exported" and report["sessions"] == 1
        assert (tmp_path / "content/dcc/modulo-532/semana-01.md").exists()
