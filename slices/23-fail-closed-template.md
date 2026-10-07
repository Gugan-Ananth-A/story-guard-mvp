# 23 — Fail closed on a bad template

**Owner:** Gugan (S5)
**Depends on:** [16](16-cli-generate.md), [21](21-wire-score-into-pdf.md)
**Size:** S
**Status:** Not started

## Outcome

When the report template is missing, `story-guard generate` exits non-zero and does not leave a new PDF in `artifacts/`.

This is the hard stop in `docs/requirements.md` §8.2: “Report PDF template missing or corrupted — nothing to render into.” Slice 14 proved the renderer function. This slice proves the generate command.

## Done when

- `templates/health_report.md` is the template path `generate` uses. It is the file from slice 07.
- Renaming or removing that file and running `story-guard generate --story-id 121213` exits non-zero.
- After that run, `artifacts/` has no new `121213.pdf`. If a PDF from a previous successful run is still on disk, this run does not replace it and does not create a second PDF. The practical check in the test: use a fresh `artifacts/` directory, run generate with the template missing, and assert `121213.pdf` does not exist.
- The narrative call does not need to succeed for this failure. Failing at render time is enough, and failing before the model call is better. Either way there is no new PDF. If the implementation calls the model before it notices the missing template, fix that: check the template path before `write_narrative`, so a missing file does not spend a model call.
- The test restores the template before it returns, including on assertion failure. The working tree’s `templates/health_report.md` is present after the suite.

## Work

- In the generate path, resolve the template path first. A missing file returns non-zero before `fetch` writes a report and before the narrative call.
- Add `tests/test_missing_template.py`. It points the command at a temporary artifacts directory and a template path that does not exist (a missing path argument, or a rename inside a try/finally that always renames it back).

## Check

```bash
pytest tests/test_missing_template.py
test -f templates/health_report.md
```

The test passes. The template file is back at its path. A manual probe — move the template aside, run generate, confirm a non-zero exit and no new PDF, move the template back — matches the test. The suite is the merge check.

## Out of this slice

A repair flow that generates with a built-in fallback template. A missing template is a hard stop. There is no second template.
