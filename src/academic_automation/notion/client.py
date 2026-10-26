import asyncio
import random
import re
from uuid import UUID

import httpx

from academic_automation.core.errors import Conflict, StageError


def page_id(value: str) -> str:
    match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})(?:[?/#]|$)", value)
    if not match:
        raise ValueError("ID de Notion inválido")
    return str(UUID(match[1]))


class NotionClient:
    def __init__(self, settings, *, transport=None):
        if not settings.notion_token.get_secret_value():
            raise StageError("NOTION_TOKEN_MISSING")
        if settings.notion_version != "2026-03-11":
            raise StageError("NOTION_VERSION_REQUIRES_2026_03_11")
        self.client = httpx.AsyncClient(
            base_url="https://api.notion.com/v1/", timeout=45, transport=transport,
            headers={"Authorization": f"Bearer {settings.notion_token.get_secret_value()}",
                     "Notion-Version": settings.notion_version})
        self.lock = asyncio.Lock()
        self.next_request = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def request(self, method: str, path: str, **kwargs):
        for attempt in range(4):
            async with self.lock:
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, self.next_request - loop.time()))
                self.next_request = loop.time() + 0.4
                try:
                    response = await self.client.request(method, path, **kwargs)
                except httpx.TransportError:
                    if method not in {"GET", "DELETE"}:
                        raise Conflict("NOTION_WRITE_OUTCOME_UNKNOWN") from None
                    if attempt == 3:
                        raise StageError("NOTION_NETWORK_ERROR", retryable=True) from None
                    continue
            if response.status_code in {401, 403}:
                raise StageError("NOTION_PERMISSION_DENIED")
            if response.status_code == 404:
                raise Conflict("NOTION_OBJECT_UNAVAILABLE")
            if response.status_code in {429, 529}:
                try:
                    if response.json().get("additional_data", {}).get("rate_limit_reason") == "public_api_request_blocked":
                        raise StageError("NOTION_ACCESS_BLOCKED")
                    delay = max(float(response.headers.get("Retry-After", 2 ** attempt)), 0)
                except ValueError:
                    delay = 2 ** attempt
                await asyncio.sleep(delay + random.random() * 0.25)
                continue
            if response.status_code >= 500:
                if method not in {"GET", "DELETE"}:
                    raise Conflict("NOTION_WRITE_OUTCOME_UNKNOWN")
                await asyncio.sleep(2 ** attempt)
                continue
            if response.is_error:
                raise StageError("NOTION_INVALID_REQUEST")
            return response.json()
        raise StageError("NOTION_RATE_OR_SERVER_LIMIT", retryable=True)

    async def page(self, identifier):
        obj = await self.request("GET", f"pages/{identifier}")
        if obj.get("in_trash") or obj.get("archived"):
            raise Conflict("NOTION_PAGE_IN_TRASH")
        return obj

    async def block(self, identifier):
        return await self.request("GET", f"blocks/{identifier}")

    async def children(self, identifier):
        result, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            response = await self.request("GET", f"blocks/{identifier}/children", params=params)
            result.extend(response["results"])
            if not response.get("has_more"):
                return result
            cursor = response["next_cursor"]

    async def search(self, title):
        result, cursor = [], None
        while True:
            body = {"query": title, "filter": {"value": "page", "property": "object"}, "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            response = await self.request("POST", "search", json=body)
            result.extend(response["results"])
            if not response.get("has_more"):
                return result
            cursor = response["next_cursor"]

    async def create_week(self, parent: str, week: int):
        return await self.request("POST", "pages", json={"parent": {"page_id": parent},
            "properties": {"title": {"type": "title", "title": [{"type": "text", "text": {"content": f"Semana {week}"}}]}}})

    async def append(self, parent: str, blocks: list[dict], *, after: str | None = None, start=False):
        position = {"type": "start" if start else "end"}
        if after:
            position = {"type": "after_block", "after_block": {"id": after}}
        response = await self.request("PATCH", f"blocks/{parent}/children", json={"children": blocks, "position": position})
        return response["results"]

    async def delete(self, identifier):
        return await self.request("DELETE", f"blocks/{identifier}")
