from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACADEMIC_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/academic.sqlite3"
    auth_enabled: bool = True
    admin_token: SecretStr = SecretStr("")
    n8n_token: SecretStr = SecretStr("")
    moodle_url: str = "https://soe.uagrm.edu.bo/virtual/my/courses.php"
    moodle_selectors_file: Path = Path("config/moodle-selectors.json")
    moodle_ignored_resources_file: Path = Path("config/moodle-ignored-resources.json")
    moodle_timeout: int = Field(60, ge=5)
    transcript_script: Path = Path("scripts/yt_transcripts.sh")
    transcript_timeout: int = Field(900, ge=1)
    codex_timeout: int = Field(1800, ge=1)
    codex_model: str = ""
    skill_path: Path = Path("~/.agents/skills/academic-transcription-to-notion")
    max_transcript_chars: int = Field(500_000, ge=1)
    notion_token: SecretStr = SecretStr("")
    notion_version: str = "2026-03-11"
    notion_dcc_root: str = ""
    notion_mia_root: str = ""
    publication_enabled: bool = False
    api_url: str = "http://127.0.0.1:8000"
    retry_base_seconds: int = Field(900, ge=1)
    max_attempts: int = Field(4, ge=1)

    def prepare(self) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)

    def workdir(self, *parts: str) -> Path:
        path = self.data_dir.joinpath(*parts).resolve()
        if not path.is_relative_to(self.data_dir.resolve()):
            raise ValueError("Ruta fuera del almacenamiento privado")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def moodle_state(self) -> Path:
        return self.workdir("private") / "moodle-state.json"
