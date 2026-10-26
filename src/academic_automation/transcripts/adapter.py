import asyncio
import os
from pathlib import Path

from academic_automation.core.errors import StageError
from academic_automation.core.process import run_process
from academic_automation.core.security import digest, sanitize


def classify_error(message: str) -> StageError:
    text = message.lower()
    # yt-dlp reports successful cookie extraction on every authenticated request.
    # Only a failure to access cookies is evidence of an authentication problem.
    cookie_failure = any(
        "cookie" in line and any(marker in line for marker in (
            "failed to load", "cannot extract", "could not find", "could not copy",
            "could not read", "unable to extract", "unable to load", "permission denied",
            "does not look like a netscape",
        ))
        for line in text.splitlines()
    )
    if cookie_failure or any(s in text for s in ("sign in", "authentication", "decrypt", "keychain", "login required", "confirm you're not a bot")):
        return StageError("YOUTUBE_AUTH_REQUIRED")
    if any(s in text for s in ("private video", "video unavailable", "has been removed", "copyright", "not available in your country")):
        return StageError("YOUTUBE_PERMANENT_ERROR")
    # The Bash wrapper appends a generic missing-subtitle message even on network
    # failures. Preserve the more specific diagnostic so retries get the right cause.
    if any(s in text for s in ("429", "timed out", "network", "connection", "503", "502", "temporary")):
        return StageError("YOUTUBE_TRANSIENT_ERROR", retryable=True)
    if any(s in text for s in ("no subtitles", "no automatic captions", "no se pudo obtener subtitulo", "requested subtitles", "processing", "premiere", "live event will begin")):
        return StageError("SUBTITLES_NOT_AVAILABLE_YET", retryable=True)
    return StageError("TRANSCRIPT_DOWNLOAD_FAILED")


def valid_artifact(txt: Path, vtt: Path) -> bool:
    try:
        return (txt.is_file() and bool(txt.read_text(encoding="utf-8").strip())
                and vtt.is_file() and vtt.read_text(encoding="utf-8").lstrip().startswith("WEBVTT"))
    except (OSError, UnicodeError):
        return False


class TranscriptAdapter:
    def __init__(self, settings, runner=run_process):
        self.settings, self.runner = settings, runner
        self.limit = asyncio.Semaphore(2)
        self.last_exit_code = None

    async def download(self, session_id: str, url: str) -> dict:
        self.last_exit_code = None
        script = self.settings.transcript_script.expanduser().resolve()
        if not script.is_file():
            raise StageError("YT_TRANSCRIPTS_SCRIPT_MISSING")
        work = self.settings.workdir("transcripts", session_id)
        txt, vtt = work / "clase1.txt", work / "clase1.vtt"
        if not valid_artifact(txt, vtt):
            async with self.limit:
                env = {key: value for key, value in os.environ.items() if key in {
                    "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
                    "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY"}}
                diagnostic = work / "yt-dlp.log"
                env["ACADEMIC_YTDLP_LOG"] = str(diagnostic)
                try:
                    result = await self.runner(["/bin/bash", str(script), "--keep-vtt", "--workers", "1",
                                                "--from", "1", "--output-dir", str(work), url],
                                               cwd=work, timeout=self.settings.transcript_timeout,
                                               log=work / "execution.log", env=env)
                    self.last_exit_code = result.code
                    details = diagnostic.read_text(errors="replace") if diagnostic.exists() else ""
                    if result.code or not valid_artifact(txt, vtt):
                        raise classify_error(result.stdout + result.stderr + details)
                finally:
                    if diagnostic.exists():
                        diagnostic.write_text(sanitize(diagnostic.read_text(errors="replace")))
                        diagnostic.chmod(0o600)
        return {"txt_path": str(txt), "vtt_path": str(vtt),
                "txt_hash": digest(txt.read_bytes()), "vtt_hash": digest(vtt.read_bytes())}
