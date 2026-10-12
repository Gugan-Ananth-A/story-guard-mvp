"""The same criterion text maps the same tests on every story."""

from story_guard.report_layout import _depth_and_gap, _facts
from story_guard.score import apply_behavior_links, score_health


def _tests():
    titles = {
        "121216": "Verify successful login with valid registered email and correct password",
        "121217": "Verify validation error when email field is left empty",
        "121220": "Verify validation error for incorrectly formatted email",
        "121221": "Verify error message for unregistered email",
        "121222": "Verify error message and field reset for incorrect password",
        "121224": "Verify Show toggle reveals the entered password",
        "121226": "Verify Login button remains disabled when required fields are empty",
        "121227": "Verify Login button becomes active once valid inputs are entered",
        "121228": "Verify navigation to the Forgot Password flow",
        "121229": "Verify leading/trailing spaces in the email field are handled correctly",
        "121231": "Verify system handles malicious input in the email field",
        "121233": "Verify all UI elements are displayed correctly on the login page",
    }
    return [
        {"id": test_id, "title": title, "type": "", "mapped_ac_ids": []}
        for test_id, title in titles.items()
    ]


def _ids(tests, test_id):
    row = next(item for item in tests if item["id"] == test_id)
    return list(row["mapped_ac_ids"]), row["type"]


def test_shared_login_text_maps_the_same_tests():
    text = (
        "Successful login. The user enters the email and the correct password "
        "and is authenticated and redirected to the dashboard."
    )
    admin = apply_behavior_links([{"ac_id": "AC-01", "text": text}], _tests())
    screen = apply_behavior_links([{"ac_id": "AC-01", "text": text}], _tests())
    assert _ids(admin, "121216") == _ids(screen, "121216")
    assert _ids(admin, "121216")[0] == ["AC-01"]
    assert _ids(admin, "121216")[1] == "happy"
    assert "AC-01" in _ids(admin, "121229")[0]
    assert _ids(admin, "121217")[0] == []


def test_invalid_credentials_show_and_forgot_agree_across_ids():
    criteria = [
        {
            "ac_id": "AC-02",
            "text": (
                "Invalid credentials. A registered email with the wrong password "
                "shows an error and the user stays on the login page."
            ),
        },
        {
            "ac_id": "AC-03",
            "text": "Password visibility — Show. When the user clicks Show, the password is plain text.",
        },
        {
            "ac_id": "AC-04",
            "text": "Forgot Password navigation. The user is redirected to the password recovery page.",
        },
    ]
    linked = apply_behavior_links(criteria, _tests())
    assert _ids(linked, "121221")[0] == ["AC-02"]
    assert _ids(linked, "121222")[0] == ["AC-02"]
    assert _ids(linked, "121222")[1] == "negative"
    assert _ids(linked, "121224")[0] == ["AC-03"]
    assert _ids(linked, "121228")[0] == ["AC-04"]


def test_disabled_login_button_is_negative_and_email_retention_is_a_gap():
    record = {
        "id": "121213",
        "title": "SNAP Login Screen",
        "acceptance_criteria": [
            {
                "ac_id": "AC-10",
                "text": (
                    "Login button state. The Login button stays disabled while either field "
                    "is empty, and it becomes available only when both fields contain input."
                ),
            },
            {
                "ac_id": "AC-11",
                "text": (
                    "Login page retention. The user stays on the login page and "
                    "the entered email remains in the email field."
                ),
            },
        ],
        "scenarios": [],
        "tests": _tests(),
        "bugs": [],
    }
    record["tests"] = apply_behavior_links(record["acceptance_criteria"], record["tests"])
    score = score_health(record)
    rows = {row["ac_id"]: row for row in score["scenarios"]}

    assert rows["AC-10"]["mapped_test_ids"] == ["121226", "121227"]
    assert "Negative scenarios are covered" in rows["AC-10"]["depth"]
    assert "No Negative scenarios Covered" not in rows["AC-10"]["gap"]
    assert rows["AC-11"]["mapped_test_ids"] == ["121220", "121221"]
    assert "entered email remains" in rows["AC-11"]["gap"]
    assert rows["AC-11"]["row_status"] == "partial"


def test_coverage_percent_uses_depth_buckets_and_the_table_uses_status():
    record = {
        "id": "123086",
        "title": "SNAP Login Screen - Admin",
        "acceptance_criteria": [
            {"ac_id": "AC-01", "text": "Successful login. Authenticated and redirected."},
            {"ac_id": "AC-02", "text": "A criterion with no matching test."},
        ],
        "scenarios": [],
        "tests": _tests(),
        "bugs": [
            {
                "id": "122595",
                "title": "Dashboard screen has UI issue",
                "priority": "P3",
                "status": "Rejected / Unable to Reproduce",
            }
        ],
    }
    record["tests"] = apply_behavior_links(record["acceptance_criteria"], record["tests"])
    score = score_health(record)
    facts = _facts(score, record)
    depth, gap, status = _depth_and_gap(score["scenarios"][0])

    assert score["open_bug_count"] == 0
    assert facts["unable"] == 1
    assert facts["open_bugs_by_priority"]["P3"] == 0
    assert score["scenarios"][0]["row_status"] == "partial"
    assert status == "partial"
    assert gap != "No coverage"
    assert "Positive" in depth
    assert facts["coverage_label"] == "33%"
    assert facts["adequate_count"] == 0
    assert facts["partial_count"] == 1
    assert facts["none_count"] == 1
