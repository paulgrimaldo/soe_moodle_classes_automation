from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModulePatch(StrictModel):
    export_number: int | None = Field(None, ge=1, strict=True)
    enabled: bool | None = None
    mode: Literal["ALL", "NEW_ONLY", "MANUAL"] | None = None
    auto_publish: bool | None = None


class SessionPatch(StrictModel):
    selected: bool | None = None
    excluded: bool | None = None
    week: int | None = Field(None, ge=1, le=8)
    class_in_week: int | None = Field(None, ge=1, le=2)
    class_date: date | None = None


class RecordingLinks(StrictModel):
    youtube_urls: list[str] = Field(min_length=1, max_length=8)

    @field_validator("youtube_urls")
    @classmethod
    def valid_videos(cls, values: list[str]) -> list[str]:
        from academic_automation.moodle.parsing import youtube

        normalized = []
        for value in values:
            video = youtube(value.strip()) if len(value) <= 2048 else None
            if video is None:
                raise ValueError("Indique enlaces válidos de YouTube")
            if video[1] in normalized:
                raise ValueError("Un video no puede repetirse entre las partes")
            normalized.append(video[1])
        return normalized


class ManualSessionCreate(RecordingLinks):
    number: int = Field(ge=1, le=8)
    class_date: date
    title: str = Field(default="", max_length=300)


class BulkSelection(StrictModel):
    session_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("session_ids")
    @classmethod
    def distinct_sessions(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not value or len(value) > 100 for value in values):
            raise ValueError("Seleccione sesiones distintas con identificadores válidos")
        return values


class BulkOperation(BulkSelection):
    operation: Literal["process", "reprocess", "publish"]
    request_id: UUID


class AcademicReviewDraft(StrictModel):
    source_job_id: str = Field(min_length=1, max_length=100)
    expected_review_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    markdown: str | None = Field(None, max_length=5_000_000)


class AcademicReviewApproval(AcademicReviewDraft):
    request_id: UUID
    acknowledge: Literal[True]
    reason: str = Field(min_length=8, max_length=2000)
    approved_finding_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("Explique el motivo de la aprobación")
        return value

    @field_validator("approved_finding_ids")
    @classmethod
    def distinct_findings(cls, values: list[str]) -> list[str]:
        import re
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[0-9a-f]{64}", v) for v in values):
            raise ValueError("Identificadores de hallazgos inválidos")
        return values


class NotionLink(StrictModel):
    page_id: str
    week: int = Field(0, ge=0, le=8)


class NotionRelink(NotionLink):
    previous_page_id: str
    acknowledge_replacement: Literal[True]


class SectionResolution(StrictModel):
    block_ids: list[str] = Field(min_length=1)
    acknowledge_overwrite: Literal[True]


class SessionNotes(StrictModel):
    session_id: str
    module_id: int
    program: Literal["DCC", "MIA"]
    module_name: str
    number: int | None
    week: int | None
    class_in_week: int | None
    class_date: date
    revision: int
    processing_status: str
    filename: str
    content_hash: str
    markdown: str


class CodexInput(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
    mode: Literal["automatic"] = "automatic"
    program: Literal["DCC", "MIA"]
    module_id: int = Field(gt=0)
    module_title: str = Field(min_length=1)
    number: int = Field(ge=1, le=8)
    week: int = Field(ge=1, le=8)
    class_in_week: int = Field(ge=1, le=2)
    transcript_file: Path

    @model_validator(mode="after")
    def academic_assignment(self):
        if self.program == "DCC" and self.class_in_week != 1:
            raise ValueError("DCC tiene una clase por semana")
        if self.program == "MIA" and self.week > 4:
            raise ValueError("MIA tiene cuatro semanas")
        return self


class ClassOutput(StrictModel):
    class_number: int = Field(ge=1, le=8)
    title: str = Field(min_length=1)
    markdown: str
    topics: list[str]
    warnings: list[str]


class CodexOutput(StrictModel):
    schema_version: Literal["1.0"]
    request_id: str
    status: Literal["ready", "needs_review"]
    warnings: list[str]
    classes: list[ClassOutput] = Field(min_length=1, max_length=1)
