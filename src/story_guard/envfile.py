"""Load the repo .env into the process. A variable already set in the shell wins."""

import os
from pathlib import Path


def env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


# The project file is the model selector. A shell export from an older edit
# must not keep sending a DeepSeek model name to Ollama.
FILE_OWNS = frozenset(
    {
        "STORY_GUARD_LLM",
        "STORY_GUARD_MODEL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
        "XAI_MODEL",
    }
)


def load_env_file(
    path: Path | None = None,
    *,
    file_owns: frozenset[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Set variables from KEY=VALUE lines. Blank values and comments are skipped.

    A variable already in the process is left alone, except names in
    ``file_owns``: those take the file value. Returns each replaced
    ``(key, previous, file_value)`` triple.
    """
    owned = file_owns or frozenset()
    replaced: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    file = env_path() if path is None else path
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return replaced
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, sep, raw_value = stripped.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        if key in os.environ and key not in owned:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value == "":
            continue
        seen.add(key)
        previous = os.environ.get(key)
        if previous == value:
            continue
        if previous is not None:
            replaced.append((key, previous, value))
        os.environ[key] = value
    # A model id left in the shell from an older provider must not survive
    # after that line is removed from the file.
    for key in owned:
        if key not in seen and key in os.environ:
            os.environ.pop(key, None)
    return replaced
