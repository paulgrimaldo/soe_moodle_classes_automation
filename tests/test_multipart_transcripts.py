from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.errors import Conflict, StageError
from academic_automation.core.process import ProcessResult
from academic_automation.transcripts.adapter import TranscriptAdapter
from academic_automation.transcripts.multipart import combine_vtt, download_parts, verify_multipart

IDS = ["6dP-ykbwEIg", "_W__qxvQA_4"]
VTT = "WEBVTT\n\n00:00.000 --> 00:01.000 align:start\nTexto <00:00.500>académico\n"


def parts():
    return [SimpleNamespace(video_id=identifier, url=f"https://www.youtube.com/watch?v={identifier}", position=i)
            for i, identifier in enumerate(IDS, 1)]


def test_combined_vtt_adjusts_cues_and_inline_times_but_keeps_sources():
    combined = combine_vtt([VTT, VTT])
    assert combined.count("WEBVTT") == 1
    assert "00:00:01.001 --> 00:00:02.001 align:start" in combined
    assert "<00:00:01.501>" in combined
    assert combined.count("Texto") == 2


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_youtube_space_only_payload_lines_preserve_all_cues(newline):
    document = (
        "WEBVTT\nKind: captions\nLanguage: es\n\n"
        "00:00:00.000 --> 00:00:01.000 align:start position:0%\n"
        " \nahora<00:00:00.500><c> sí</c>\n\n"
        "00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
        "ahora sí\n \n\n"
    ).replace("\n", newline)
    combined = combine_vtt([document, document])
    assert combined.count(" --> ") == 4
    assert combined.count("\n \nahora") == 2
    assert combined.count("ahora sí\n \n") == 2
    assert "00:00:02.001 --> 00:00:03.001 align:start position:0%" in combined
    assert "ahora<00:00:02.501><c> sí</c>" in combined
    assert "parte-2-2\n00:00:03.001 --> 00:00:04.001" in combined


async def test_partial_failure_resumes_only_failed_part_and_preserves_order(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    calls = Counter()

    async def runner(args, **kwargs):
        identifier = kwargs["cwd"].name
        calls[identifier] += 1
        if identifier == IDS[1] and calls[identifier] == 1:
            return ProcessResult(1, "No subtitles available", "")
        (kwargs["cwd"] / "clase1.txt").write_text(f"Contenido {identifier}")
        (kwargs["cwd"] / "clase1.vtt").write_text(VTT)
        return ProcessResult(0, "", "")

    adapter = TranscriptAdapter(settings, runner)
    with pytest.raises(StageError, match="SUBTITLES_NOT_AVAILABLE_YET"):
        await download_parts(adapter, settings, "session", parts())
    result = await download_parts(adapter, settings, "session", parts())
    assert calls == {IDS[0]: 1, IDS[1]: 2}
    content = Path(result["txt_path"]).read_text()
    assert content.index(IDS[0]) < content.index(IDS[1])
    assert "PARTE 1 DE 2" in content and "PARTE 2 DE 2" in content
    assert result == await download_parts(adapter, settings, "session", parts())
    assert calls == {IDS[0]: 1, IDS[1]: 2}
    original_vtt = tmp_path / "transcripts/session/parts" / IDS[0] / "clase1.vtt"
    assert original_vtt.read_text() == VTT
    original_txt = original_vtt.with_suffix(".txt")
    original_txt.write_text("Cambio externo")
    with pytest.raises(Conflict, match="TRANSCRIPT_ARTIFACT_CHANGED"):
        verify_multipart(settings, "session", parts())


@pytest.mark.parametrize("bad", ["WEBVTT\n", "not VTT", "WEBVTT\n\n00:05.000 --> 00:01.000\ntexto"])
def test_invalid_part_is_not_silently_discarded(bad):
    with pytest.raises(Conflict, match="TRANSCRIPT_VTT_INVALID"):
        combine_vtt([VTT, bad])


async def test_source_order_changes_require_review(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    work = settings.workdir("transcripts", "session", "combined")
    (work / "manifest.json").write_text('{"video_ids":["6dP-ykbwEIg","_W__qxvQA_4"],"parts":[]}')
    with pytest.raises(Conflict, match="TRANSCRIPT_PARTS_MANIFEST_INVALID"):
        await download_parts(None, settings, "session", list(reversed(parts())))
