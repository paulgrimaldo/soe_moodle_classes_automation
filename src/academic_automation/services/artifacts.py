from pathlib import Path

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.schemas import SessionNotes
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicModule, AcademicSession

MAX_NOTES_BYTES = 5_000_000


def read_notes(settings: Settings, session: AcademicSession, module: AcademicModule) -> SessionNotes:
    """Serve the last committed revision, including while a new attempt is running."""
    if not session.output_path:
        raise StageError("ACADEMIC_NOTES_NOT_READY")
    try:
        path = Path(session.output_path).resolve()
        root = settings.data_dir.resolve()
        if path.suffix != ".md" or not any(path.is_relative_to(root / folder)
                                           for folder in ("processed", "reconciled")):
            raise StageError("ACADEMIC_NOTES_PATH_INVALID")
        with path.open("rb") as source:
            content = source.read(MAX_NOTES_BYTES + 1)
    except FileNotFoundError:
        raise StageError("ACADEMIC_NOTES_FILE_MISSING") from None
    except (OSError, ValueError, RuntimeError):
        raise StageError("ACADEMIC_NOTES_UNREADABLE") from None
    if len(content) > MAX_NOTES_BYTES:
        raise StageError("ACADEMIC_NOTES_TOO_LARGE")
    content_hash = digest(content)
    if content_hash != session.content_hash:
        raise StageError("ACADEMIC_NOTES_CHANGED")
    try:
        markdown = content.decode("utf-8")
    except UnicodeError:
        raise StageError("ACADEMIC_NOTES_UNREADABLE") from None
    return SessionNotes(session_id=session.id, module_id=module.id, program=module.program,
                        module_name=module.name, number=session.number, week=session.week,
                        class_in_week=session.class_in_week, class_date=session.class_date,
                        revision=session.revision, processing_status=session.processing_status,
                        filename=f"{module.program}-{module.id}-sesion-{session.number or session.id}.md",
                        content_hash=content_hash, markdown=markdown)
