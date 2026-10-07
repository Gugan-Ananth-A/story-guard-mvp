# Phase 1 slices — Sprint 1

**Plan date:** 30 Sep 2026
**Window:** Tue 29 Sep – Thu 1 Oct 2026. 4 hours a day for Gugan, Thabitha, and Valliammai (36 hours).
**Demo:** `story-guard generate --story-id 121213` writes `artifacts/121213.pdf`.
**Sample:** Azure DevOps story 121213, SNAP Login Screen, recorded in `docs/requirements.md` §6.2.
**Defaults:** the fixture is the source. `--live` is off. One local model. One narrative call.

This folder is the build plan for that demo. `docs/requirements.md`, `docs/orchestration-and-cost.md`, and `docs/architecture.md` stay the contracts. A slice that needs a fact from those files cites the section. It does not reopen the decision.

Slices 01, 02, 03, 04, and 05 are done. Slices 09 and 10 landed on 30 Sep 2026 against the old Red rule and are in rework for the banking-PDF health rule. The rest are not started.

## How to read a card

Each file in this folder is one slice. A slice is done when its **Done when** list is true and its **Check** command (or inspection) passes. The next slice can start from that tree.

Cards name paths so two people do not invent two layouts. The paths the demo depends on:

| Path | What it is |
| --- | --- |
| `pyproject.toml`, `src/story_guard/` | Package and the `story-guard` command |
| `.env.example` | Variable names. Secret values stay blank |
| `fixtures/SCHEMA.md` | Field names for this sprint |
| `fixtures/FIX-121213.json` | The only fixture this sprint scores |
| `fixtures/FIX-121213.md` | The counts a reader checks the PDF against |
| `docs/pdf-library.md` | The D8 lock for this sprint |
| `docs/rag-stand-in.md` | SR-1, SR-2, and SR-3, labeled stand-in |
| `templates/health_report.md` | The six section headings |
| `prompts/rubric_v1.md` | The stable narrative prefix |
| `artifacts/121213.pdf` | The demo output |
| `artifacts/runs.jsonl` | Local token count and latency |
| `scripts/demo.sh` | The demo command, without `--live` |

## Order and owners

Sizes are planning weight for a 4-hour day. S fits beside another slice. M is most of a day. Demo-critical slices stay if Thursday slips. The two drop slices are 17 and 20.

| # | Slice | Owner | Bucket | Depends on | Size | Demo |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | [Repo guard rails](01-repo-guard-rails.md) | Gugan | S1 | — | S | Yes |
| 02 | [Ollama and qwen3.5:4b](02-ollama-qwen.md) | Gugan | S1 | 01 | S | Yes |
| 03 | [LangGraph on the path](03-langgraph-path.md) | Gugan | S1 | 01 | S | Yes |
| 04 | [Fixture field names](04-fixture-field-names.md) | Thabitha | S8 | — | S | Yes |
| 05 | [FIX-121213.json](05-fix-121213.md) | Thabitha | S8 | 04 | M | Yes |
| 06 | [PDF library (D8)](06-pdf-library-d8.md) | Valliammai | S6 | — | S | Yes |
| 07 | [Six section headings](07-section-headings.md) | Valliammai | S6 | — | S | Yes |
| 08 | [Rubric prefix, first cut](08-rubric-prefix-start.md) | Valliammai | S4 | — | S | Yes |
| 09 | [Score 121213](09-score-121213.md) | Gugan | S5 | 01, 04, 05 | M | Yes — rework |
| 10 | [Graph through score](10-graph-through-score.md) | Gugan | S5 | 03, 09 | S | Yes — rework |
| 11 | [ADO client](11-ado-client.md) | Thabitha | S2 | 01, 04 | M | Drop candidate |
| 12 | [Dummy test adapter](12-dummy-test-adapter.md) | Thabitha | S3 | 04, 05 | S | Yes |
| 13 | [Prefix ready to send](13-rubric-prefix-sendable.md) | Valliammai | S4 | 08 | S | Yes |
| 14 | [PDF from a sample score](14-pdf-from-sample-score.md) | Valliammai | S6 | 06, 07 | M | Yes |
| 15 | [One narrative call](15-one-narrative-call.md) | Gugan | S5 | 02, 09, 13 | M | Yes |
| 16 | [CLI generate](16-cli-generate.md) | Gugan | S5 | 10, 12, 15, 14 | M | Yes |
| 17 | [Local trace and LangSmith](17-local-trace-langsmith.md) | Gugan | S7 | 16 | S | No — drop first |
| 18 | [Expected counts](18-expected-counts.md) | Thabitha | S8 | 05, 09 | S | Yes |
| 19 | [pytest locks the counts](19-pytest-locks-counts.md) | Gugan | S5 | 09, 18 | S | Yes |
| 20 | [Live fetch flag](20-live-flag.md) | Thabitha | S2 | 11, 12, 16 | S | No — drop second |
| 21 | [Real score into the PDF](21-wire-score-into-pdf.md) | Gugan | S5 | 16, 18 | M | Yes |
| 22 | [Prefix hash is stable](22-prefix-stable.md) | Valliammai | S4 | 13, 16 | S | Yes |
| 23 | [Bad template fails closed](23-fail-closed-template.md) | Gugan | S5 | 16, 21 | S | Yes |

Lanes that can move on the same day:

- **Gugan** builds the package, the graph, the scorer, the one model call, and the CLI.
- **Thabitha** freezes the schema and the fixture, then the dummy test adapter. The ADO client is real work and is the first thing to pause if her lane slips, because the demo reads the fixture.
- **Valliammai** locks D8, the six headings, the rubric prefix, and a PDF rendered from a hand-built score. Gugan wires that renderer to the live score in slice 21.

`04`, `06`, `07`, and `08` are documents. They can start before slice 01 merges.

## Thursday exit

The demo is green when all of these are true:

1. `scripts/demo.sh` runs `story-guard generate --story-id 121213` and does not pass `--live`.
2. The command writes `artifacts/121213.md` and `artifacts/121213.pdf`.
3. The PDF shows the six headings from slice 07, in that order.
4. The counts in the PDF match `fixtures/FIX-121213.md`: AC field empty, 8 scenarios, 18 tests, 0 mapped, 0 bugs, 8 not covered, story health No open bugs, rules SR-1, SR-2, and SR-3.
5. `pytest` asserts those counts from the scorer. A covered AC fails the test. A non-zero bug count fails the test.
6. Two generates record the same prefix hash, and the hashed bytes contain no story id.

If the clock runs out, stop in this order: slice 17 (LangSmith client), then slice 20 (`--live`). Keep the narrative call, the CLI, the count test, and the PDF. A local `artifacts/runs.jsonl` line is part of slice 17; if the LangSmith client is cut, still append that line when the generate path already has the numbers in hand.

## What this sprint leaves open

These stay open on purpose. A slice must not close them by inventing a second rule:

| Still open | What this sprint does instead |
| --- | --- |
| TBD-HEALTH-1, Vignesh accepting the story-health rule | SR-1, SR-2, and SR-3 in `docs/rag-stand-in.md`, labeled stand-in. 121213 is No open bugs under SR-2. Coverage is the separate SR-3 table. |
| TBD-HEALTH-2, keep / park / drop on H1–H12 | The scorer reports the counts in slice 09. It does not ship H7 or H10. |
| TBD-DATA-1, which field H1 reads | The AC field and the description scenarios are stored apart. The score reports the AC field empty and eight description scenarios. |
| TBD-GATES-1, G4 / G5 | A bad story id writes no file. An empty AC field still generates. |
| TBD-FIX-1, the five-row fixture matrix | One file, `fixtures/FIX-121213.json`. The other personas wait. |
| TBD-ARCH-3 | No rubric-cache server, no tool registry, no second model context. The prefix is a file and a hash. |
| D6 / D10 reversal | The graph is code nodes plus one narrative call. |

## Rules every slice inherits

- Dummy data and story 121213 only. The PAT stays in `.env`.
- Coverage comes from `mapped_ac_ids`. An empty list covers nothing. The button-disabled contradiction is a note on the story.
- The narrative call is one Ollama request: prefix, then the score JSON, JSON mode, no tools, `num_ctx` 8192. Invalid JSON retries that call once. A second failure writes no PDF. There is no rewrite call.
- Development model is `qwen3.5:4b`. `phi4-mini` is the fallback, loaded only when the default is not resident. The README says not to load both.
- The PDF library chosen in slice 06 renders on the 8 GB Mac and does not launch a browser.
