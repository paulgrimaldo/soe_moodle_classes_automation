import json
import re
from datetime import date
from urllib.parse import parse_qs, urlencode, urljoin, urlparse


COURSE = re.compile(r"(?<![\w-])(MIA|DCC)-(V[\w]+)\s*-\s*(\d+)\s*\.\s*(.+)$", re.I)
# Shared with JavaScript's RegExp in the readiness check: keep syntax compatible.
# Includes the observed module 505 wording without "de": "Grabación sesión síncrona".
RECORDING = re.compile(
    r"grabaci[oó]n(?:es)?\s+(?:de\s+)?sesi[oó]n(?:es)?\s+s[ií]ncronas?\s*-\s*"
    r"(?:(?:semana|encuentro)\s+\d+\s*)?\(?\s*(\d{2}/\d{2}/(?:\d{4}|\d{2}))(?!\d)", re.I)
SYNCHRONOUS_SECTION = re.compile(r"\bsesiones?\s+s[ií]ncronas?\b", re.I)
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def course_metadata(title: str, url: str) -> dict | None:
    # Moodle cards prepend accessibility labels or repeat the cohort before the full title.
    match = COURSE.search(" ".join(title.split()))
    parsed = urlparse(url)
    ids = parse_qs(parsed.query).get("id", [])
    if not match or not parsed.path.endswith("/course/view.php") or not ids or not ids[0].isdigit():
        return None
    program, cohort, number, name = match.groups()
    return {"program": program.upper(), "cohort": cohort.upper(), "module_number": int(number),
            "module_name": name.strip(), "moodle_course_id": int(ids[0])}


def course_name_quality(course: dict) -> tuple[bool, int]:
    name = course["module_name"].strip()
    return (not name.endswith(("...", "…")), len(name))


def course_from_link(link: dict) -> dict | None:
    labels = [link.get("title", ""), *link.get("labels", [])]
    matches = [course for label in labels if (course := course_metadata(label, link["href"]))]
    return max(matches, key=course_name_quality) if matches else None


def youtube(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url if not url.startswith("//") else "https:" + url)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    parts = parsed.path.strip("/").split("/")
    video = None
    if host in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        video = parts[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            video = parts[1]
        elif parsed.path == "/watch":
            video = parse_qs(parsed.query).get("v", [None])[0]
    if video and VIDEO_ID.fullmatch(video):
        return video, f"https://www.youtube.com/watch?v={video}"
    return None


def resource_metadata(title: str, href: str, base_url: str) -> dict | None:
    match = RECORDING.search(title)
    if not match:
        return None
    url = urljoin(base_url, href)
    parsed, base = urlparse(url), urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname != base.hostname or not parsed.path.startswith("/virtual/"):
        return None
    identifier = parse_qs(parsed.query).get("id", [None])[0]
    if not identifier or not identifier.isdigit():
        return None
    day, month, year = match[1].split("/")
    # This platform's two-digit postgraduate dates refer to 2000..2099;
    # avoid strptime's implicit 1969/2068 century pivot.
    try:
        class_date = date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
    except ValueError:
        return None
    return {"resource_key": f"{parsed.path}:{identifier}", "resource_url": url,
            "title": " ".join(title.split()), "date": class_date}


def recording_section_urls(links: list[dict], module_id: int, base_url: str) -> set[str]:
    """Follow observed course section links, never guess section numbers or endpoints."""
    urls = set()
    for link in links:
        labels = " ".join([link.get("title", ""), *link.get("labels", [])])
        parsed = urlparse(urljoin(base_url, link["href"]))
        query = parse_qs(parsed.query)
        section = query.get("section", [""])[0]
        if (SYNCHRONOUS_SECTION.search(labels) and parsed.scheme == "https"
                and parsed.hostname == urlparse(base_url).hostname
                and parsed.path.endswith("/course/view.php")
                and query.get("id") == [str(module_id)] and section.isdigit()):
            urls.add(parsed._replace(query=urlencode({"id": module_id, "section": section}), fragment="").geturl())
    return urls


def player_source_urls(configurations: list[str]) -> list[str]:
    """Read Moodle's observed data-setup-lazy JSON without executing player scripts."""
    urls = []
    for raw in configurations:
        try:
            config = json.loads(raw)
        except (ValueError, TypeError):
            continue
        sources = config.get("sources", []) if isinstance(config, dict) else []
        if isinstance(sources, list):
            urls.extend(source["src"] for source in sources
                        if isinstance(source, dict) and isinstance(source.get("src"), str))
    return urls
