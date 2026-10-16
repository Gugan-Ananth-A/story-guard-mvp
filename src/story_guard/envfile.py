"""Load the repo .env into the process. A variable already set in the shell wins."""

import os
from pathlib import Path


def env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def load_env_file(path: Path | None = None) -> None:
    """Set unset variables from KEY=VALUE lines. Blank values and comments are skipped."""
    file = env_path() if path is None else path
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, sep, raw_value = stripped.partition("=")
        key = key.strip()
        if not sep or not key or key in os.environ:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value == "":
            continue
        os.environ[key] = value
