# 16 — CLI generate --story-id

**Owner:** Gugan (S5)
**Depends on:** [10](10-graph-through-score.md), [12](12-dummy-test-adapter.md), [14](14-pdf-from-sample-score.md), [15](15-one-narrative-call.md)
**Size:** M
**Status:** Done (7 Oct 2026)

## Outcome

`story-guard generate --story-id 121213` runs the full graph against the fixture and writes markdown under `artifacts/`. `--live` is absent or off by default. The demo script uses that default.

Node order on this command:

```
gate_input → fetch → validate_contract → score_health → write_narrative → render_pdf
```

`fetch` uses the fixture (tests through the slice 12 adapter). `render_pdf` may still be fed the hand-built sample until slice 21 swaps in the real score. This slice’s required artifact is the markdown. Slice 21 requires the PDF from the same command.

## Done when

- `story-guard generate --story-id 121213` exits 0.
- It writes `artifacts/121213.md` with the six headings.
- The default invocation does not pass `--live` and does not read `ADO_PAT`. A missing PAT still completes this default command.
- `scripts/demo.sh` runs that default command and nothing else. The script’s text has no `--live`.
- A bad story id exits non-zero and does not create `artifacts/121213.md`.
- A second narrative failure (slice 15) exits non-zero and does not create the PDF. If markdown was going to be written only after a successful narrative, it is absent too. The observable rule: a failed generate leaves no new report file for that story id.
- `--live` may be parsed as a flag that defaults to false. Slice 20 gives it behavior. Until slice 20, passing `--live` can exit with a clear “not wired” message. The default path must not require the flag.

## Work

- Extend `src/story_guard/cli.py` with `generate --story-id`.
- Invoke the graph from slice 10, then `write_narrative`, then the renderer.
- Write markdown to `artifacts/121213.md`. Create `artifacts/` if needed. The directory stays gitignored (slice 01).
- Add `scripts/demo.sh`.

## Check

```bash
story-guard generate --story-id 121213
test -f artifacts/121213.md
rg -n "live" scripts/demo.sh
story-guard generate --story-id 999999 ; echo exit:$?
```

The first command exits 0. The markdown file exists and contains the six headings. `scripts/demo.sh` does not contain `--live`. The bad id exits non-zero and does not leave `artifacts/999999.md`.

## Out of this slice

The LangSmith client and the live ADO fetch. Proving the PDF counts match the scorer is slice 21.
