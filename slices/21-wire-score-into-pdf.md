# 21 — Wire the real score into the PDF

**Owner:** Gugan (S5), with the renderer from Valliammai (S6)
**Depends on:** [16](16-cli-generate.md), [18](18-expected-counts.md)
**Size:** M
**Status:** Not started

## Outcome

`story-guard generate --story-id 121213` writes `artifacts/121213.pdf`. The PDF shows the six sections and the same counts as `fixtures/FIX-121213.md`. The narrative’s numbers match the score JSON.

This is the demo artifact. The hand-built sample from slice 14 stays available to the renderer tests. `generate` does not read `tests/data/sample_score.json`.

## Done when

- The command writes `artifacts/121213.pdf` and exits 0. It also writes `artifacts/121213.md` (slice 16).
- Opening the PDF shows the six headings from `templates/health_report.md`, in that order, and no seventh section.
- The PDF text shows: AC field empty, scenarios 8, tests 18, mapped 0, bugs 0, 8 not covered, story health No open bugs.
- Those values were produced by `score_health` on the fixture for this run. They were not edited in the template and not taken from the hand-built sample.
- The narrative cites those counts. A check compares the numbers that appear in the narrative JSON (`headline` and `sections`) with the score JSON from the same run. A narrative that states a different test count, a different mapped count, a different bug count, a different story health, or that an AC is covered fails the run and writes no PDF.
- `source` on the default path is the fixture, and the title block says so.

## Work

- Pass the `score_health` result into `render_pdf`. Pass the narrative object in beside it for the headline, the section prose, and the actions.
- Before render, compare the narrative’s stated counts to the score. The prefix already tells the model not to invent coverage. This check is the code side of that rule: the model does not get the last word on the digits.
- Keep the comparison on counts the score actually has: scenario count, test count, mapped count, bug count, none count, story health, AC field empty. Do not require the model to echo every test title. Do not require a coverage percentage.

## Check

```bash
story-guard generate --story-id 121213
python -c "
from pathlib import Path
p=Path('artifacts/121213.pdf')
assert p.exists() and p.stat().st_size > 0
"
```

Extract the PDF text in the test and assert the six headings and the counts from `fixtures/FIX-121213.md`. A stubbed narrative that says 17 tests, or that says an AC is covered, or that calls the story Red, exits non-zero and does not leave a new `artifacts/121213.pdf`.

## Out of this slice

A second generate for a rewrite, a different story id, and a hand-edited PDF checked in as the demo. The demo is the command, re-runnable.
