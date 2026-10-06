"""Load the local test-case fixture for the dummy TMS adapter."""

import json
from pathlib import Path
from typing import Any, Dict, List


FIXTURE_STORY_ID = "121213"
FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "FIX-121213.json"
)


class DummyTestAdapterError(Exception):
    """Raised when the local test fixture is missing or malformed."""


def fetch_tests(story_id: str) -> List[Dict[str, Any]]:
    """Return test rows for story 121213; other stories have no test pack."""
    if str(story_id) != FIXTURE_STORY_ID:
        return []

    try:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DummyTestAdapterError(
            "Could not load the sanitized 121213 test fixture"
        ) from error

    source_rows = fixture.get("tests") if isinstance(fixture, dict) else None
    if not isinstance(source_rows, list):
        raise DummyTestAdapterError("The 121213 fixture must contain a tests list")

    test_rows = []
    for row in source_rows:
        if not isinstance(row, dict):
            raise DummyTestAdapterError("Fixture test rows must be objects")

        test_id = row.get("id")
        title = row.get("title")
        mapped_ac_ids = row.get("mapped_ac_ids")
        if (
            test_id is None
            or not isinstance(title, str)
            or not isinstance(mapped_ac_ids, list)
            or not all(isinstance(ac_id, str) for ac_id in mapped_ac_ids)
        ):
            raise DummyTestAdapterError(
                "Fixture test rows must have an id, title, and mapped_ac_ids list"
            )

        test_rows.append(
            {
                "id": str(test_id),
                "title": title,
                "mapped_ac_ids": list(mapped_ac_ids),
            }
        )

    return test_rows
