# 03 — LangGraph on the path

**Owner:** Gugan (S1)
**Depends on:** [01](01-repo-guard-rails.md)
**Size:** S
**Status:** Not started

## Outcome

LangGraph is a project dependency, and a one-node graph runs from the CLI. The node is plain Python. It does not call Ollama.

This is D6 as a workflow graph of code nodes (`docs/orchestration-and-cost.md` §1 and §3). A supervisor of specialist models is a different design and is not this slice.

## Done when

- `langgraph` is declared in `pyproject.toml` and installs with the package.
- A `StateGraph` with one node runs from `story-guard` and the process exits 0.
- That node does not open a socket to `11434`, does not import an LLM client, and does not read `.env`.

## Work

- Add the `langgraph` dependency.
- Add `src/story_guard/graph.py` with a one-node `StateGraph`. The node writes a fixed key on the state (for example `graph` = `ok`) and returns.
- Point a CLI path at that graph so `story-guard` (or a subcommand this slice adds and slice 16 keeps) invokes it and exits 0.
- Leave room for the later node list. Slice 10 replaces this single node with `gate_input → fetch → validate_contract → score_health`. Keep the graph in this module so that replacement is an edit, not a second framework.

## Check

```bash
story-guard
python -c "import langgraph, story_guard.graph"
```

The CLI exits 0. `rg` over `src/story_guard/graph.py` shows a `StateGraph` and shows no `11434`, no `ollama`, and no `Chat` client.

## Out of this slice

Scoring, fixtures, and the narrative node. The one node is a path check only.
