# 19 — pytest locks the counts

**Owner:** Gugan (S5)
**Depends on:** [09](09-score-121213.md), [18](18-expected-counts.md)
**Size:** S
**Status:** Done (7 Oct 2026)

## Outcome

A test runs the scorer on `fixtures/FIX-121213.json` and asserts the counts published in `fixtures/FIX-121213.md`. The suite fails if any AC is covered. The suite fails if the bug count is not zero.

This is the regression lock for the demo. A later edit that “helpfully” maps the 18 tests onto AC-1–AC-8 fails here.

## Done when

- `tests/test_score_121213.py` loads `fixtures/FIX-121213.json`, calls `score_health`, and asserts:
  - AC field empty
  - scenario count 8
  - test count 18
  - mapped count 0
  - bug count 0
  - open bug count 0
  - none count 8
  - story health `No open bugs`
  - rule ids `SR-1`, `SR-2`, and `SR-3`
- The test fails when any scenario is covered. Assert `covered` is false on every scenario, and assert the union of mapped test ids is empty.
- The test fails when `bug_count` is anything other than 0.
- The test does not call Ollama, Azure DevOps, or the PDF renderer.

## Work

- Add the test. If slice 09 already added a thinner test, fold it into this file so one test owns the published counts.
- Read the expected numbers from the test body as literals that match `fixtures/FIX-121213.md`. A comment at the top of the test points at that page. Do not parse the markdown to discover the expected numbers; a drift should show up as a disagreement a human can see.

## Check

```bash
pytest tests/test_score_121213.py
```

The test passes on the fixture as committed. Flipping one test’s `mapped_ac_ids` to `["AC-1"]` in a temporary copy, or appending a bug, fails the test. Restore the fixture after that probe. The committed fixture stays at mapped 0 and bugs 0.

## Out of this slice

Asserting narrative prose, PDF bytes, or the other fixture personas.
