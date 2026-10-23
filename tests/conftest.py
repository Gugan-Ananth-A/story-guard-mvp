"""Keep pytest green while the suite has no feature tests yet."""

import os

import pytest

from story_guard.envfile import FILE_OWNS


@pytest.fixture(autouse=True)
def _restore_model_selector_env():
    """A CLI test may apply the project .env. Put the process back afterwards."""
    saved = {key: os.environ.get(key) for key in FILE_OWNS}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Pytest uses exit code 5 when collection finds nothing. Later slices add tests here.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
