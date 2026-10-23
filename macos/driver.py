"""Thin bridge from the Story Guard Mac app to the existing CLI.

The driver does not score stories. It calls ``story_guard.cli.main`` and turns
the CLI's stderr into JSON events on stdout.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from typing import Callable, TextIO

# Story percent is how many acceptance criteria have been reviewed.
# "live review started: N acceptance criteria" sets the total.
# Each "completed AC-…:" line counts one criterion, once.
# The first fraction on a "reviewing" line is a suite batch inside the
# current criterion, so it does not move the percent.
# "reports written" finishes the story at 100.
# Overall percent: ((story_index - 1) * 100 + story_percent) // story_count
_REVIEW_STARTED = re.compile(r"live review started:\s*(\d+)\s+acceptance criteria")
_AC_COMPLETED = re.compile(r"\bcompleted\s+(\S+):")
_STARTING = re.compile(r"starting (?:live )?generation for story (\S+)")
_REPORTS = re.compile(r"reports written to (.+\.md) and (.+\.pdf)\s*$")
_STORY_ID = re.compile(r"^[1-9][0-9]*$")
_WARNINGS = (
    "could not unload",
    "batch trace was not written",
    "langsmith trace was not sent",
    "sprint PDF failed",
)


def ac_coverage_percent(completed: int, total: int) -> int:
    """Whole-number share of acceptance criteria that have been reviewed."""
    if total <= 0 or completed <= 0:
        return 0
    if completed >= total:
        return 100
    return (completed * 100) // total


def overall_percent(story_index: int, story_count: int, story_percent: int) -> int:
    """Whole-number percent for a batch. Index is 1-based."""
    if story_index < 1 or story_count <= 0:
        return 0
    return ((story_index - 1) * 100 + story_percent) // story_count


class ProgressTracker:
    """Fold CLI stderr lines into driver events."""

    def __init__(self, story_ids: list[str]) -> None:
        self.story_ids = list(story_ids)
        self.index_by_id = {story_id: index for index, story_id in enumerate(self.story_ids, 1)}
        self.current_id: str | None = None
        self.current_index = 0
        self.story_percent = 0
        self.ac_total = 0
        self.ac_completed: list[str] = []
        self.finished: set[str] = set()

    @property
    def story_count(self) -> int:
        return len(self.story_ids)

    def feed(self, line: str) -> list[dict]:
        text = line.strip()
        if not text:
            return []
        message = text[len("[story-guard] ") :] if text.startswith("[story-guard] ") else text
        started = _STARTING.search(message)
        if started:
            return self._begin_story(started.group(1), message)
        if self.current_id is None:
            if text.startswith("[story-guard]"):
                return [self._progress(message)]
            return [_error(None, message)]
        written = _REPORTS.search(message)
        if written:
            self.story_percent = 100
            story_id = self.current_id
            self.finished.add(story_id)
            pdf = written.group(2).strip()
            stem = os.path.splitext(os.path.basename(pdf))[0]
            if _STORY_ID.match(stem):
                story_id = stem
                self.finished.add(story_id)
            return [
                self._progress(message),
                {
                    "event": "report",
                    "story_id": story_id,
                    "pdf": pdf,
                    "markdown": written.group(1).strip(),
                },
            ]
        if text.startswith("[story-guard]") or _is_warning(message):
            self._apply_coverage(message)
            return [self._progress(message)]
        return [_error(self.current_id, message)]

    def done_event(self) -> dict:
        written = [story_id for story_id in self.story_ids if story_id in self.finished]
        failed = [story_id for story_id in self.story_ids if story_id not in self.finished]
        return {"event": "done", "written": written, "failed": failed}

    def _begin_story(self, story_id: str, message: str) -> list[dict]:
        if story_id not in self.index_by_id:
            self.story_ids.append(story_id)
            self.index_by_id[story_id] = len(self.story_ids)
        self.current_id = story_id
        self.current_index = self.index_by_id[story_id]
        if story_id not in self.finished:
            self.story_percent = 0
            self.ac_total = 0
            self.ac_completed = []
        return [self._progress(message)]

    def _apply_coverage(self, message: str) -> None:
        started = _REVIEW_STARTED.search(message)
        if started:
            self.ac_total = int(started.group(1))
            self.ac_completed = []
            self.story_percent = ac_coverage_percent(0, self.ac_total)
            return
        if "live review complete" in message:
            if self.ac_total <= 0:
                self.story_percent = 100
            else:
                self.story_percent = ac_coverage_percent(len(self.ac_completed), self.ac_total)
            return
        completed = _AC_COMPLETED.search(message)
        if completed:
            ac_id = completed.group(1)
            if ac_id not in self.ac_completed:
                self.ac_completed.append(ac_id)
            self.story_percent = ac_coverage_percent(len(self.ac_completed), self.ac_total)
            return
        if "reports written" in message:
            self.story_percent = 100

    def _progress(self, message: str) -> dict:
        return {
            "event": "progress",
            "story_index": self.current_index,
            "story_count": self.story_count,
            "message": message,
            "percent": overall_percent(self.current_index, self.story_count, self.story_percent),
            "ac_completed": len(self.ac_completed),
            "ac_total": self.ac_total,
        }


def _error(story_id: str | None, message: str) -> dict:
    event = {"event": "error", "message": message}
    if story_id:
        event["story_id"] = story_id
    return event


def _is_warning(message: str) -> bool:
    return any(message.startswith(prefix) for prefix in _WARNINGS)


def _emit(event: dict, stdout: TextIO) -> None:
    print(json.dumps(event, ensure_ascii=False), file=stdout, flush=True)


def _lead_process_group() -> None:
    """Become a process-group leader so the app can cancel this driver."""
    if os.environ.get("STORY_GUARD_APP") != "1":
        return
    try:
        os.setpgrp()
    except OSError:
        return


def _positive_ids(raw_ids: list[str]) -> list[str] | None:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        story_id = raw.strip()
        if not _STORY_ID.match(story_id):
            return None
        if story_id in seen:
            continue
        seen.add(story_id)
        ordered.append(story_id)
    return ordered


class _LineSink(io.TextIOBase):
    def __init__(self, on_line: Callable[[str], None]) -> None:
        self._pending = ""
        self._on_line = on_line

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = str(text)
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._on_line(line)
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self._on_line(self._pending)
            self._pending = ""

    @property
    def encoding(self) -> str:
        return "utf-8"


def _call_cli(argv: list[str], on_stderr: Callable[[str], None] | None = None) -> tuple[str, str, int]:
    from story_guard.cli import main

    stdout_buffer = io.StringIO()
    stderr_lines: list[str] = []

    def collect(line: str) -> None:
        stderr_lines.append(line)
        if on_stderr is not None:
            on_stderr(line)

    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = stdout_buffer
    sink = _LineSink(collect)
    sys.stderr = sink
    try:
        try:
            code = main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sink.flush()
        sys.stdout = saved_out
        sys.stderr = saved_err
    return stdout_buffer.getvalue(), "\n".join(stderr_lines), int(code)


def _sprints(stdout: TextIO) -> int:
    out, err, code = _call_cli(["sprints"])
    if code != 0:
        message = err.strip() or "Could not read iteration paths."
        print(message, file=sys.stderr)
        _emit({"event": "error", "message": message}, stdout)
        return code
    paths = [line for line in out.splitlines() if line.strip()]
    print(json.dumps(paths, ensure_ascii=False), file=stdout, flush=True)
    return 0


def _ids_for_sprint(path: str, stdout: TextIO) -> tuple[list[str] | None, int]:
    out, err, code = _call_cli(["list-stories", "--iteration-path", path])
    if code != 0:
        message = err.strip() or "Could not list stories for that sprint."
        _emit({"event": "error", "message": message}, stdout)
        return None, code
    try:
        stories = json.loads(out)
    except json.JSONDecodeError:
        _emit({"event": "error", "message": "Sprint story list was not JSON."}, stdout)
        return None, 1
    ids: list[str] = []
    seen: set[str] = set()
    if isinstance(stories, list):
        for story in stories:
            if not isinstance(story, dict):
                continue
            story_id = story.get("id")
            if not isinstance(story_id, str):
                continue
            story_id = story_id.strip()
            if not _STORY_ID.match(story_id) or story_id in seen:
                continue
            seen.add(story_id)
            ids.append(story_id)
    if not ids:
        _emit({"event": "error", "message": f"sprint {path} has no user stories"}, stdout)
        return None, 1
    return ids, 0


def _generate(story_ids: list[str], sprint: str, stdout: TextIO) -> int:
    argv = ["generate", "--live"]
    known_ids = story_ids
    if sprint:
        known_ids, code = _ids_for_sprint(sprint, stdout)
        if known_ids is None:
            _emit({"event": "done", "written": [], "failed": []}, stdout)
            return code
        argv.extend(["--sprint", sprint])
    else:
        for story_id in story_ids:
            argv.extend(["--story-id", story_id])
    tracker = ProgressTracker(known_ids)

    def on_stderr(line: str) -> None:
        for event in tracker.feed(line):
            _emit(event, stdout)

    try:
        _out, _err, code = _call_cli(argv, on_stderr=on_stderr)
    except Exception as exc:
        _emit({"event": "error", "message": str(exc)}, stdout)
        code = 1
    _emit(tracker.done_event(), stdout)
    return code


def main(argv: list[str] | None = None) -> int:
    _lead_process_group()
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="story-guard-driver")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("sprints")
    generate = sub.add_parser("generate")
    generate.add_argument("--story-id", action="append", default=[])
    generate.add_argument("--sprint", default="")
    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    real_stdout = sys.stdout
    if parsed.command == "sprints":
        return _sprints(real_stdout)
    if parsed.command != "generate":
        print("usage: driver.py sprints | generate --story-id ID | generate --sprint PATH", file=sys.stderr)
        return 2
    sprint = parsed.sprint.strip()
    story_ids = parsed.story_id or []
    if sprint and story_ids:
        _emit({"event": "error", "message": "Pass story ids or a sprint, not both."}, real_stdout)
        return 2
    if sprint:
        return _generate([], sprint, real_stdout)
    ids = _positive_ids(story_ids)
    if not ids:
        _emit(
            {"event": "error", "message": "Pass one or more positive story ids, or a sprint."},
            real_stdout,
        )
        return 2
    return _generate(ids, "", real_stdout)


if __name__ == "__main__":
    sys.exit(main())
