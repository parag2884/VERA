from __future__ import annotations

import logging
import re
from typing import Any

from app.config import get_settings

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|secret|password|token)\s*[:=]\s*([^\s,;]+)"
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_secrets(str(v)) for k, v in record.args.items()}
            else:
                record.args = tuple(redact_secrets(str(a)) for a in record.args)
        return True


def redact_secrets(text: str) -> str:
    return SECRET_PATTERN.sub(r"\1=***REDACTED***", text)


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(s in lowered for s in ("key", "secret", "password", "token", "authorization")):
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, str):
            redacted[key] = redact_secrets(value)
        else:
            redacted[key] = value
    return redacted


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.vera_log_level.upper())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.addFilter(RedactingFilter())
