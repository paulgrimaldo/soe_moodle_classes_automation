from copy import deepcopy
from pathlib import Path
import shlex

from click.testing import CliRunner
from streamlit import config
from streamlit.runtime.credentials import Credentials
from streamlit.web import cli


def test_launcher_starts_dashboard_without_first_run_email_prompt(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = next(line for line in (root / "scripts/start-host.sh").read_text().splitlines()
                   if line.startswith("uv run streamlit "))
    args = shlex.split(command)[3:]
    monkeypatch.chdir(root)
    monkeypatch.setattr(config, "_config_options", deepcopy(config.get_config_options()))
    config.set_option("server.headless", False)
    config.set_option("browser.gatherUsageStats", False)
    monkeypatch.setattr(Credentials, "_singleton", None)
    credentials_file = tmp_path / "streamlit-credentials.toml"
    monkeypatch.setattr("streamlit.runtime.credentials._get_credential_file_path", lambda: str(credentials_file))
    started = []
    monkeypatch.setattr(cli.bootstrap, "run", lambda *args, **kwargs: started.append((args, kwargs)))

    # Real Streamlit CLI and onboarding, empty stdin, no stored credentials, no socket binding.
    result = CliRunner().invoke(cli.main, args, input="")

    assert result.exit_code == 0, result.output
    assert started, result.output
    assert "Email:" not in result.output
    assert not credentials_file.exists()
