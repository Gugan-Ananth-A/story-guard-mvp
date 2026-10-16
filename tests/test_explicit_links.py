"""Known suite 121215 cases score as gaps. None are adequate. AC-11 is partial."""

from story_guard.score import apply_explicit_links, score_health


def _criteria():
    return [
        {"ac_id": f"AC-{index:02d}", "text": f"Criterion {index}", "testable": True, "flags": []}
        for index in range(1, 13)
    ]


def _tests():
    titles = {
        "121216": "successful login",
        "121217": "empty email validation error",
        "121218": "empty password validation error",
        "121219": "both fields empty validation error",
        "121220": "invalid email format",
        "121221": "unregistered email",
        "121222": "incorrect password and field reset",
        "121223": "password masked by default",
        "121224": "show password",
        "121225": "hide password",
        "121226": "login stays disabled",
        "121227": "login becomes active",
        "121228": "forgot password",
        "121229": "leading spaces",
        "121230": "case insensitive email",
        "121231": "injection",
        "121232": "session refresh",
        "121233": "ui elements",
    }
    return [
        {
            "id": test_id,
            "title": title,
            "type": "",
            "mapped_ac_ids": [],
            "last_result": "",
            "last_result_at": None,
            "linked_bug_ids": [],
        }
        for test_id, title in titles.items()
    ]


def test_explicit_links_score_gaps_and_cover_login_retention():
    record = {
        "id": "121213",
        "title": "SNAP Login Screen",
        "acceptance_criteria": _criteria(),
        "scenarios": [],
        "tests": apply_explicit_links(_tests()),
        "bugs": [],
        "note": "",
    }
    score = score_health(record)
    by_id = {row["ac_id"]: row for row in score["scenarios"]}

    assert score["adequate_count"] == 0
    assert score["partial_count"] == 12
    assert score["none_count"] == 0
    assert by_id["AC-11"]["row_status"] == "partial"
    assert by_id["AC-11"]["mapped_test_ids"] == ["121220", "121221"]
    assert "No Positive scenarios Covered" in by_id["AC-11"]["gap"]
    assert "No Adhoc scenarios Covered" in by_id["AC-11"]["gap"]
    assert by_id["AC-01"]["mapped_test_ids"] == ["121216"]
    assert by_id["AC-01"]["row_status"] == "partial"
    assert by_id["AC-04"]["mapped_test_ids"] == ["121220"]
    assert by_id["AC-05"]["mapped_test_ids"] == ["121221", "121222"]
    assert by_id["AC-10"]["mapped_test_ids"] == ["121226", "121227"]
    assert score["mapped_count"] == 15
    unlinked = {"121217", "121218", "121219", "121229", "121230", "121231", "121232", "121233"}
    assert all(test["mapped_ac_ids"] == [] for test in record["tests"] if test["id"] in unlinked)
    assert "121222" not in by_id["AC-11"]["mapped_test_ids"]


def test_live_fetch_preserves_empty_source_links_for_model_review(monkeypatch):
    from story_guard.ado_client import ADOClient
    from story_guard.graph import _fetch_live

    class FakeADOClient:
        def __init__(self, story_id):
            self.story_id = story_id

        def load_live_story(self, story_id, test_plan_id=None):
            return {
                "id": self.story_id,
                "title": "SNAP Login Screen",
                "type": "User Story",
                "state": "New",
                "description": "",
                "area": "Ecom MVP",
                "iteration": "",
                "raw_ac_text": (
                    "Scenario: AC-11 Login page retention\n"
                    "Expected: The entered email remains."
                ),
                "tests": _tests(),
                "bugs": [],
            }

    def install(story_id):
        monkeypatch.setattr(
            ADOClient,
            "from_env",
            classmethod(lambda cls, story_id=story_id: FakeADOClient(story_id)),
        )
        return _fetch_live({"story_id": story_id, "test_plan_id": None})

    linked = {test["id"]: test for test in install("121213")["tests"]}
    assert linked["121220"]["mapped_ac_ids"] == []
    assert linked["121221"]["mapped_ac_ids"] == []
    assert linked["121222"]["mapped_ac_ids"] == []
    assert linked["121216"]["mapped_ac_ids"] == []

    other = {test["id"]: test for test in install("123086")["tests"]}
    assert other["121220"]["mapped_ac_ids"] == []
    assert other["121221"]["mapped_ac_ids"] == []
    assert other["121216"]["mapped_ac_ids"] == []
