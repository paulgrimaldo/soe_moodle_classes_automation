from pathlib import Path

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError
from academic_automation.core.process import ProcessResult, run_process
from academic_automation.transcripts.adapter import TranscriptAdapter, classify_error

COOKIE_INFO = "Extracting cookies from chrome\nExtracted 2660 cookies from chrome\n"
SCRIPT_FAILURE = "[FALLIDO] No se pudo obtener subtitulo para: https://youtu.be/abcdefghijk\n"


@pytest.mark.parametrize("message,code,retryable", [
    ("Sign in to confirm you're not a bot", "YOUTUBE_AUTH_REQUIRED", False),
    ("No subtitles available", "SUBTITLES_NOT_AVAILABLE_YET", True),
    ("This video is still processing", "SUBTITLES_NOT_AVAILABLE_YET", True),
    ("Private video", "YOUTUBE_PERMANENT_ERROR", False),
    ("HTTP Error 429", "YOUTUBE_TRANSIENT_ERROR", True),
    (COOKIE_INFO + "[info] There are no subtitles for the requested languages",
     "SUBTITLES_NOT_AVAILABLE_YET", True),
    (COOKIE_INFO + "ERROR: HTTP Error 429\n" + SCRIPT_FAILURE, "YOUTUBE_TRANSIENT_ERROR", True),
    (COOKIE_INFO + "ERROR: Private video\n" + SCRIPT_FAILURE, "YOUTUBE_PERMANENT_ERROR", False),
    (COOKIE_INFO + "ERROR: Unexpected extractor failure", "TRANSCRIPT_DOWNLOAD_FAILED", False),
    ("ERROR: failed to load cookies", "YOUTUBE_AUTH_REQUIRED", False),
    ("ERROR: could not find chrome cookies database", "YOUTUBE_AUTH_REQUIRED", False),
    ("ERROR: Could not copy Chrome cookie database", "YOUTUBE_AUTH_REQUIRED", False),
    ("WARNING: cannot decrypt v10 cookies: no key found", "YOUTUBE_AUTH_REQUIRED", False),
])
def test_classification(message, code, retryable):
    error = classify_error(message)
    assert (error.code, error.retryable) == (code, retryable)


@pytest.mark.parametrize("diagnostic,code,retryable", [
    ("[info] There are no subtitles for the requested languages", "SUBTITLES_NOT_AVAILABLE_YET", True),
    ("ERROR: HTTP Error 429", "YOUTUBE_TRANSIENT_ERROR", True),
    ("ERROR: Private video", "YOUTUBE_PERMANENT_ERROR", False),
    ("ERROR: Sign in to confirm you're not a bot", "YOUTUBE_AUTH_REQUIRED", False),
])
async def test_download_classifies_diagnostic_with_successful_cookie_extraction(
        tmp_path, diagnostic, code, retryable):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()

    async def runner(args, **kwargs):
        Path(kwargs["env"]["ACADEMIC_YTDLP_LOG"]).write_text(COOKIE_INFO + diagnostic)
        return ProcessResult(123, "", SCRIPT_FAILURE)

    adapter = TranscriptAdapter(settings, runner)
    with pytest.raises(StageError) as caught:
        await adapter.download("session1", "https://youtu.be/abcdefghijk")
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert adapter.last_exit_code == 123


async def test_download_reuses_valid_files(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    calls = []
    async def runner(args, **kwargs):
        calls.append(args)
        work = kwargs["cwd"]
        (work / "clase1.txt").write_text("Texto académico completo.")
        (work / "clase1.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nTexto")
        return ProcessResult(0, "ok", "")
    adapter = TranscriptAdapter(settings, runner)
    first = await adapter.download("session1", "https://youtu.be/abcdefghijk")
    second = await adapter.download("session1", "https://youtu.be/abcdefghijk")
    assert first == second and len(calls) == 1
    assert "--keep-vtt" in calls[0]


async def test_process_timeout_kills_children(tmp_path):
    with pytest.raises(StageError, match="PROCESS_TIMEOUT"):
        await run_process(["/bin/sleep", "10"], cwd=tmp_path, timeout=0.05, log=tmp_path / "timeout.log")
