"""Detect and redact credential-like text before it reaches reports or models."""

from __future__ import annotations

import copy
import re
from typing import Any

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*['\"]?)([^\s,;'\"<>]{8,})"
)
_BEARER_TOKEN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]{20,}")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"
)

_SECURITY_NOTICE = (
    "Credential-like content was detected and redacted before report and narrative generation."
)
_SECURITY_CLEAR = (
    "No credential-like content was detected by the targeted text check; this is not a comprehensive security scan."
)


def review_and_redact(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return a copy with credential-like string values redacted."""
    sanitized = copy.deepcopy(record)
    detected = [False]
    sanitized = _redact_value(sanitized, detected)
    findings = [_SECURITY_NOTICE if detected[0] else _SECURITY_CLEAR]
    sanitized["security_findings"] = findings
    return sanitized, findings


def _redact_value(value: Any, detected: list[bool]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, detected)
    if isinstance(value, list):
        return [_redact_value(item, detected) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_value(item, detected)
            for key, item in value.items()
        }
    return value


def _redact_text(value: str, detected: list[bool]) -> str:
    def replace_secret(match: re.Match[str]) -> str:
        detected[0] = True
        return f"{match.group(1)}[REDACTED]"

    text = _SECRET_ASSIGNMENT.sub(replace_secret, value)

    def replace_bearer(match: re.Match[str]) -> str:
        detected[0] = True
        return f"{match.group(1)}[REDACTED]"

    text = _BEARER_TOKEN.sub(replace_bearer, text)

    def replace_aws(match: re.Match[str]) -> str:
        detected[0] = True
        return "[REDACTED]"

    text = _AWS_ACCESS_KEY.sub(replace_aws, text)

    def replace_private_key(match: re.Match[str]) -> str:
        detected[0] = True
        return "[REDACTED PRIVATE KEY]"

    return _PRIVATE_KEY.sub(replace_private_key, text)
