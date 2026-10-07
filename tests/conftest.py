"""Keep pytest green while the suite has no feature tests yet."""

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Pytest uses exit code 5 when collection finds nothing. Later slices add tests here.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
