import json

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
