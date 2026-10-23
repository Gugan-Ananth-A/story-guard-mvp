"""The repo .env fills variables the shell did not set."""

import os

from story_guard.envfile import FILE_OWNS, load_env_file


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


def test_file_owns_replaces_a_stale_shell_provider(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "STORY_GUARD_LLM=deepseek",
                "STORY_GUARD_MODEL=deepseek-v4-pro",
                "DEEPSEEK_MODEL=deepseek-v4-pro",
                "ADO_PAT=from-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STORY_GUARD_LLM", "ollama")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.delenv("STORY_GUARD_MODEL", raising=False)
    monkeypatch.setenv("XAI_MODEL", "grok-4.7")
    monkeypatch.setenv("ADO_PAT", "from-shell")

    replaced = load_env_file(env_file, file_owns=FILE_OWNS)

    assert os.environ["STORY_GUARD_LLM"] == "deepseek"
    assert os.environ["STORY_GUARD_MODEL"] == "deepseek-v4-pro"
    assert os.environ["DEEPSEEK_MODEL"] == "deepseek-v4-pro"
    assert os.environ["ADO_PAT"] == "from-shell"
    assert "XAI_MODEL" not in os.environ
    assert ("STORY_GUARD_LLM", "ollama", "deepseek") in replaced
    assert ("DEEPSEEK_MODEL", "deepseek-chat", "deepseek-v4-pro") in replaced
