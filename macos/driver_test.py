"""Percent math for the Mac app driver. No Ollama and no Azure DevOps."""

from __future__ import annotations

import json
import unittest

from driver import ProgressTracker, ac_coverage_percent, main, overall_percent


_REVIEW = (
    "[story-guard] reviewing AC-01 against Suite "
    "(3/12, criterion part 1/1, description part 1/1, 4 tests)"
)
_WRITTEN = (
    "[story-guard] reports written to "
    "/Users/gugan/Library/Application Support/Story Guard/artifacts/121213.md and "
    "/Users/gugan/Library/Application Support/Story Guard/artifacts/121213.pdf"
)


class PercentTests(unittest.TestCase):
    def test_coverage_percent_is_completed_criteria_over_total(self) -> None:
        self.assertEqual(ac_coverage_percent(0, 12), 0)
        self.assertEqual(ac_coverage_percent(3, 12), 25)
        self.assertEqual(ac_coverage_percent(2, 8), 25)
        self.assertEqual(ac_coverage_percent(12, 12), 100)
        self.assertEqual(ac_coverage_percent(1, 0), 0)

    def test_before_review_the_story_sits_at_0(self) -> None:
        tracker = ProgressTracker(["121213", "123086"])
        tracker.feed("[story-guard] provider ollama, model qwen3.5:4b")
        events = tracker.feed("[story-guard] starting live generation for story 121213")
        events += tracker.feed("[story-guard] fetching live story 121213 and test suites")
        self.assertEqual(tracker.story_percent, 0)
        self.assertEqual(events[-1]["story_index"], 1)
        self.assertEqual(events[-1]["story_count"], 2)
        self.assertEqual(events[-1]["percent"], overall_percent(1, 2, 0))
        self.assertEqual(events[-1]["percent"], 0)
        self.assertEqual(events[-1]["ac_completed"], 0)
        self.assertEqual(events[-1]["ac_total"], 0)

    def test_percent_follows_completed_acceptance_criteria(self) -> None:
        tracker = ProgressTracker(["121213", "123086"])
        tracker.feed("[story-guard] starting live generation for story 121213")
        started = tracker.feed(
            "[story-guard] live review started: 12 acceptance criteria across 2 suite batches"
        )
        self.assertEqual(tracker.story_percent, 0)
        self.assertEqual(started[-1]["ac_total"], 12)
        # 3/12 here is a suite batch inside one criterion, not criteria completed.
        reviewing = tracker.feed(_REVIEW)
        self.assertEqual(tracker.story_percent, 0)
        self.assertEqual(reviewing[-1]["percent"], 0)
        self.assertIn("reviewing AC-01 against Suite (3/12", reviewing[-1]["message"])
        events = []
        for index in range(1, 4):
            events = tracker.feed(
                f"[story-guard] completed AC-0{index}: 2 predicted test links"
            )
        self.assertEqual(tracker.story_percent, 25)
        self.assertEqual(events[-1]["percent"], overall_percent(1, 2, 25))
        self.assertEqual(events[-1]["percent"], 12)
        self.assertEqual(events[-1]["ac_completed"], 3)
        self.assertEqual(events[-1]["ac_total"], 12)
        again = tracker.feed("[story-guard] completed AC-03: 2 predicted test links")
        self.assertEqual(again[-1]["ac_completed"], 3)
        self.assertEqual(tracker.story_percent, 25)

    def test_rendering_keeps_coverage_and_reports_written_is_100(self) -> None:
        tracker = ProgressTracker(["121213", "123086"])
        tracker.feed("[story-guard] starting live generation for story 121213")
        tracker.feed("[story-guard] live review started: 12 acceptance criteria across 1 suite batches")
        for index in range(1, 4):
            tracker.feed(f"[story-guard] completed AC-0{index}: 1 predicted test links")
        rendering = tracker.feed("[story-guard] rendering Markdown and PDF reports")
        self.assertEqual(tracker.story_percent, 25)
        self.assertEqual(rendering[-1]["percent"], overall_percent(1, 2, 25))
        written = tracker.feed(_WRITTEN)
        self.assertEqual(tracker.story_percent, 100)
        self.assertEqual(written[0]["percent"], 50)
        self.assertEqual(written[1]["event"], "report")
        self.assertEqual(written[1]["story_id"], "121213")
        self.assertTrue(written[1]["pdf"].endswith("121213.pdf"))
        self.assertTrue(written[1]["markdown"].endswith("121213.md"))

    def test_a_failed_story_still_advances_the_batch(self) -> None:
        tracker = ProgressTracker(["121213", "123086"])
        tracker.feed("[story-guard] starting live generation for story 121213")
        tracker.feed(_WRITTEN)
        started = tracker.feed("[story-guard] starting live generation for story 123086")
        self.assertEqual(started[-1]["story_index"], 2)
        self.assertEqual(started[-1]["percent"], overall_percent(2, 2, 0))
        self.assertEqual(started[-1]["percent"], 50)
        self.assertEqual(started[-1]["ac_total"], 0)
        error = tracker.feed("story 123086: narrative failed after 4 attempts")
        self.assertEqual(error, [{
            "event": "error",
            "story_id": "123086",
            "message": "story 123086: narrative failed after 4 attempts",
        }])
        done = tracker.done_event()
        self.assertEqual(done["written"], ["121213"])
        self.assertEqual(done["failed"], ["123086"])

    def test_one_story_coverage_is_completed_criteria_over_total(self) -> None:
        line = (
            "[story-guard] reviewing AC-03 against US - 123086 "
            "(2/8, criterion part 1/1, description part 1/1, 2 tests)"
        )
        tracker = ProgressTracker(["123086"])
        tracker.feed("[story-guard] starting live generation for story 123086")
        tracker.feed(
            "[story-guard] live review started: 8 acceptance criteria across 1 suite batches"
        )
        ignored = tracker.feed(line)
        self.assertEqual(tracker.story_percent, 0)
        self.assertEqual(ignored[-1]["percent"], 0)
        tracker.feed("[story-guard] completed AC-01: 1 predicted test links")
        events = tracker.feed("[story-guard] completed AC-03: 2 predicted test links")
        self.assertEqual(tracker.story_percent, ac_coverage_percent(2, 8))
        self.assertEqual(events[-1]["percent"], 25)
        self.assertEqual(events[-1]["ac_completed"], 2)
        self.assertEqual(events[-1]["ac_total"], 8)

    def test_a_review_with_no_criteria_reaches_100_when_it_finishes(self) -> None:
        tracker = ProgressTracker(["121213"])
        tracker.feed("[story-guard] starting live generation for story 121213")
        tracker.feed(
            "[story-guard] live review started: 0 acceptance criteria and no fetched tests"
        )
        self.assertEqual(tracker.story_percent, 0)
        events = tracker.feed(
            "[story-guard] live review complete: model links checked and score calculated"
        )
        self.assertEqual(tracker.story_percent, 100)
        self.assertEqual(events[-1]["percent"], 100)


class ArgumentTests(unittest.TestCase):
    def test_generate_rejects_a_blank_request(self) -> None:
        self.assertEqual(main(["generate"]), 2)

    def test_generate_rejects_a_non_numeric_id(self) -> None:
        self.assertEqual(main(["generate", "--story-id", "abc"]), 2)
        self.assertEqual(main(["generate", "--story-id", "0"]), 2)
        self.assertEqual(main(["generate", "--story-id", "012"]), 2)

    def test_generate_rejects_story_ids_mixed_with_a_sprint(self) -> None:
        self.assertEqual(main(["generate", "--story-id", "121213", "--sprint", "Ecom MVP\\Sprint"]), 2)

    def test_usage_without_a_command(self) -> None:
        self.assertEqual(main([]), 2)

    def test_reject_message_is_json(self) -> None:
        from io import StringIO
        import contextlib

        buffer = StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["generate", "--story-id", "nope"])
        self.assertEqual(code, 2)
        event = json.loads(buffer.getvalue().strip())
        self.assertEqual(event["event"], "error")


if __name__ == "__main__":
    unittest.main()
