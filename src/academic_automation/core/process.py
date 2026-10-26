import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from academic_automation.core.errors import StageError
from academic_automation.core.security import sanitize


@dataclass
class ProcessResult:
    code: int
    stdout: str
    stderr: str


async def run_process(args: list[str], *, cwd: Path, timeout: int, log: Path,
                      env: dict[str, str] | None = None, stdin: str | None = None) -> ProcessResult:
    """Bounded output, no shell expansion, group termination including Bash/xargs children."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, env=env, start_new_session=True,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        raise StageError("EXECUTABLE_NOT_FOUND") from None

    async def read(stream):
        result = bytearray()
        while chunk := await stream.read(16384):
            if len(result) + len(chunk) > 8 * 1024 * 1024:
                raise StageError("PROCESS_OUTPUT_LIMIT")
            result.extend(chunk)
        return result.decode("utf-8", errors="replace")

    async def communicate():
        async def write():
            if stdin is not None:
                process.stdin.write(stdin.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
        _, out, err, _ = await asyncio.gather(write(), read(process.stdout), read(process.stderr), process.wait())
        return ProcessResult(process.returncode, out, err)

    try:
        result = await asyncio.wait_for(communicate(), timeout)
    except BaseException as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        log.write_text("PROCESS_TIMEOUT\n" if isinstance(error, TimeoutError) else "PROCESS_INTERRUPTED\n")
        if isinstance(error, TimeoutError):
            raise StageError("PROCESS_TIMEOUT", retryable=True) from None
        raise
    log.write_text(sanitize(f"exit_code={result.code}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"), encoding="utf-8")
    log.chmod(0o600)
    return result
