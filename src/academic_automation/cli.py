import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from academic_automation.core.config import Settings
from academic_automation.core.security import configure_logging


def main():
    parser = argparse.ArgumentParser(prog="academic")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("worker")
    commands.add_parser("moodle-login")
    inspect = commands.add_parser("moodle-inspect")
    inspect.add_argument("--url")
    recordings_inspect = commands.add_parser("moodle-recordings-inspect", help="Inspeccionar grabaciones sin crear sesiones")
    recordings_inspect.add_argument("--module-id", required=True, type=int)
    sync = commands.add_parser("sync-recordings", help="Descubrir y guardar sesiones con el código actual del host")
    sync.add_argument("--module-id", required=True, type=int)
    notion_inspect = commands.add_parser("notion-inspect", help="Diagnóstico de solo lectura de una clase publicada")
    notion_inspect.add_argument("--session-id", required=True, type=UUID)
    web_export = commands.add_parser("export-web", help="Exportar apuntes vigentes para el visor web")
    web_export.add_argument("--program", choices=("DCC", "MIA"), default="DCC")
    web_export.add_argument("--output", type=Path, default=Path("content"))
    web_export.add_argument("--overwrite", action="store_true", help="Reemplazar ediciones en archivos ya exportados")
    notion_capture = commands.add_parser("notion-capture", help="Capturar apuntes históricos sin escribir en Notion")
    notion_capture.add_argument("--mapping", required=True, type=Path)
    notion_capture.add_argument("--output", required=True, type=Path)
    notion_import = commands.add_parser("import-notion", help="Revisar o incorporar una captura histórica local")
    notion_import.add_argument("--snapshot", required=True, type=Path)
    notion_import.add_argument("--apply", action="store_true", help="Guardar revisiones; por defecto solo muestra la propuesta")
    args = parser.parse_args()
    settings = Settings()
    settings.prepare()
    configure_logging()
    if args.command in {"notion-capture", "import-notion"}:
        from academic_automation.core.errors import StageError
        try:
            if args.command == "notion-capture":
                from academic_automation.notion.archive import capture
                report = asyncio.run(capture(settings, args.mapping, args.output))
            else:
                from academic_automation.database.session import factory, make_engine
                from academic_automation.services.imported_notes import import_snapshot
                engine = make_engine(settings.database_url)
                try:
                    with factory(engine)() as db:
                        report = import_snapshot(settings, db, args.snapshot, apply=args.apply)
                finally:
                    engine.dispose()
        except StageError as error:
            print(json.dumps({"status": "failed", "error_code": error.code}, ensure_ascii=False, indent=2))
            raise SystemExit(1) from None
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "export-web":
        from academic_automation.core.errors import StageError
        from academic_automation.database.session import factory, make_engine
        from academic_automation.services.web_export import WebExportNumberingError, export_web
        engine = make_engine(settings.database_url)
        try:
            with factory(engine)() as db:
                report = export_web(settings, db, args.output, args.program, overwrite=args.overwrite)
        except StageError as error:
            report = {"status": "failed", "error_code": error.code}
            if isinstance(error, WebExportNumberingError):
                report["issues"] = error.issues
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(1) from None
        finally:
            engine.dispose()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "doctor":
        import sys
        from academic_automation.academic.processor import load_skill
        print(f"Python: {sys.version.split()[0]}")
        for command in ("uv", "codex", "yt-dlp", "node", "docker"):
            path = shutil.which(command)
            if path:
                result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
                print(f"{command}: {result.stdout.strip().splitlines()[0] if result.stdout.strip() else 'disponible'}")
            else:
                print(f"{command}: AUSENTE")
        try:
            _, sha = load_skill(settings.skill_path)
            print(f"Skill: disponible, contrato 1.0, sha256={sha}")
        except Exception:
            print("Skill: AUSENTE o inválida")
        try:
            from importlib.metadata import version
            print(f"Playwright: {version('playwright')}; verificar binario con playwright install chromium")
        except ImportError:
            print("Playwright: AUSENTE")
        print(f"Script: {'disponible' if settings.transcript_script.is_file() else 'AUSENTE'}")
        print(f"Sesión Moodle: {'guardada; vigencia sin verificar' if settings.moodle_state.exists() else 'pendiente'}")
    elif args.command == "worker":
        from academic_automation.orchestration.worker import main as worker_main
        worker_main()
    elif args.command == "sync-recordings":
        from academic_automation.core.errors import StageError
        from academic_automation.orchestration.manual_sync import sync_module_now
        if args.module_id <= 0:
            parser.error("--module-id debe ser un entero positivo")
        try:
            report = asyncio.run(sync_module_now(settings, args.module_id))
        except StageError as error:
            print(json.dumps({"status": "failed", "error_code": error.code}, ensure_ascii=False, indent=2))
            raise SystemExit(1) from None
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "notion-inspect":
        from academic_automation.core.errors import StageError
        from academic_automation.notion.inspection import save_inspection
        try:
            report = asyncio.run(save_inspection(settings, str(args.session_id)))
        except StageError as error:
            print(json.dumps({"status": "failed", "error_code": error.code}, ensure_ascii=False, indent=2))
            raise SystemExit(1) from None
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        from academic_automation.moodle.client import MoodleClient
        client = MoodleClient(settings)
        if args.command == "moodle-recordings-inspect":
            if args.module_id <= 0:
                parser.error("--module-id debe ser un entero positivo")
            report = asyncio.run(client.inspect_recordings(args.module_id))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if report["status"] == "failed":
                raise SystemExit(1)
        elif args.command == "moodle-login":
            asyncio.run(client.login())
        else:
            from academic_automation.core.errors import StageError
            try:
                report = asyncio.run(client.inspect(args.url or settings.moodle_url))
            except StageError as error:
                print(json.dumps({"status": "failed", "error_code": error.code,
                                  "diagnostic_file": str(settings.workdir("private") / "moodle-progress.json")},
                                 ensure_ascii=False, indent=2))
                raise SystemExit(1) from None
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
