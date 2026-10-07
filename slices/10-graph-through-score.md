# 10 — Graph through score, no model yet

**Owner:** Gugan (S5)
**Depends on:** [03](03-langgraph-path.md), [09](09-score-121213.md)
**Size:** S
**Status:** Done (30 Sep 2026)

## Outcome

The LangGraph path runs four code nodes and prints the score JSON for story 121213. Fetch reads the fixture. A story id the fixture does not contain stops the run before any file is written.

Nodes, in this order:

```
gate_input → fetch → validate_contract → score_health
```

No node calls Ollama. `write_narrative` and `render_pdf` are added in later slices on this same graph.

## Done when

- `gate_input` accepts `121213` and rejects a blank id, a non-numeric id, and any id other than `121213`. Rejection exits non-zero.
- `fetch` loads `fixtures/FIX-121213.json` for `121213`. It does not call Azure DevOps. Slice 12 may move the test rows behind the dummy adapter; the node name stays `fetch`.
- `validate_contract` checks the payload against `fixtures/SCHEMA.md` (StoryRecord, the test rows, the bug list). A contract failure exits non-zero.
- `score_health` is the function from slice 09. The CLI prints its JSON to stdout.
- A bad story id (for example `999999` or `121214`) exits non-zero, and the run creates no file under `artifacts/`. Gate failure happens before `fetch` writes anything. This slice’s fetch should not write a file at all; the “no file” check is there so a later edit cannot start writing on the error path.
- The process that prints the score for `121213` exits 0.

## Work

- Extend `src/story_guard/graph.py` from the one-node graph in slice 03 to these four nodes.
- Add a CLI entry that takes a story id, invokes the graph, and prints the score JSON. Slice 16 grows this entry into `story-guard generate --story-id`. Keep one graph module.
- On gate or contract failure, print a short error to stderr and return a non-zero code. Do not catch that failure and continue.

## Check

```bash
story-guard score --story-id 121213
story-guard score --story-id 999999 ; echo exit:$?
```

The first command prints JSON with `rag` Red, `mapped_count` 0, `scenario_count` 8, `test_count` 18, `bug_count` 0, and exits 0. The second exits non-zero. `git status -- artifacts` shows no new file after the second command. `rg` over the four node functions shows no `ollama` and no `11434`.

The subcommand may be named `score` until slice 16 adds `generate`. What matters is the four-node order and the two exits.

## Out of this slice

The narrative call, the PDF, `--live`, and LangSmith.
