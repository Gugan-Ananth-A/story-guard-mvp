"""Load the stable narrative prefix. The text is not formatted with story fields."""

from pathlib import Path


def load_prefix() -> str:
    """Return prompts/rubric_v1.md exactly. Callers append the score JSON after it."""
    path = Path(__file__).resolve().parents[2] / "prompts" / "rubric_v1.md"
    return path.read_text(encoding="utf-8")
