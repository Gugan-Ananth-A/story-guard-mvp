# 14 — Render a PDF from a hand-built score object

**Owner:** Valliammai (S6)
**Depends on:** [06](06-pdf-library-d8.md), [07](07-section-headings.md)
**Size:** M
**Status:** Not started

## Outcome

A hand-built score JSON runs through `templates/health_report.md` and a PDF is written with the library locked in slice 06. The sample counts appear as text in the PDF. A missing template exits non-zero and writes no file.

The sample is not a model call and not `score_health`. Slice 21 points the same renderer at the real score.

## Done when

- The sample lives at `tests/data/sample_score.json` (not at `fixtures/FIX-121213.json`). Its counts match the demo so the PDF is readable against the later page: AC field empty, 8 scenarios, 18 tests, 0 mapped, 0 bugs, RAG Red, rule SR-2.
- A function `render_pdf(score, template_path, out_path)` fills the eight sections and writes a PDF.
- The PDF text contains the eight headings from slice 07, in that order, and contains the sample counts (the digits and the word Red, plus a line that the AC field is empty).
- The renderer uses the library named in `docs/pdf-library.md`. It does not start a browser process.
- When `template_path` does not exist, the function exits non-zero (or raises an error the CLI maps to non-zero) and the output path is not created.
- Markdown is produced as well, because QA reviews markdown first (`docs/requirements.md` §10). The markdown contains the same eight headings and the same counts. This slice may write both next to the PDF in a temp directory. Slice 16 chooses the `artifacts/` names.

## Work

- Add `src/story_guard/render.py`.
- Keep headings in the template file. The renderer does not hard-code a second outline.
- Add a test that renders to a temp directory and extracts the PDF text (the library’s text extract, or `pypdf` if the locked library does not extract). Assert the counts and the eight headings.
- Add a test that points at a missing template path, asserts non-zero, and asserts the destination file is absent.

## Check

```bash
pytest -k render
```

Both the happy render and the missing-template case pass. The test PDF is under the temp dir or under `artifacts/` and is gitignored. It is not committed.

## Out of this slice

Calling Ollama, reading `score_health`, and the `generate` command. Those join in slices 16 and 21.
