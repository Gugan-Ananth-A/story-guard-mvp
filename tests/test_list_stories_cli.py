import json

import pytest

from story_guard.ado_client import ADOClient
from story_guard.cli import main


def test_list_stories_command_prints_one_json_array(monkeypatch, capsys):
    stories = [
        {"id": "121216", "title": "Login succeeds"},
        {"id": "121217", "title": "Empty email is rejected"},
    ]
    class FakeADOClient:
        def list_user_stories(self, _iteration_path):
            return stories

    client = FakeADOClient()
    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda _cls: client))

    result = main(
        [
            "list-stories",
            "--iteration-path",
            "Story Guard\\Sprint 1",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == stories


def test_fetch_stories_command_outputs_each_result_and_returns_nonzero_for_errors(
    monkeypatch, capsys
):
    results = [
        {"id": "121213", "story": {"title": "Login"}, "bugs": [], "test_cases": []},
        {"id": "not-found", "error": {"code": "not_found", "message": "missing"}},
        {"id": "121214", "story": {"title": "Checkout"}, "bugs": [], "test_cases": []},
    ]
    received_ids = []

    class FakeADOClient:
        def fetch_many_stories(self, story_ids):
            received_ids.extend(story_ids)
            return results

    client = FakeADOClient()
    monkeypatch.setattr(ADOClient, "from_env", classmethod(lambda _cls: client))

    result = main(["fetch-stories", "--story-ids", "121213", "404", "121214"])

    assert result == 1
    assert received_ids == [121213, 404, 121214]
    assert json.loads(capsys.readouterr().out) == results


def test_fetch_story_and_bug_writes_no_fixtures_or_artifacts(
    tmp_path, monkeypatch, capsys
):
    from io import BytesIO
    from pathlib import Path

    project_url = "https://dev.azure.com/storyguard/sample"
    payloads = {
        100: {
            "id": 100,
            "fields": {
                "System.WorkItemType": "User Story",
                "System.Title": "Login story",
                "System.State": "New",
                "System.Description": "",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Related",
                    "url": f"{project_url}/_apis/wit/workitems/999",
                }
            ],
        },
        999: {
            "id": 999,
            "fields": {
                "System.WorkItemType": "Bug",
                "System.Title": "Login defect",
                "System.State": "Active",
            },
        },
    }
    requests = []

    def opener(request, timeout):
        requests.append(request)
        work_item_id = int(request.full_url.rsplit("/", 1)[-1].split("?", 1)[0])
        return BytesIO(json.dumps(payloads[work_item_id]).encode("utf-8"))

    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    fixture_snapshot = {
        path.relative_to(fixture_dir): path.read_bytes()
        for path in fixture_dir.rglob("*")
        if path.is_file()
    }
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("ADO_PROJECT_URL", project_url)
    monkeypatch.setenv("ADO_PAT", "offline-test-pat")
    monkeypatch.setenv("STORY_GUARD_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr("story_guard.ado_client.urlopen", opener)

    result = main(["fetch-stories", "--story-ids", "100", "999"])

    captured = capsys.readouterr()
    records = json.loads(captured.out)
    assert result == 1
    assert records[0]["story"]["id"] == "100"
    assert records[1]["id"] == "999"
    assert records[1]["error"]["code"] == "not_user_story"
    assert all(request.get_method() == "GET" for request in requests)
    assert {
        path.relative_to(fixture_dir): path.read_bytes()
        for path in fixture_dir.rglob("*")
        if path.is_file()
    } == fixture_snapshot
    assert not artifacts_dir.exists() or list(artifacts_dir.iterdir()) == []
    assert not (artifacts_dir / "999.pdf").exists()


def test_sprints_command_prints_iteration_paths(monkeypatch, capsys):
    paths = ["Commerce\\Release 1\\Sprint 1", "Commerce\\Release 1\\Sprint 2"]

    class FakeADOClient:
        def list_iterations(self):
            return paths

    monkeypatch.setattr(
        ADOClient,
        "from_env",
        classmethod(lambda _cls: FakeADOClient()),
    )

    result = main(["sprints"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.splitlines() == paths
    assert captured.err == ""


def test_sprints_command_handles_project_access_denial_without_artifacts(
    tmp_path, monkeypatch, capsys
):
    from io import BytesIO
    from urllib.error import HTTPError

    project_url = "https://dev.azure.com/customer-org/Commerce"
    artifacts_dir = tmp_path / "artifacts"

    def opener(request, timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", {}, BytesIO())

    monkeypatch.setenv("ADO_PROJECT_URL", project_url)
    monkeypatch.setenv("ADO_PAT", "offline-test-pat")
    monkeypatch.setenv("STORY_GUARD_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr("story_guard.ado_client.urlopen", opener)

    result = main(["sprints"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "configuration error" in captured.err
    assert "ADO_PAT cannot read" in captured.err
    assert not artifacts_dir.exists()


def test_list_stories_command_reports_missing_ado_configuration(monkeypatch, capsys):
    monkeypatch.delenv("ADO_PROJECT_URL", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)

    result = main(["list-stories", "--iteration-path", "Project\\Sprint 1"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "ADO_PROJECT_URL, ADO_PAT" in captured.err


def test_generate_sprint_runs_each_story_with_its_own_plan(
    tmp_path, monkeypatch, capsys
):
    from story_guard.graph import load_live_story

    monkeypatch.delenv("ADO_PAT", raising=False)

    def story_bundle(story_id, test_cases):
        return {
            "id": str(story_id),
            "story": {
                "id": str(story_id),
                "title": f"Story {story_id}",
                "type": "User Story",
                "state": "New",
                "description": "Scenario: Works\nExpected: It works",
                "area": "Commerce",
                "iteration": "Commerce\\Release 1\\Sprint 1",
                "raw_ac_text": "",
                "acceptance_criteria": [],
            },
            "bugs": [],
            "test_cases": test_cases,
        }

    cases = {
        "501": {
            "id": "501",
            "title": "First plan case",
            "type": "happy",
            "mapped_ac_ids": [],
            "last_result": "",
            "last_result_at": None,
            "linked_bug_ids": [],
        },
        "502": {
            "id": "502",
            "title": "Second plan case",
            "type": "negative",
            "mapped_ac_ids": [],
            "last_result": "",
            "last_result_at": None,
            "linked_bug_ids": [],
        },
    }
    bundles = {
        "100": story_bundle(100, [cases["501"]]),
        "200": story_bundle(200, [cases["502"]]),
        "300": story_bundle(300, []),
    }
    requests = []

    class FakeADOClient:
        def list_user_stories(self, iteration_path):
            assert iteration_path == "Commerce\\Release 1\\Sprint 1"
            return [{"id": story_id} for story_id in bundles]

        def fetch_many_stories(self, story_ids):
            assert len(story_ids) == 1
            story_id = str(story_ids[0])
            requests.append(story_id)
            return [bundles[story_id]]

        def test_case_plan_memberships(self, test_case_ids):
            assert test_case_ids == [501, 502]
            return {"501": [121214], "502": [765432]}

    generated = []

    def fake_run_generate(state):
        generated.append(state)
        story_id = state["story_id"]
        return {
            "story_id": story_id,
            "token_count": 10,
            "narrative_latency_ms": 2,
            "markdown_path": str(tmp_path / f"{story_id}.md"),
        }

    monkeypatch.setattr(
        ADOClient,
        "from_env",
        classmethod(lambda _cls: FakeADOClient()),
    )
    monkeypatch.setattr("story_guard.cli.run_generate", fake_run_generate)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)
    monkeypatch.setattr("story_guard.graph.load_live_story", load_live_story)

    result = main(["generate", "--sprint", "Commerce\\Release 1\\Sprint 1"])

    captured = capsys.readouterr()
    assert result == 0
    assert requests == ["100", "200", "300"]
    assert [state["story_id"] for state in generated] == ["100", "200", "300"]
    records = [state["live_record"] for state in generated]
    assert [record["tests"][0]["id"] for record in records[:2]] == ["501", "502"]
    assert records[0]["note"] == "Linked Test Plan IDs: 121214"
    assert records[1]["note"] == "Linked Test Plan IDs: 765432"
    assert records[2]["tests"] == []
    assert "No explicitly linked Test Plan" in records[2]["note"]
    assert captured.out.splitlines() == [
        str(tmp_path / "100.md"),
        str(tmp_path / "200.md"),
        str(tmp_path / "300.md"),
    ]
    assert captured.err == ""


def test_generate_sprint_continues_after_story_failure(monkeypatch, capsys):
    from story_guard.ado_client import ADORequestError

    class FakeADOClient:
        def list_user_stories(self, _iteration_path):
            return [{"id": "100"}, {"id": "200"}]

        def fetch_many_stories(self, story_ids):
            if story_ids == [100]:
                raise ADORequestError("temporary ADO failure")
            return [
                {
                    "id": "200",
                    "story": {
                        "id": "200",
                        "title": "Second story",
                        "type": "User Story",
                        "state": "New",
                        "description": "",
                        "area": "Commerce",
                        "iteration": "Commerce\\Sprint",
                        "raw_ac_text": "",
                        "acceptance_criteria": [],
                    },
                    "bugs": [],
                    "test_cases": [],
                }
            ]

        def test_case_plan_memberships(self, test_case_ids):
            assert test_case_ids == []
            return {}

    generated_ids = []

    def fake_run_generate(state):
        generated_ids.append(state["story_id"])
        return {
            "story_id": state["story_id"],
            "token_count": 5,
            "narrative_latency_ms": 1,
            "markdown_path": "reports/200.md",
        }

    monkeypatch.setattr(
        ADOClient,
        "from_env",
        classmethod(lambda _cls: FakeADOClient()),
    )
    monkeypatch.setattr("story_guard.cli.run_generate", fake_run_generate)
    monkeypatch.setattr("story_guard.cli.record_success", lambda *_args: None)

    result = main(["generate", "--sprint", "Commerce\\Sprint"])

    captured = capsys.readouterr()
    assert result == 1
    assert generated_ids == ["200"]
    assert captured.out.splitlines() == ["reports/200.md"]
    assert "Story 100: temporary ADO failure" in captured.err


def test_generate_rejects_sprint_and_story_id_together(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["generate", "--story-id", "121213", "--sprint", "Commerce\\Sprint"])

    assert raised.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
