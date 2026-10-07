"""Verify the reusable rubric prefix is stable when read from disk."""

import hashlib
from pathlib import Path

EXPECTED_PREFIX_SHA256 = "19ea855b697d462bd73dcdbe9ea05256514efb3f275296518b0e253bceaa26ab"
STORY_SPECIFIC_MARKERS = (
    "121213",
    "121214",
    "121215",
    "121216",
    "SNAP",
    "Login Screen",
    "AC-1",
    "8 scenarios",
    "18 tests",
)


def test_rubric_prefix_hash_is_stable_and_story_agnostic() -> None:
    prefix_path = Path(__file__).resolve().parents[1] / "prompts" / "rubric_v1.md"

    first_read = prefix_path.read_bytes()
    second_read = prefix_path.read_bytes()
    first_hash = hashlib.sha256(first_read).hexdigest()
    second_hash = hashlib.sha256(second_read).hexdigest()

    assert first_hash == second_hash
    assert first_hash == EXPECTED_PREFIX_SHA256

    prefix_text = first_read.decode("utf-8")
    assert all(
        marker.casefold() not in prefix_text.casefold()
        for marker in STORY_SPECIFIC_MARKERS
    )
