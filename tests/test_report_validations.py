"""Coverage and validation behavior for incomplete story inputs."""

import re
from pathlib import Path

from story_guard import cli, graph
from story_guard.ado_client import ADOClient
from story_guard.render import render_markdown
from story_guard.score import score_health
from story_guard.security import review_and_redact

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "health_report.md"


def _record(**overrides):
    record = {
        "id": "424242",
        "title": "Checkout validation",
        "type": "User Story",
        "state": "New",
        "description": "As a buyer, I want checkout validation.",
        "area": "Commerce",
        "iteration": "Commerce\\Sprint 1",
        "acceptance_criteria_raw": "",
        "acceptance_criteria": [],
        "scenarios": [
            {
                "ac_id": "AC-1",
                "text": "Reject invalid postal codes.",
                "testable": True,
                "flags": [],
            }
        ],
        "tests": [],
        "bugs": [],
        "note": "",
        "source": "test fixture",
    }
    record.update(overrides)
    return record


def test_empty_story_with_tests_has_zero_coverage_and_no_data_validation():
    record = _record(
        title="",
        description="",
        acceptance_criteria_raw="",
        acceptance_criteria=[],
        scenarios=[],
        tests=[{"id": "TC-1", "title": "Checkout smoke", "type": "happy", "mapped_ac_ids": []}],
    )

    score = score_health(record)

    assert score["average_testcase_coverage"] == 0
    assert score["scenarios"] == []
    assert score["validation_messages"] == [
        "Userstory ID - “424242” has no data."
    ]


def test_story_without_testcases_has_zero_coverage_and_blank_depth_and_gap():
    score = score_health(_record())

    assert score["average_testcase_coverage"] == 0
    assert score["validation_messages"] == [
        "Userstory ID - “424242” has no Testcases."
    ]
    assert score["scenarios"][0]["depth"] == ""
    assert score["scenarios"][0]["gap"] == ""


def test_unmapped_criterion_with_a_test_suite_has_requested_gap_labels():
    record = _record(
        tests=[{"id": "TC-1", "title": "Checkout smoke", "type": "happy", "mapped_ac_ids": []}]
    )

    score = score_health(record)

    assert score["average_testcase_coverage"] == 0
    assert score["scenarios"][0]["depth"] == "No Testcases Found"
    assert score["scenarios"][0]["gap"] == "No Testcases Found"


def test_average_coverage_counts_only_criteria_with_explicit_mappings():
    record = _record(
        scenarios=[
            {"ac_id": "AC-1", "text": "A", "testable": True, "flags": []},
            {"ac_id": "AC-2", "text": "B", "testable": True, "flags": []},
        ],
        tests=[
            {"id": "TC-1", "title": "Case 1", "type": "happy", "mapped_ac_ids": ["AC-1"]},
            {"id": "TC-2", "title": "Case 2", "type": "happy", "mapped_ac_ids": []},
        ],
    )

    score = score_health(record)

    assert score["average_testcase_coverage"] == 50


def test_not_found_report_keeps_headings_and_blanks_section_values(tmp_path):
    record = {
        **_record(
            title="",
            description="",
            scenarios=[],
            tests=[],
        ),
        "not_found": True,
    }
    score = score_health(record)
    output = tmp_path / "missing.md"

    render_markdown(score, {}, TEMPLATE, output, record=record)

    report = output.read_text(encoding="utf-8")
    headings = re.findall(r"^## .+$", report, flags=re.MULTILINE)
    assert len(headings) == 8
    assert "Userstory ID - “424242” Does not exist." in report
    for heading in headings[1:]:
        section_text = report.split(heading, 1)[1].split("\n## ", 1)[0]
        assert all(
            not line.strip() or line.rstrip().endswith(":")
            for line in section_text.splitlines()
        )


def test_security_review_redacts_credential_like_values_recursively():
    record = _record(
        description="Use api_key=sample-secret-credential for the service.",
        tests=[{"id": "TC-1", "title": "Bearer abcdefghijklmnopqrstuvwxyz123456"}],
    )

    sanitized, findings = review_and_redact(record)

    assert "sample-secret-credential" not in str(sanitized)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in str(sanitized)
    assert "[REDACTED]" in str(sanitized)
    assert "redacted" in findings[0].lower()
    assert "sample-secret-credential" in record["description"]


def test_sprint_generation_skips_duplicate_id_and_warns_in_kept_report(monkeypatch, capsys):
    generated = []
    client = type(
        "FakeADOClient",
        (),
        {
            "list_user_stories": lambda self, _path: [
                {"id": 12},
                {"id": 12},
                {"id": 13},
            ],
            "fetch_many_stories": lambda self, ids: [
                {"id": str(ids[0]), "story": {}, "test_cases": [], "bugs": []}
            ],
            "test_case_plan_memberships": lambda self, _ids: {},
        },
    )()
    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda _cls: client))
    monkeypatch.setattr(
        graph,
        "load_live_story",
        lambda story_id, **_kwargs: {
            "id": story_id,
            "validation_messages": [],
        },
    )

    def fake_generate(state):
        generated.append(state)
        return {
            "story_id": state["story_id"],
            "token_count": 0,
            "narrative_latency_ms": 0,
            "markdown_path": f"{state['story_id']}.md",
        }

    monkeypatch.setattr(cli, "run_generate", fake_generate)
    monkeypatch.setattr(cli, "record_success", lambda *_args: None)

    assert cli._generate_sprint("Commerce\\Sprint 1") == 0

    assert [state["story_id"] for state in generated] == ["12", "13"]
    assert generated[0]["live_record"]["validation_messages"] == [
        "Duplicate Userstory ID - “12” found"
    ]
    capsys.readouterr()


def test_cli_generates_nonexistent_story_report_without_calling_model(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    def fail_narrative(_score):
        raise AssertionError("narrative should not run for a missing story")

    monkeypatch.setattr("story_guard.graph.request_narrative", fail_narrative)

    assert cli.main(["generate", "--story-id", "424242"]) == 0

    markdown = (tmp_path / "424242.md").read_text(encoding="utf-8")
    assert (tmp_path / "424242.pdf").is_file()
    assert "Userstory ID - “424242” Does not exist." in markdown
    assert len(re.findall(r"^## .+$", markdown, flags=re.MULTILINE)) == 8
    assert "Avg testcase coverage" not in markdown
    capsys.readouterr()


def test_fetch_redacts_sensitive_text_before_score_and_report(tmp_path):
    from story_guard.narrative import _build_payload

    secret = "api_key=sample-secret-credential"
    record = _record(
        description=f"Use {secret} only in local tests.",
        tests=[
            {
                "id": "TC-1",
                "title": "Bearer abcdefghijklmnopqrstuvwxyz123456",
                "type": "happy",
                "mapped_ac_ids": [],
            }
        ],
    )

    sanitized = graph.fetch(
        {"story_id": "424242", "live": True, "live_record": record}
    )["record"]
    score = score_health(sanitized)
    payload, _payload_score = _build_payload(score)
    output = tmp_path / "secured.md"
    render_markdown(score, {}, TEMPLATE, output, record=sanitized)

    assert "sample-secret-credential" not in str(payload)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in str(payload)
    assert "sample-secret-credential" not in output.read_text(encoding="utf-8")
    assert "Security review: Credential-like content was detected" in output.read_text(
        encoding="utf-8"
    )
    assert secret in record["description"]


def test_missing_criteria_report_shows_zero_coverage_and_empty_mapping_table(tmp_path):
    record = _record(
        title="",
        description="",
        scenarios=[],
        tests=[{"id": "TC-1", "title": "Checkout smoke", "type": "happy", "mapped_ac_ids": []}],
    )
    score = score_health(record)
    output = tmp_path / "empty-story.md"

    render_markdown(score, {}, TEMPLATE, output, record=record)

    report = output.read_text(encoding="utf-8")
    assert "Avg testcase coverage: 0%" in report
    assert "Userstory ID - “424242” has no data." in report
    assert "| AC ID | Acceptance Criteria | Linked Test IDs | Coverage depth | Coverage gap |" in report
    assert "| --- | --- | --- | --- | --- |" in report


def test_no_testcase_report_keeps_coverage_cells_blank(tmp_path):
    record = _record(tests=[])
    score = score_health(record)
    output = tmp_path / "no-tests.md"

    render_markdown(score, {}, TEMPLATE, output, record=record)

    report = output.read_text(encoding="utf-8")
    assert "Avg testcase coverage: 0%" in report
    assert "Userstory ID - “424242” has no Testcases." in report
    assert "| AC-1 | Reject invalid postal codes. |  |  |  |" in report


def test_ado_not_found_is_a_reportable_result_but_other_errors_fail_closed():
    from story_guard.ado_client import ADOResponseError

    missing = graph.load_live_story(
        "424242",
        client=object(),
        story_bundle={
            "id": "424242",
            "error": {"code": "not_found", "message": "Work item missing"},
        },
        plan_memberships={},
    )
    assert missing["not_found"] is True
    assert missing["id"] == "424242"

    raised = False
    try:
        graph.load_live_story(
            "424242",
            client=object(),
            story_bundle={
                "id": "424242",
                "error": {"code": "forbidden", "message": "Access denied"},
            },
            plan_memberships={},
        )
    except ADOResponseError:
        raised = True
    assert raised


def test_sprint_duplicate_warning_appears_in_the_generated_report(
    tmp_path, monkeypatch, capsys
):
    client = type(
        "FakeADOClient",
        (),
        {
            "list_user_stories": lambda self, _path: [
                {"id": 12},
                {"id": 12},
            ],
            "fetch_many_stories": lambda self, ids: [
                {"id": str(ids[0]), "story": {}, "test_cases": [], "bugs": []}
            ],
            "test_case_plan_memberships": lambda self, _ids: {},
        },
    )()
    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda _cls: client))
    monkeypatch.setattr("story_guard.graph.artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)
    monkeypatch.setattr(graph, "load_live_story", lambda story_id, **_kwargs: _record(id=story_id))
    monkeypatch.setattr(
        graph,
        "request_narrative",
        lambda score: {
            "score": score,
            "narrative": {
                "headline": "Report ready.",
                "sections": [],
                "actions": [
                    {"owner": "QA", "text": "Review the test mapping."},
                    {"owner": "Dev", "text": "Review the story data."},
                    {"owner": "PO", "text": "Confirm the acceptance criteria."},
                ],
            },
            "token_count": 0,
            "narrative_latency_ms": 0,
        },
    )

    assert cli._generate_sprint("Commerce\\Sprint 1") == 0

    report = (tmp_path / "12.md").read_text(encoding="utf-8")
    assert "Duplicate Userstory ID - “12” found" in report
    capsys.readouterr()
