"""Validate/export saved Codex responses without invoking a model or publishing."""

import json

from pydantic import ValidationError

from academic_automation.core.errors import StageError
from academic_automation.core.markdown_math import academic_markdown_parser
from academic_automation.core.schemas import CodexOutput
from academic_automation.core.security import digest, sanitize


class CodexOutputError(StageError):
    def __init__(self, diagnostic):
        super().__init__("CODEX_OUTPUT_INVALID", review=True)
        self.diagnostic = diagnostic


def validation_diagnostic(stage, error, *, skill=None, raw=None):
    diagnostic = {"stage": stage, "reason": "Salida inválida para el contrato académico."}
    if isinstance(error, ValidationError):
        diagnostic["issues"] = [{"field": sanitize(".".join(map(str, e["loc"])))[:160], "type": e["type"]}
                                for e in error.errors(include_input=False, include_url=False)[:10]]
    elif skill is not None and isinstance(error, skill.Failure):
        diagnostic["reason"] = sanitize(str(error))[:500]
        pattern = getattr(skill, "ADMINISTRATIVE", None)
        findings = []

        def scan(value, field=""):
            if len(findings) >= 10:
                return
            if isinstance(value, str) and pattern is not None:
                for match in pattern.finditer(value):
                    findings.append({"field": field, "line": value.count("\n", 0, match.start()) + 1,
                                     "match": sanitize(match[0])[:100]})
                    if len(findings) >= 10:
                        break
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    scan(item, f"{field}.{index}")
            elif isinstance(value, dict):
                # Output schema already rejected unknown fields before academic lint.
                for key, item in value.items():
                    scan(item, f"{field}.{key}".strip("."))

        scan(raw)
        if findings:
            diagnostic["findings"] = findings
    elif stage == "identity":
        diagnostic["reason"] = "La salida no corresponde al request_id o número de clase solicitado."
    elif stage == "response_json":
        diagnostic["reason"] = "Falta response.json o no contiene JSON UTF-8 válido."
    elif stage == "export":
        diagnostic["reason"] = "No se pudo exportar el paquete en un directorio nuevo."
    return diagnostic


def validate_academic_response(request, skill_request, raw, skill):
    """The same validation gates, without writing a bundle (used by human review)."""
    stage = "output_schema"
    try:
        parsed = CodexOutput.model_validate(raw)
        stage = "identity"
        if parsed.request_id != request.request_id or parsed.classes[0].class_number != request.number:
            raise ValueError("Output identity mismatch")
        stage = "academic_lint"
        skill.validate_result(skill_request, raw)
        stage = "markdown"
        for item in parsed.classes:
            academic_markdown_parser().parse(item.markdown)
        return parsed
    except (ValueError, OSError, skill.Failure) as error:
        raise CodexOutputError(validation_diagnostic(stage, error, skill=skill, raw=raw)) from None


def export_academic_response(request, skill_request, sources, raw, output, skill, skill_hash, *, model=None):
    """Reuse the installed skill unchanged; a caller must supply a new output directory."""
    parsed = validate_academic_response(request, skill_request, raw, skill)
    try:
        metadata = skill.export_bundle(skill_request, sources, raw, output)
    except (ValueError, OSError, skill.Failure) as error:
        raise CodexOutputError(validation_diagnostic("export", error, skill=skill, raw=raw)) from None
    metadata.update({"contract_extension": "single-class-v1", "skill_version": "1.0",
                     "lint_extension": "text-examples-v1",
                     "skill_sha256": skill_hash, "codex_model": model,
                     "session_number": request.number, "class_in_week": request.class_in_week})
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    if parsed.status == "needs_review":
        raise StageError("ACADEMIC_NEEDS_REVIEW", review=True)
    notes = output / "notes.md"
    if not notes.is_file() or digest(notes.read_bytes()) != metadata["content_sha256"]:
        raise StageError("ACADEMIC_ARTIFACT_HASH_MISMATCH", review=True)
    return {"status": "completed", "title": parsed.classes[0].title, "markdown_file": str(notes),
            "content_hash": metadata["content_sha256"], "skill_version": "1.0", "skill_hash": skill_hash,
            "model": model, "metadata": metadata}
