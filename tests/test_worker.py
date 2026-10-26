import json

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.security import digest
from academic_automation.database.models import AcademicSession, NotionPage, now
from academic_automation.orchestration.queue import claim, enqueue
from academic_automation.orchestration.worker import Worker
from academic_automation.services.catalog import sync_recordings
from fakes import FakeNotion
from test_foundation import module
from test_moodle import recording


class FakeTranscript:
    def __init__(self, root):
        self.root, self.calls = root, 0
    async def download(self, session_id, url):
        self.calls += 1
        target = self.root / session_id
        target.mkdir()
        txt, vtt = target / "source.txt", target / "source.vtt"
        txt.write_text("Transcripción de prueba")
        vtt.write_text("WEBVTT\n")
        return {"txt_path": str(txt), "vtt_path": str(vtt), "txt_hash": digest(txt.read_bytes()),
                "vtt_hash": digest(vtt.read_bytes())}


class FakeProcessor:
    def __init__(self, root):
        self.root, self.calls = root, 0
    async def process(self, request):
        self.calls += 1
        out = self.root / request.request_id
        out.mkdir()
        notes = out / "notes.md"
        notes.write_text(f"# Clase {request.number}: Prueba\n\nTexto procesado {self.calls}\n")
        (out / "metadata.json").write_text(json.dumps({"status": "ready", "content_sha256": digest(notes.read_bytes())}))
        return {"markdown_file": str(notes), "content_hash": digest(notes.read_bytes()),
                "model": "simulated", "skill_version": "1.0", "skill_hash": "test-hash"}


async def run_job(worker, db, kind, **kwargs):
    job = enqueue(db, kind, **kwargs)
    job = claim(db)
    await worker.execute(db, job)
    return job


async def test_end_to_end_two_classes_publish_and_reprocess(db, tmp_path):
    settings = Settings(data_dir=tmp_path, publication_enabled=True)
    settings.prepare()
    m = module(db)
    sync_recordings(db, m, [recording("r1", 5, "abcdefghijk"), recording("r2", 9, "bcdefghijkl")])
    sessions = list(db.scalars(select(AcademicSession).order_by(AcademicSession.number)))
    transcripts, processor, notion = FakeTranscript(tmp_path), FakeProcessor(tmp_path), FakeNotion()
    parent = notion.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="module"))
    db.commit()
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=transcripts, processor=processor,
                    notion_factory=lambda: notion)
    for s in reversed(sessions):
        assert (await run_job(worker, db, "process", session_id=s.id, module_id=m.id)).status == "COMPLETED"
        assert (await run_job(worker, db, "publish", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert transcripts.calls == 2 and processor.calls == 2
    assert all(s.publication_status == "PUBLISHED" for s in sessions)
    assert len(notion.pages) == 2  # module + one shared week, never per-class pages
    s = sessions[0]
    await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    assert transcripts.calls == 2 and processor.calls == 2
    await run_job(worker, db, "reprocess", session_id=s.id, module_id=m.id)
    assert transcripts.calls == 2 and processor.calls == 3
    assert (await run_job(worker, db, "publish", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert len(notion.pages) == 2


async def test_retry_backoff_preserves_independent_state(db, tmp_path):
    settings = Settings(data_dir=tmp_path, retry_base_seconds=900)
    settings.prepare()
    m = module(db)
    sync_recordings(db, m, [recording("r1", 5, "abcdefghijk")])
    s = db.scalar(select(AcademicSession))
    class NotReady:
        async def download(self, *args):
            raise StageError("SUBTITLES_NOT_AVAILABLE_YET", retryable=True)
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=NotReady())
    before = now()
    job = await run_job(worker, db, "process", session_id=s.id, module_id=m.id)
    assert job.status == "RETRY_WAIT" and (job.available_at - before).total_seconds() >= 900
    assert s.processing_status == "PENDING" and s.publication_status == "PENDING"
    assert s.transcript_status == "FAILED"


async def test_disable_cancels_queued_automatic_work(db, tmp_path):
    m = module(db)
    settings = Settings(data_dir=tmp_path)
    worker = Worker(settings, sessionmaker(db.get_bind()))
    job = await run_job(worker, db, "recordings", module_id=m.id, automatic=True)
    assert job.status == "CANCELLED"


async def test_recording_job_distinguishes_discovered_from_new_sessions(db, tmp_path):
    from unittest.mock import AsyncMock

    m = module(db)
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    moodle = type("Moodle", (), {"recordings": AsyncMock(return_value=[recording("r1", 5, "abcdefghijk")])})()
    worker = Worker(settings, sessionmaker(db.get_bind()), moodle=moodle)
    first = await run_job(worker, db, "recordings", module_id=m.id)
    second = await run_job(worker, db, "recordings", module_id=m.id)

    assert first.status == second.status == "COMPLETED"
    assert first.result == {"recordings_found": 1, "new_sessions": 1, "videos_identified": 1}
    assert second.result == {"recordings_found": 1, "new_sessions": 0, "videos_identified": 1}
    assert len(list(db.scalars(select(AcademicSession)))) == 1


async def test_multipart_class_generates_and_publishes_once_and_checks_original_parts(db, tmp_path):
    from academic_automation.core.process import ProcessResult
    from academic_automation.database.models import Recording, NotionSection
    from academic_automation.transcripts.adapter import TranscriptAdapter
    from test_recording_parts import multipart

    settings = Settings(data_dir=tmp_path, publication_enabled=True)
    settings.prepare()
    m = module(db)
    m.program = "DCC"
    db.commit()
    sync_recordings(db, m, [multipart()])
    s = db.scalar(select(AcademicSession))
    calls = []

    async def runner(args, **kwargs):
        calls.append(args[-1])
        (kwargs["cwd"] / "clase1.txt").write_text(f"Contenido {kwargs['cwd'].name}")
        (kwargs["cwd"] / "clase1.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nContenido\n")
        return ProcessResult(0, "", "")

    class CompleteClassProcessor(FakeProcessor):
        async def process(self, request):
            source = Path(request.transcript_file).read_text()
            assert source.index("6dP-ykbwEIg") < source.index("_W__qxvQA_4")
            assert "PARTE 1 DE 2" in source and "PARTE 2 DE 2" in source
            return await super().process(request)

    from pathlib import Path
    processor = CompleteClassProcessor(tmp_path)
    notion = FakeNotion()
    parent = notion.add_page()
    db.add(NotionPage(module_id=m.id, week=0, page_id=parent, url="module"))
    db.commit()
    worker = Worker(settings, sessionmaker(db.get_bind()), transcripts=TranscriptAdapter(settings, runner),
                    processor=processor, notion_factory=lambda: notion)
    assert (await run_job(worker, db, "process", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert len(calls) == 2 and processor.calls == 1
    assert len(list(db.scalars(select(Recording)))) == 2
    assert len(list(db.scalars(select(AcademicSession)))) == 1
    assert (await run_job(worker, db, "publish", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert len(notion.pages) == 2 and len(list(db.scalars(select(NotionSection)))) == 1
    assert (await run_job(worker, db, "process", session_id=s.id, module_id=m.id)).status == "COMPLETED"
    assert len(calls) == 2 and processor.calls == 1
    original = tmp_path / "transcripts" / s.id / "parts/_W__qxvQA_4/clase1.txt"
    original.write_text("Edición manual externa")
    failed = await run_job(worker, db, "reprocess", session_id=s.id, module_id=m.id)
    assert failed.status == "REVIEW_REQUIRED" and failed.error_code == "TRANSCRIPT_ARTIFACT_CHANGED"
    assert processor.calls == 1


async def test_sync_review_resource_does_not_hide_other_sessions(db, tmp_path):
    from unittest.mock import AsyncMock

    m = module(db)
    good = recording("r1", 5, "abcdefghijk")
    review = {"resource_key": "r2", "title": "Grabación con dos videos", "date": good["date"],
              "resource_url": "https://example.org/r2", "discovery_error": "MOODLE_MULTIPLE_VIDEOS",
              "video_candidates": [{"video_id": "bcdefghijkl", "url": "https://youtu.be/bcdefghijkl"},
                                   {"video_id": "cdefghijklm", "url": "https://youtu.be/cdefghijklm"}]}
    moodle = type("Moodle", (), {"recordings": AsyncMock(return_value=[good, review])})()
    worker = Worker(Settings(data_dir=tmp_path), sessionmaker(db.get_bind()), moodle=moodle)
    job = await run_job(worker, db, "recordings", module_id=m.id)
    assert job.status == "REVIEW_REQUIRED" and job.error_code == "MOODLE_MULTIPLE_VIDEOS"
    assert job.result["new_sessions"] == 2 and len(job.result["reviews"]) == 1
    sessions = list(db.scalars(select(AcademicSession).order_by(AcademicSession.resource_key)))
    assert sessions[0].discovery_status == "VIDEO_IDENTIFIED"
    assert sessions[1].discovery_status == "REVIEW_REQUIRED"
    assert not m.review_required
