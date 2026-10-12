"""Live ADO text is HTML. The Acceptance Criteria field is what the report scores."""

from story_guard.graph import _story_record_from_ado
from story_guard.score import score_health


def _story(**overrides):
    story = {
        "id": "121213",
        "title": "SNAP Login Screen",
        "type": "User Story",
        "state": "New",
        "description": "",
        "area": "Ecom MVP",
        "iteration": "Ecom MVP",
        "raw_ac_text": "",
        "acceptance_criteria": [],
    }
    story.update(overrides)
    return story


def _fixture():
    return {
        "id": "121213",
        "note": "",
        "tests": [],
        "bugs": [],
        "acceptance_criteria": [],
        "scenarios": [],
    }


def test_html_acceptance_criteria_are_scored_with_their_labels():
    raw_ac = (
        "<div><span>&nbsp; Scenario: AC-01 Successful login</span></div>"
        "<div>Expected: The user reaches the SNAP dashboard.</div>"
        "<div>Scenario: AC-02 Email required</div>"
        "<div>Expected: The Login button stays disabled.</div>"
    )
    description = (
        "<div>Scenario: Old description scenario</div>"
        "<div>Given the user is on the login page</div>"
    )
    record = _story_record_from_ado(
        _story(description=description, raw_ac_text=raw_ac),
        _fixture(),
    )

    assert [item["ac_id"] for item in record["acceptance_criteria"]] == ["AC-01", "AC-02"]
    assert record["acceptance_criteria"][0]["text"] == (
        "Successful login. The user reaches the SNAP dashboard."
    )
    assert record["acceptance_criteria"][0]["testable"] is True
    assert [item["ac_id"] for item in record["scenarios"]] == ["AC-1"]
    assert "login page" in record["scenarios"][0]["text"]

    score = score_health(record)
    assert score["ac_field"] == "present"
    assert score["scenario_count"] == 2
    assert [row["ac_id"] for row in score["scenarios"]] == ["AC-01", "AC-02"]
    assert score["none_count"] == 2


def test_html_description_is_scored_when_the_acceptance_criteria_field_is_empty():
    description = (
        "<div><span>&nbsp; Scenario: Successful login with valid credentials</span></div>"
        "<div>Expected: Authenticated and redirected to the SNAP dashboard.</div>"
    )
    record = _story_record_from_ado(_story(description=description), _fixture())

    assert record["acceptance_criteria"] == []
    assert record["scenarios"][0]["ac_id"] == "AC-1"
    assert "SNAP dashboard" in record["scenarios"][0]["text"]
    assert score_health(record)["scenario_count"] == 1


def test_plain_scenario_lines_still_split():
    description = (
        "Scenario: Empty email field\n"
        "Expected: Login button stays disabled\n\n"
        "Scenario: Empty password field\n"
        "Expected result: Login button stays disabled\n"
    )
    record = _story_record_from_ado(_story(description=description), _fixture())

    assert [item["ac_id"] for item in record["scenarios"]] == ["AC-1", "AC-2"]
    assert record["scenarios"][1]["text"] == "Empty password field. Login button stays disabled"
