import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from filelock import FileLock, Timeout
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

from academic_automation.core.errors import Conflict, StageError
from academic_automation.core.security import sanitize
from academic_automation.moodle.parsing import (
    RECORDING, SYNCHRONOUS_SECTION, course_from_link, course_name_quality,
    player_source_urls, recording_section_urls, resource_metadata, youtube,
)

CLIENT_REVISION = "recordings-9"


class MoodleClient:
    """No Moodle-specific DOM selectors are assumed. Inspection config is optional."""

    def __init__(self, settings):
        self.settings = settings
        path = settings.moodle_selectors_file
        self.selectors = json.loads(path.read_text()) if path.exists() else {}
        self.operation = "browser_launch"

    def progress(self, operation=None, *, error_code=None):
        """Small private checkpoint, independent of DOM access and exception text."""
        if operation:
            self.operation = operation
        report = {"client_revision": CLIENT_REVISION, "pid": os.getpid(),
                  "timestamp": datetime.now(timezone.utc).isoformat(),
                  "operation": self.operation, "error_code": error_code}
        path = self.settings.workdir("private") / "moodle-progress.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(report, output, ensure_ascii=False)

    @asynccontextmanager
    async def browser(self, *, supervised=False):
        lock = FileLock(str(self.settings.workdir("private") / "moodle.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            raise StageError("MOODLE_BROWSER_BUSY", retryable=True) from None
        try:
            self.progress("browser_launch")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=not supervised)
                state = self.settings.moodle_state
                self.progress("browser_context")
                context = await browser.new_context(storage_state=str(state) if state.exists() else None)
                context.set_default_timeout(self.settings.moodle_timeout * 1000)
                try:
                    page = await context.new_page()
                    yield page
                finally:
                    await context.close()
                    await browser.close()
        except PlaywrightTimeout:
            code = f"MOODLE_{self.operation.upper()}_TIMEOUT"
            self.progress(error_code=code)
            raise StageError(code, retryable=True) from None
        except StageError as error:
            self.progress(error_code=error.code)
            raise
        finally:
            lock.release()

    async def check_auth(self, page):
        if "/login/" in page.url or await page.locator('input[type="password"]').count():
            raise StageError("MOODLE_SESSION_EXPIRED")

    async def open(self, page, url):
        parsed, base = urlparse(url), urlparse(self.settings.moodle_url)
        if parsed.hostname != base.hostname or parsed.scheme != "https":
            raise StageError("MOODLE_UNTRUSTED_URL")
        self.progress("navigation")
        response = await page.goto(url, wait_until="domcontentloaded")
        if response and response.status >= 400:
            raise StageError("MOODLE_HTTP_ERROR", retryable=response.status >= 500)
        self.progress("authentication_check")
        await self.check_auth(page)
        if self.selectors.get("ready_selector"):
            self.progress("page_ready")
            await page.locator(self.selectors["ready_selector"]).wait_for()

    async def login(self):
        async with self.browser(supervised=True) as page:
            await page.goto(self.settings.moodle_url)
            await asyncio.to_thread(input, "Inicie sesión en el navegador y pulse Enter aquí para guardar: ")
            await page.goto(self.settings.moodle_url, wait_until="domcontentloaded")
            await self.check_auth(page)
            path = self.settings.moodle_state
            await page.context.storage_state(path=str(path))
            path.chmod(0o600)

    async def links(self, page, container=""):
        self.progress("links")
        scope = page.locator(container) if container else page
        if container and await scope.count() != 1:
            raise Conflict("MOODLE_CONTAINER_AMBIGUOUS")
        return await scope.locator("a[href]").evaluate_all(
            """els => els.map(a => {
                const labels = [...new Set([a.innerText, a.textContent, a.title,
                    a.getAttribute('aria-label'), ...Array.from(a.querySelectorAll('img[alt]'), i => i.alt)]
                    .filter(Boolean).map(t => t.trim()).filter(Boolean))];
                return {title: labels[0] || '', href: a.href, labels};
            })""")

    async def prepare_catalog(self, page):
        grouping = self.selectors.get("catalog_grouping_label")
        all_courses = self.selectors.get("catalog_all_courses_label")
        operation = "catalog_ready"
        try:
            self.progress(operation)
            # DOMContentLoaded precedes Moodle's asynchronous event registration.
            # This catalog-only marker was observed in the institutional DOM.
            ready = self.selectors.get("catalog_ready_selector")
            if ready:
                await page.locator(ready).wait_for(state="attached")
            if grouping and all_courses:
                operation = "catalog_filter_state"
                self.progress(operation)
                option = page.get_by_role("menuitem", name=all_courses, exact=True, include_hidden=True)
                if await option.get_attribute("aria-current") != "true":
                    button = page.get_by_role("button", name=grouping, exact=True)
                    operation = "catalog_filter_open"
                    self.progress(operation)
                    if await button.get_attribute("aria-expanded") != "true":
                        await button.click()
                    operation = "catalog_filter_select"
                    self.progress(operation)
                    await option.click()
            operation = "catalog_courses"
            self.progress(operation)
            # Course cards are populated asynchronously after DOMContentLoaded.
            await page.wait_for_function("""() => Array.from(document.querySelectorAll('a[href]')).some(a => {
                const u = new URL(a.href, document.baseURI);
                return u.origin === location.origin && u.pathname.endsWith('/course/view.php')
                    && /^\\d+$/.test(u.searchParams.get('id') || '');
            })""", timeout=self.settings.moodle_timeout * 1000)
        except PlaywrightTimeout:
            await self.check_auth(page)
            await self.save_catalog_inspection(page, operation=operation)
            if operation == "catalog_ready":
                raise StageError("MOODLE_CATALOG_READY_TIMEOUT", retryable=True) from None
            if operation.startswith("catalog_filter"):
                raise Conflict("MOODLE_CATALOG_FILTER_TIMEOUT") from None
            raise Conflict("MOODLE_CATALOG_DOM_REQUIRES_INSPECTION") from None

    async def catalog_inspection(self, page, links=None):
        links = links if links is not None else await self.links(page)
        candidates = []
        for link in links:
            parsed = urlparse(link["href"])
            if parsed.hostname != urlparse(self.settings.moodle_url).hostname or not parsed.path.endswith("/course/view.php"):
                continue
            identifier = parse_qs(parsed.query).get("id", [""])[0]
            course = course_from_link(link)
            if course:
                course = {key: sanitize(value) if isinstance(value, str) else value for key, value in course.items()}
            candidates.append({"title": sanitize(link["title"]), "path": parsed.path,
                               "moodle_course_id": int(identifier) if identifier.isdigit() else None,
                               "labels": [sanitize(label) for label in link.get("labels", [])],
                               "course": course})
        return {"title": sanitize(await page.title()), "page_path": urlparse(page.url).path,
                "link_count": len(links), "course_links": candidates}

    async def save_catalog_inspection(self, page, *, operation="catalog_parse"):
        self.progress("catalog_inspection")
        report = await self.catalog_inspection(page)
        report["operation"] = operation
        target = self.settings.workdir("private") / "moodle-catalog-inspection.json"
        with target.open("w", encoding="utf-8") as output:
            target.chmod(0o600)
            output.write(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    async def catalog(self):
        if not self.settings.moodle_state.exists():
            raise StageError("MOODLE_LOGIN_REQUIRED")
        courses = {}
        async with self.browser() as page:
            await self.open(page, self.settings.moodle_url)
            await self.prepare_catalog(page)
            for _ in range(100):
                # Allow ordinary lazy rendering without assuming Moodle-specific selectors.
                previous = -1
                for _ in range(10):
                    links = await self.links(page, self.selectors.get("catalog_container", ""))
                    for link in links:
                        if urlparse(link["href"]).hostname == urlparse(self.settings.moodle_url).hostname:
                            item = course_from_link(link)
                            if item:
                                previous_item = courses.get(item["moodle_course_id"])
                                if previous_item is None or course_name_quality(item) > course_name_quality(previous_item):
                                    courses[item["moodle_course_id"]] = item
                    if len(links) == previous:
                        break
                    previous = len(links)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(800)
                next_selector = self.selectors.get("catalog_next")
                if not next_selector:
                    break
                nxt = page.locator(next_selector)
                if not await nxt.count() or not await nxt.is_visible() or await nxt.is_disabled():
                    break
                await nxt.click()
                await page.wait_for_timeout(1000)
                await self.check_auth(page)
            else:
                raise Conflict("MOODLE_PAGINATION_LIMIT")
            if not courses:
                await self.save_catalog_inspection(page)
                raise Conflict("MOODLE_CATALOG_DOM_REQUIRES_INSPECTION")
        return list(courses.values())

    async def save_recordings_inspection(self, page, module_id: int):
        links = await self.links(page)
        resources = []
        for link in links:
            parsed = urlparse(link["href"])
            if parsed.hostname == urlparse(self.settings.moodle_url).hostname and "/mod/" in parsed.path:
                identifier = parse_qs(parsed.query).get("id", [""])[0]
                resources.append({"title": sanitize(link["title"]), "path": parsed.path,
                                  "resource_id": int(identifier) if identifier.isdigit() else None})
        report = {"module_id": module_id, "page_path": urlparse(page.url).path,
                  "link_count": len(links), "resource_links": resources}
        target = self.settings.workdir("private") / f"moodle-recordings-{module_id}-inspection.json"
        with target.open("w", encoding="utf-8") as output:
            target.chmod(0o600)
            json.dump(report, output, ensure_ascii=False, indent=2)

    async def wait_recording_links(self, page, module_id: int, *, initial=False):
        self.progress("recording_links_ready")
        try:
            await page.wait_for_function("""patterns => Array.from(document.querySelectorAll('a[href]')).some(a => {
                const text = [a.textContent, a.getAttribute('aria-label')].filter(Boolean).join(' ');
                return patterns.some(pattern => new RegExp(pattern, 'i').test(text));
            })""", arg=[RECORDING.pattern, *([SYNCHRONOUS_SECTION.pattern] if initial else [])],
                timeout=self.settings.moodle_timeout * 1000)
        except PlaywrightTimeout:
            await self.check_auth(page)
            await self.save_recordings_inspection(page, module_id)
            raise Conflict("MOODLE_RECORDINGS_DOM_REQUIRES_INSPECTION") from None

    async def save_video_inspection(self, page, module_id, item, evidence):
        """Record only normalized video IDs/URLs and safe resource metadata."""
        resource = urlparse(item["resource_url"])
        current = urlparse(page.url)
        identifier = parse_qs(resource.query).get("id", [""])[0]
        current_id = parse_qs(current.query).get("id", [""])[0]
        report = {"client_revision": CLIENT_REVISION, "module_id": module_id,
                  "resource_key": item["resource_key"], "resource_title": sanitize(item["title"]),
                  "resource_path": resource.path, "resource_id": int(identifier) if identifier.isdigit() else None,
                  "class_date": item["date"].isoformat(), "page_path": current.path,
                  "page_item_id": int(current_id) if current_id.isdigit() else None,
                  "page_title": sanitize(await page.title()),
                  "candidate_videos": [{**value, "sources": sorted(value["sources"])}
                                       for _, value in sorted(evidence.items())]}
        target = self.settings.workdir("private") / f"moodle-videos-{module_id}-inspection.json"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(report, output, ensure_ascii=False, indent=2)
        # Keep every conflict: later resources must not erase earlier evidence.
        specific = target.with_name(f"moodle-videos-{module_id}-{identifier}-inspection.json")
        descriptor = os.open(specific, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(report, output, ensure_ascii=False, indent=2)

    async def recordings(self, module_id: int, *, allow_partial=False):
        items = {}
        ignored_file = self.settings.moodle_ignored_resources_file
        try:
            ignored_config = json.loads(ignored_file.read_text()) if ignored_file.exists() else {}
            if not isinstance(ignored_config, dict):
                raise ValueError("Invalid ignored resources")
            ignored = ignored_config.get(str(module_id), {})
            if (not isinstance(ignored, dict)
                    or any(not key or not isinstance(reason, str) or not reason.strip()
                           for key, reason in ignored.items())):
                raise ValueError("Invalid ignored resources")
        except (ValueError, OSError):
            raise Conflict("MOODLE_IGNORED_RESOURCES_CONFIG_INVALID") from None
        ignored_found = False
        parts_file = self.settings.workdir("private") / "moodle-recording-parts.json"
        try:
            overrides = json.loads(parts_file.read_text()) if parts_file.exists() else {}
            overrides = overrides.get(str(module_id), {})
            if not isinstance(overrides, dict):
                raise ValueError("Invalid overrides")
        except (ValueError, AttributeError):
            raise Conflict("MOODLE_RECORDING_PARTS_CONFIG_INVALID") from None
        async with self.browser() as page:
            url = urljoin(self.settings.moodle_url, f"../course/view.php?id={module_id}")
            await self.open(page, url)
            await self.wait_recording_links(page, module_id, initial=True)
            section_urls = recording_section_urls(await self.links(page), module_id, self.settings.moodle_url)
            if len(section_urls) > 1:
                raise Conflict("MOODLE_RECORDINGS_SECTION_AMBIGUOUS")
            if section_urls:
                await self.open(page, next(iter(section_urls)))
                await self.wait_recording_links(page, module_id)
            links = await self.links(page, self.selectors.get("recordings_section", ""))
            for link in links:
                for label in [link.get("title", ""), *link.get("labels", [])]:
                    item = resource_metadata(label, link["href"], self.settings.moodle_url)
                    if item:
                        if item["resource_key"] in ignored:
                            ignored_found = True
                            break
                        items[item["resource_key"]] = item
                        break
            if not items and not ignored_found:
                await self.save_recordings_inspection(page, module_id)
                raise Conflict("MOODLE_RECORDINGS_DOM_REQUIRES_INSPECTION")
            for item in items.values():
                await self.open(page, item["resource_url"])
                self.progress("recording_video")
                candidates = {"page": [page.url],
                              "media": await page.locator("iframe[src], video[src], source[src]").evaluate_all("els => els.map(e => e.src)")}
                configurations = await page.locator("[data-setup-lazy]").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-setup-lazy'))")
                candidates["player"] = player_source_urls(configurations)
                candidates["links"] = [link["href"] for link in await self.links(page)]
                videos, evidence = {}, {}
                for kind, urls in candidates.items():
                    for url in urls:
                        if video := youtube(url):
                            videos[video[0]] = video
                            evidence.setdefault(video[0], {"video_id": video[0], "url": video[1], "sources": set()})["sources"].add(kind)
                configured = overrides.get(item["resource_key"])
                if configured is not None and (not isinstance(configured, list) or not 2 <= len(configured) <= 8
                        or any(not isinstance(v, str) for v in configured)
                        or len(set(configured)) != len(configured) or set(configured) != set(videos)):
                    await self.save_video_inspection(page, module_id, item, evidence)
                    raise Conflict("MOODLE_RECORDING_PARTS_CHANGED")
                if len(videos) > 1 and configured is None:
                    self.progress("recording_video_conflict")
                    await self.save_video_inspection(page, module_id, item, evidence)
                    if not allow_partial:
                        raise Conflict("MOODLE_MULTIPLE_VIDEOS")
                    item["discovery_error"] = "MOODLE_MULTIPLE_VIDEOS"
                    item["video_candidates"] = [{"video_id": identifier, "url": videos[identifier][1]}
                                                for identifier in sorted(videos)]
                    await asyncio.sleep(1)
                    continue
                if videos:
                    ordered = [videos[identifier] for identifier in configured] if configured else list(videos.values())
                    item["video_id"], item["url"] = ordered[0]
                    if configured:
                        item["videos"] = [{"video_id": video[0], "url": video[1]} for video in ordered]
                await asyncio.sleep(1)
        return list(items.values())

    async def inspect_recordings(self, module_id: int):
        """Run the read-only discovery client; never persist sessions or process classes."""
        try:
            items = await self.recordings(module_id, allow_partial=True)
        except StageError as error:
            if error.code in {"MOODLE_MULTIPLE_VIDEOS", "MOODLE_RECORDING_PARTS_CHANGED"}:
                filename = f"moodle-videos-{module_id}-inspection.json"
            elif error.code == "MOODLE_RECORDINGS_DOM_REQUIRES_INSPECTION":
                filename = f"moodle-recordings-{module_id}-inspection.json"
            else:
                filename = "moodle-progress.json"
            return {"status": "failed", "module_id": module_id, "error_code": error.code,
                    "diagnostic_file": str(self.settings.workdir("private") / filename),
                    "database_changes": False, "processing_started": False}
        reviews = [item for item in items if item.get("discovery_error")]
        if reviews:
            return {"status": "failed", "module_id": module_id, "error_code": "MOODLE_MULTIPLE_VIDEOS",
                    "recordings_found": len(items), "review_resources": [item["resource_key"] for item in reviews],
                    "diagnostic_file": str(self.settings.workdir("private") / f"moodle-videos-{module_id}-inspection.json"),
                    "database_changes": False, "processing_started": False}
        return {"status": "completed", "module_id": module_id, "recordings_found": len(items),
                "videos_identified": sum(len(item["videos"]) if item.get("videos") else bool(item.get("video_id")) for item in items),
                "database_changes": False, "processing_started": False}

    async def inspect(self, url: str) -> dict:
        async with self.browser(supervised=True) as page:
            await self.open(page, url)
            if urlparse(url).path == urlparse(self.settings.moodle_url).path:
                await self.prepare_catalog(page)
            # Only safe diagnostic fields, never raw HTML, input values, cookies or URL queries.
            links = await self.links(page)
            return {**await self.catalog_inspection(page, links), "links": [
                {"title": sanitize(l["title"]), "path": urlparse(l["href"]).path,
                 "course": course_from_link(l)} for l in links],
                "iframes": await page.locator("iframe").count()}
