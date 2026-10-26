from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class AcademicProgram(Base):
    __tablename__ = "academic_programs"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String)
    weeks: Mapped[int] = mapped_column(Integer)
    classes_per_week: Mapped[int] = mapped_column(Integer)
    modules: Mapped[list[AcademicModule]] = relationship(back_populates="program_record", lazy="raise")


class AcademicModule(Base):
    __tablename__ = "academic_modules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Moodle course ID
    program: Mapped[str] = mapped_column(ForeignKey("academic_programs.code"), index=True)
    cohort: Mapped[str] = mapped_column(String)
    module_number: Mapped[int] = mapped_column(Integer)
    export_number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String, default="MANUAL")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    proposed_assignments: Mapped[list | None] = mapped_column(JSON)
    last_catalog_sync: Mapped[datetime | None] = mapped_column(DateTime)
    last_recording_sync: Mapped[datetime | None] = mapped_column(DateTime)
    program_record: Mapped[AcademicProgram] = relationship(back_populates="modules", lazy="raise")
    sessions: Mapped[list[AcademicSession]] = relationship(back_populates="module", lazy="raise")
    notion_pages: Mapped[list[NotionPage]] = relationship(back_populates="module", lazy="raise")


class AcademicSession(Base):
    __tablename__ = "academic_sessions"
    __table_args__ = (UniqueConstraint("module_id", "resource_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    module_id: Mapped[int] = mapped_column(ForeignKey("academic_modules.id"), index=True)
    resource_key: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    class_date: Mapped[date] = mapped_column(Date, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    number: Mapped[int | None] = mapped_column(Integer)
    week: Mapped[int | None] = mapped_column(Integer)
    class_in_week: Mapped[int | None] = mapped_column(Integer)
    manual_assignment: Mapped[bool] = mapped_column(Boolean, default=False)
    recordings_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    discovery_status: Mapped[str] = mapped_column(String, default="DISCOVERED")
    transcript_status: Mapped[str] = mapped_column(String, default="TRANSCRIPT_PENDING")
    processing_status: Mapped[str] = mapped_column(String, default="PENDING")
    publication_status: Mapped[str] = mapped_column(String, default="PENDING")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    output_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    module: Mapped[AcademicModule] = relationship(back_populates="sessions", lazy="raise")
    recordings: Mapped[list[Recording]] = relationship(back_populates="session", lazy="raise", order_by="Recording.position")
    transcript: Mapped[TranscriptArtifact | None] = relationship(back_populates="session", lazy="raise")
    jobs: Mapped[list[ProcessingJob]] = relationship(back_populates="session", lazy="raise")
    publication: Mapped[NotionSection | None] = relationship(back_populates="session", lazy="raise")


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("session_id", "position", name="uq_recording_part"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("academic_sessions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    video_id: Mapped[str] = mapped_column(String(11), unique=True)
    url: Mapped[str] = mapped_column(String)
    resource_url: Mapped[str] = mapped_column(String)
    session: Mapped[AcademicSession] = relationship(back_populates="recordings", lazy="raise")


class TranscriptArtifact(Base):
    __tablename__ = "transcript_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("academic_sessions.id"), unique=True)
    txt_path: Mapped[str] = mapped_column(Text)
    vtt_path: Mapped[str] = mapped_column(Text)
    txt_hash: Mapped[str] = mapped_column(String)
    vtt_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    session: Mapped[AcademicSession] = relationship(back_populates="transcript", lazy="raise")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("uq_active_job", "active_key", unique=True,
              sqlite_where=text("status IN ('QUEUED','RUNNING','RETRY_WAIT')")),
        Index("ix_job_queue", "status", "available_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String)
    active_key: Mapped[str] = mapped_column(String)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("academic_sessions.id"), index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("academic_modules.id"))
    status: Mapped[str] = mapped_column(String, default="QUEUED")
    stage: Mapped[str | None] = mapped_column(String)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    skill_version: Mapped[str | None] = mapped_column(String)
    skill_hash: Mapped[str | None] = mapped_column(String)
    result: Mapped[dict | None] = mapped_column(JSON)
    session: Mapped[AcademicSession | None] = relationship(back_populates="jobs", lazy="raise")
    logs: Mapped[list[ExecutionLog]] = relationship(back_populates="job", lazy="raise")


class NotionPage(Base):
    __tablename__ = "notion_pages"
    __table_args__ = (UniqueConstraint("module_id", "week"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("academic_modules.id"))
    week: Mapped[int] = mapped_column(Integer, default=0)  # 0 = existing module page
    page_id: Mapped[str] = mapped_column(String, unique=True)
    url: Mapped[str] = mapped_column(String)
    divider_id: Mapped[str | None] = mapped_column(String)
    module: Mapped[AcademicModule] = relationship(back_populates="notion_pages", lazy="raise")


class NotionSection(Base):
    __tablename__ = "notion_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("academic_sessions.id"), unique=True)
    page_id: Mapped[str] = mapped_column(String, index=True)
    block_ids: Mapped[list] = mapped_column(JSON, default=list)
    remote_hash: Mapped[str | None] = mapped_column(String)
    content_hash: Mapped[str | None] = mapped_column(String)  # Rendered payload; legacy rows held source hash.
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    session: Mapped[AcademicSession] = relationship(back_populates="publication", lazy="raise")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String)
    event: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    job: Mapped[ProcessingJob] = relationship(back_populates="logs", lazy="raise")


class MonitorEvent(Base):
    __tablename__ = "monitor_events"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
