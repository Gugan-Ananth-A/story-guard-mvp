"""The repo .env fills variables the shell did not set."""

import os

from story_guard.envfile import load_env_file


def test_load_env_file_sets_missing_values_and_keeps_the_shell(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "export NEW_FROM_FILE=from-file",
                "ALREADY_SET=from-file",
                "QUOTED=\"spaced value\"",
                "EMPTY=",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("NEW_FROM_FILE", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.delenv("EMPTY", raising=False)
    monkeypatch.setenv("ALREADY_SET", "from-shell")

    load_env_file(env_file)

    assert os.environ["NEW_FROM_FILE"] == "from-file"
    assert os.environ["QUOTED"] == "spaced value"
    assert os.environ["ALREADY_SET"] == "from-shell"
    assert "EMPTY" not in os.environ


def test_missing_env_file_is_ignored(tmp_path):
    load_env_file(tmp_path / "absent.env")
