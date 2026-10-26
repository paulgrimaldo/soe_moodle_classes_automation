import json
import sys
from unittest.mock import AsyncMock

import pytest

from academic_automation.cli import main
from academic_automation.core.config import Settings
from academic_automation.core.errors import StageError


def test_inspector_reports_known_failure_without_traceback(tmp_path, monkeypatch, capsys):
    settings = Settings(data_dir=tmp_path, moodle_selectors_file=tmp_path / "selectors.json")
    monkeypatch.setattr("academic_automation.cli.Settings", lambda: settings)
    monkeypatch.setattr("academic_automation.cli.configure_logging", lambda: None)
    monkeypatch.setattr("academic_automation.moodle.client.MoodleClient.inspect",
                        AsyncMock(side_effect=StageError("MOODLE_NAVIGATION_TIMEOUT", retryable=True)))
    monkeypatch.setattr(sys, "argv", ["academic", "moodle-inspect"])

    with pytest.raises(SystemExit) as error:
        main()

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert error.value.code == 1
    assert result["status"] == "failed" and result["error_code"] == "MOODLE_NAVIGATION_TIMEOUT"
    assert result["diagnostic_file"] == str(tmp_path / "private/moodle-progress.json")
    assert captured.err == ""


@pytest.mark.parametrize("failed", [True, False])
def test_recordings_inspection_cli_is_read_only_and_returns_summary(tmp_path, monkeypatch, capsys, failed):
    settings = Settings(data_dir=tmp_path, moodle_selectors_file=tmp_path / "selectors.json")
    monkeypatch.setattr("academic_automation.cli.Settings", lambda: settings)
    monkeypatch.setattr("academic_automation.cli.configure_logging", lambda: None)
    report = {"status": "failed" if failed else "completed", "module_id": 197,
              "database_changes": False, "processing_started": False}
    if failed:
        report.update(error_code="MOODLE_MULTIPLE_VIDEOS", diagnostic_file=str(tmp_path / "private/inspection.json"))
    inspector = AsyncMock(return_value=report)
    monkeypatch.setattr("academic_automation.moodle.client.MoodleClient.inspect_recordings", inspector)
    monkeypatch.setattr(sys, "argv", ["academic", "moodle-recordings-inspect", "--module-id", "197"])
    if failed:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    else:
        main()
    assert json.loads(capsys.readouterr().out) == report
    inspector.assert_awaited_once_with(197)


def test_manual_sync_cli_reports_saved_sessions_even_with_reviews(tmp_path, monkeypatch, capsys):
    settings = Settings(data_dir=tmp_path)
    report = {"status": "REVIEW_REQUIRED", "new_sessions": 4, "recordings_found": 4, "reviews": [{"resource_key": "week4"}]}
    sync = AsyncMock(return_value=report)
    monkeypatch.setattr("academic_automation.cli.Settings", lambda: settings)
    monkeypatch.setattr("academic_automation.cli.configure_logging", lambda: None)
    monkeypatch.setattr("academic_automation.orchestration.manual_sync.sync_module_now", sync)
    monkeypatch.setattr(sys, "argv", ["academic", "sync-recordings", "--module-id", "197"])
    main()
    assert json.loads(capsys.readouterr().out) == report
    sync.assert_awaited_once_with(settings, 197)
