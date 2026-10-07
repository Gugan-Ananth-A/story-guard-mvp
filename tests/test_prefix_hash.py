"""Verify the reusable rubric prefix is stable when read from disk."""

import hashlib
from pathlib import Path


def test_rubric_prefix_has_consistent_content_hash() -> None:
    prefix_path = Path(__file__).resolve().parents[1] / "prompts" / "rubric_v1.md"

    first_hash = hashlib.sha256(prefix_path.read_bytes()).hexdigest()
    second_hash = hashlib.sha256(prefix_path.read_bytes()).hexdigest()

    assert first_hash == second_hash
