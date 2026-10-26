import hashlib
import json
import logging
import re


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def sanitize(value: str) -> str:
    value = re.sub(r"(?im)^.*\b(?:cookie|authorization|password|sesskey)\s*[:=].*$", "[REDACTED CREDENTIAL LINE]", value)
    value = re.sub(r"(?i)(bearer\s+|(?:token|password|cookie|authorization|sesskey)[\s=:]+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"\b(?:ntn_|secret_|sk-)[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"https?://\S+", "[URL]", value)
    return value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "logger": record.name,
                           "message": sanitize(record.getMessage())}, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
