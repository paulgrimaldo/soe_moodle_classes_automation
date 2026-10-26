from typing import Protocol

from academic_automation.core.schemas import CodexInput


class MoodleGateway(Protocol):
    async def catalog(self) -> list[dict]: ...
    async def recordings(self, module_id: int) -> list[dict]: ...


class TranscriptGateway(Protocol):
    async def download(self, session_id: str, url: str) -> dict: ...


class AcademicProcessor(Protocol):
    async def process(self, request: CodexInput) -> dict: ...
