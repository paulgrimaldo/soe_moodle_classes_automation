import json
from pathlib import Path

import pytest

from academic_automation.core.config import Settings
from academic_automation.core.security import sanitize


def test_private_paths_and_redaction(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.prepare()
    with pytest.raises(ValueError):
        settings.workdir("../../outside")
    value = sanitize("Cookie: auth=secret; other=hidden\nAuthorization: Bearer abc\nToken=ntn_abcdef\nhttps://a.b/?sesskey=private")
    assert all(secret not in value for secret in ("secret;", "hidden", "abc", "private"))


def test_workflows_use_http_and_env_only():
    files = sorted(Path("workflows").glob("*.json"))
    assert len(files) == 4
    for file in files:
        body = json.loads(file.read_text())
        assert not body["active"]
        assert body["settings"]["timezone"] == "America/La_Paz"
        request = next(n for n in body["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
        assert "$env.BACKEND_URL" in request["parameters"]["url"]
        assert "$env.N8N_BACKEND_TOKEN" in json.dumps(request)
        assert all("executeCommand" not in n["type"] for n in body["nodes"])
