# 01 — Python package and repo guard rails

**Owner:** Gugan (S1)
**Depends on:** nothing
**Size:** S
**Status:** Done (30 Sep 2026)

## Outcome

A clone of this repo installs a Python package, runs `pytest` with no feature tests, and has a `story-guard` command. Secrets and generated files have a place to live that git does not track.

## Done when

- `pyproject.toml` exists and the install uses a `src` layout at `src/story_guard/`.
- A console script named `story-guard` is wired to a function in that package. Running it exits 0.
- `pytest` from the repo root exits 0 when the suite has no feature tests yet. Later slices add tests to this same command.
- `.gitignore` ignores `.env` and `artifacts/`.
- `.env.example` lists the variable names and leaves every secret blank. Names this sprint needs:
  - `ADO_ORG` — may show `rootquotient`
  - `ADO_PROJECT` — may show `Ecom MVP`
  - `ADO_PAT` — blank
  - `OLLAMA_HOST` — may show `http://127.0.0.1:11434`
  - `OLLAMA_MODEL` — may show `qwen3.5:4b`
  - `LANGSMITH_API_KEY` — blank
  - `LANGSMITH_PROJECT` — may name a project; the key stays blank
- Python is 3.12 or newer, matching the stack note in the week-2 plan.

## Work

- Add `pyproject.toml` with a `src` layout and the `story-guard` script entry.
- Add `src/story_guard/__init__.py` and `src/story_guard/cli.py`. The CLI in this slice prints a one-line usage and returns 0. Slice 03 hangs the first graph on this command. Slice 16 adds `generate`.
- Add an empty `tests/` package (or the equivalent pytest root). Do not add a product assertion yet.
- Add `.gitignore` entries for `.env` and `artifacts/`.
- Add `.env.example` with the names above. Commit that file. Do not commit `.env`.

## Check

```bash
pip install -e .
story-guard
pytest
git check-ignore -v .env artifacts/example.pdf
```

`story-guard` and `pytest` both exit 0. `git check-ignore` matches `.env` and the artifacts path. `git grep` over the tracked tree finds no PAT value. `.env.example` contains the name `ADO_PAT` and the name `LANGSMITH_API_KEY` with empty values.

## Out of this slice

Ollama, LangGraph, fixtures, and the generate subcommand. Those are slices 02, 03, and 16.
