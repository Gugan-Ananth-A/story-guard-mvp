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


def test_list_stories_command_reports_missing_ado_configuration(monkeypatch, capsys):
    monkeypatch.delenv("ADO_PROJECT_URL", raising=False)
    monkeypatch.delenv("ADO_PAT", raising=False)

    result = main(["list-stories", "--iteration-path", "Project\\Sprint 1"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "ADO_PROJECT_URL, ADO_PAT" in captured.err
