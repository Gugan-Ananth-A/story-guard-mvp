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


def test_show_and_forgot_cases_fill_positive_negative_and_adhoc():
    """Cases added beside the known ids still count when the title or the steps name the behavior."""
    record = {
        "id": "123086",
        "title": "SNAP Login Screen - Admin",
        "acceptance_criteria": [
            {
                "ac_id": "AC-01",
                "text": (
                    "Successful login. Given a registered account, when the user enters "
                    "the email and the correct password and clicks Login, the user is "
                    "authenticated and redirected to the SNAP dashboard/home page."
                ),
            },
            {
                "ac_id": "AC-02",
                "text": (
                    "Invalid credentials. When the user submits an unregistered email, "
                    "or a registered email with the wrong password, an error says the "
                    "credentials are invalid, and the user stays on the login page."
                ),
            },
            {
                "ac_id": "AC-03",
                "text": (
                    "Password visibility — Show. When the user has entered a password "
                    "and clicks Show, the password is displayed as plain text."
                ),
            },
            {
                "ac_id": "AC-04",
                "text": (
                    "Forgot Password navigation. When the user clicks Forgot Password?, "
                    "the user is redirected to the password recovery page."
                ),
            },
        ],
        "scenarios": [],
        "tests": [
            {"id": "121216", "title": "Verify successful login with valid registered email and correct password", "type": "", "mapped_ac_ids": []},
            {"id": "121217", "title": "Verify validation error when email field is left empty", "type": "", "mapped_ac_ids": []},
            {"id": "121221", "title": "Verify error message for unregistered email", "type": "", "mapped_ac_ids": []},
            {"id": "121222", "title": "Verify error message and field reset for incorrect password", "type": "", "mapped_ac_ids": []},
            {"id": "121224", "title": "Verify 'Show' toggle reveals the entered password", "type": "", "mapped_ac_ids": []},
            {"id": "121228", "title": "Verify navigation to the Forgot Password flow", "type": "", "mapped_ac_ids": []},
            {"id": "121229", "title": "Verify leading/trailing spaces in the email field are handled correctly", "type": "", "mapped_ac_ids": []},
            {"id": "123364", "title": "Verify whether if the password field is left empty then on click on show password button the field should be empty.", "type": "", "mapped_ac_ids": []},
            {"id": "123378", "title": "Verify click Show button with an invalid password", "type": "", "mapped_ac_ids": []},
            {"id": "123379", "title": "Verify Show password with leading/trailing spaces", "type": "", "mapped_ac_ids": []},
            {"id": "123390", "title": "Verify click Forgot Password with empty credentials", "type": "", "mapped_ac_ids": []},
            {"id": "123395", "title": "Verify repeated clicks on Forgot Password", "type": "", "mapped_ac_ids": []},
            {"id": "123396", "title": "Verify navigate using keyboard", "type": "", "mapped_ac_ids": [], "steps": "Use Tab to focus Forgot Password?. The password recovery page opens successfully."},
            {"id": "123401", "title": "Verify recovery page destination", "type": "", "mapped_ac_ids": []},
            {"id": "123402", "title": "Verify navigation with Show enabled", "type": "", "mapped_ac_ids": [], "steps": "Enter a password. Click Show. Click Forgot Password?. The recovery page opens successfully."},
        ],
        "bugs": [],
    }
    record["tests"] = apply_behavior_links(record["acceptance_criteria"], record["tests"])
    score = score_health(record)
    rows = {row["ac_id"]: row for row in score["scenarios"]}
    by_id = {test["id"]: test for test in record["tests"]}

    assert rows["AC-03"]["row_status"] == "adequate"
    assert rows["AC-03"]["gap"] == "Adequate"
    assert "Positive scenarios are covered" in rows["AC-03"]["depth"]
    assert "Negative scenarios are covered" in rows["AC-03"]["depth"]
    assert "Adhoc scenarios are covered" in rows["AC-03"]["depth"]
    assert by_id["123364"]["type"] == "negative"
    assert by_id["123378"]["mapped_ac_ids"] == ["AC-03"]
    assert by_id["123379"]["type"] == "adhoc"
    assert "123378" not in rows["AC-02"]["mapped_test_ids"]

    assert rows["AC-04"]["row_status"] == "adequate"
    assert by_id["123390"]["type"] == "negative"
    assert by_id["123395"]["type"] == "adhoc"
    assert by_id["123396"]["type"] == "adhoc"
    assert by_id["123396"]["mapped_ac_ids"] == ["AC-04"]
    assert by_id["123401"]["type"] == "happy"
    assert by_id["123402"]["type"] == "adhoc"
    assert by_id["123402"]["mapped_ac_ids"] == ["AC-03", "AC-04"]

    assert rows["AC-01"]["row_status"] == "partial"
    assert "121216" in rows["AC-01"]["mapped_test_ids"]
    assert "123378" not in rows["AC-01"]["mapped_test_ids"]
    assert by_id["121217"]["mapped_ac_ids"] == []
    assert by_id["121217"]["type"] == ""
    assert rows["AC-02"]["mapped_test_ids"] == ["121221", "121222"]
