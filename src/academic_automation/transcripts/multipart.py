"""One derived class transcript, retaining immutable source TXT/VTT per part."""

import json
import os
import re
import tempfile
from pathlib import Path

from academic_automation.core.errors import Conflict
from academic_automation.core.security import digest

STAMP = r"(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}"
CUE = re.compile(rf"^({STAMP})\s+-->\s+({STAMP})(.*)$")
INLINE = re.compile(rf"<({STAMP})>")


def milliseconds(value):
    fields = value.split(":")
    hours, minutes, seconds = (0, *fields) if len(fields) == 2 else fields
    seconds, ms = str(seconds).split(".")
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise Conflict("TRANSCRIPT_VTT_INVALID")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(ms)


def timestamp(value):
    seconds, ms = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def combine_vtt(documents):
    offset, body, globals_ = 0, [], []
    for part, document in enumerate(documents, 1):
        if not document.lstrip().startswith("WEBVTT"):
            raise Conflict("TRANSCRIPT_VTT_INVALID")
        last, cues = 0, 0
        body.append(f"NOTE Parte {part}")
        # YouTube auto-captions use space-only lines inside cue payloads.
        # Only a truly empty line separates blocks; preserve payload whitespace.
        normalized = document.replace("\r\n", "\n").strip("\n")
        for block in re.split(r"\n{2,}", normalized):
            lines = block.splitlines()
            if lines[0].startswith("WEBVTT"):
                continue
            if lines[0] in {"STYLE", "REGION"}:
                if block not in globals_:
                    globals_.append(block)
                continue
            if lines[0].startswith("NOTE"):
                body.append(block)
                continue
            index = 0 if "-->" in lines[0] else 1
            match = CUE.fullmatch(lines[index]) if index < len(lines) else None
            if not match:
                raise Conflict("TRANSCRIPT_VTT_INVALID")
            start, end = milliseconds(match[1]), milliseconds(match[2])
            if end < start:
                raise Conflict("TRANSCRIPT_VTT_INVALID")
            cues, last = cues + 1, max(last, end)
            timing = f"{timestamp(start + offset)} --> {timestamp(end + offset)}{match[3]}"
            payload = "\n".join(lines[index + 1:])
            payload = INLINE.sub(lambda m: f"<{timestamp(milliseconds(m[1]) + offset)}>", payload)
            body.append(f"parte-{part}-{cues}\n{timing}\n{payload}")
        if not cues:
            raise Conflict("TRANSCRIPT_VTT_INVALID")
        offset += last + 1
    return "WEBVTT\n\n" + "\n\n".join([*globals_, *body]) + "\n"


def atomic_text(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".multipart-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_entry(settings, entry):
    try:
        for kind in ("txt", "vtt"):
            path = Path(entry[f"{kind}_path"]).resolve()
            if not path.is_relative_to(settings.data_dir.resolve()) or not path.is_file():
                raise Conflict("TRANSCRIPT_ARTIFACT_CHANGED")
            if digest(path.read_bytes()) != entry[f"{kind}_hash"]:
                raise Conflict("TRANSCRIPT_ARTIFACT_CHANGED")
    except (KeyError, TypeError, OSError, ValueError):
        raise Conflict("TRANSCRIPT_PARTS_MANIFEST_INVALID") from None


def load_manifest(work, recordings):
    manifest_path = work / "manifest.json"
    ids = [part.video_id for part in recordings]
    if not manifest_path.exists():
        return {"video_ids": ids, "parts": []}
    try:
        manifest = json.loads(manifest_path.read_text())
        if manifest["video_ids"] != ids or not isinstance(manifest["parts"], list):
            raise ValueError("Parts changed")
        if [part["video_id"] for part in manifest["parts"]] != ids[:len(manifest["parts"])]:
            raise ValueError("Part order changed")
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise Conflict("TRANSCRIPT_PARTS_MANIFEST_INVALID") from None


def verify_multipart(settings, session_id, recordings):
    work = settings.workdir("transcripts", session_id, "combined")
    manifest = load_manifest(work, recordings)
    if len(manifest["parts"]) != len(recordings) or "combined" not in manifest:
        raise Conflict("TRANSCRIPT_PARTS_MANIFEST_INVALID")
    for entry in [*manifest["parts"], manifest["combined"]]:
        verify_entry(settings, entry)
    return manifest["combined"]


async def download_parts(adapter, settings, session_id, recordings):
    work = settings.workdir("transcripts", session_id, "combined")
    manifest = load_manifest(work, recordings)
    if "combined" in manifest:
        return verify_multipart(settings, session_id, recordings)
    for position, part in enumerate(recordings):
        if position < len(manifest["parts"]):
            verify_entry(settings, manifest["parts"][position])
            continue
        entry = await adapter.download(f"{session_id}/parts/{part.video_id}", part.url)
        verify_entry(settings, entry)
        manifest["parts"].append({"video_id": part.video_id, **entry})
        atomic_text(work / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    documents = [Path(entry["txt_path"]).read_text(encoding="utf-8").strip() for entry in manifest["parts"]]
    if any(not document for document in documents):
        raise Conflict("TRANSCRIPT_EMPTY_OR_TOO_LARGE")
    combined = "\n\n".join(f"PARTE {i} DE {len(documents)}\n\n{document}" for i, document in enumerate(documents, 1)) + "\n"
    vtt = combine_vtt([Path(entry["vtt_path"]).read_text(encoding="utf-8") for entry in manifest["parts"]])
    txt_path, vtt_path = work / "transcript.txt", work / "transcript.vtt"
    atomic_text(txt_path, combined)
    atomic_text(vtt_path, vtt)
    manifest["combined"] = {"txt_path": str(txt_path), "vtt_path": str(vtt_path),
                            "txt_hash": digest(txt_path.read_bytes()), "vtt_hash": digest(vtt_path.read_bytes())}
    atomic_text(work / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest["combined"]
