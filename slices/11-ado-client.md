# 11 — ADO client for work item 121213

**Owner:** Thabitha (S2)
**Depends on:** [01](01-repo-guard-rails.md), [04](04-fixture-field-names.md)
**Size:** M
**Status:** Not started

## Outcome

A read-only client loads work item 121213 from Azure DevOps with relations, using the PAT from the environment, and maps it to the StoryRecord from slice 04. Failure is a typed error the gate can turn into a non-zero exit. The unit test never touches the network.

This slice is not on the demo’s default path. Slice 20 is what calls it, and only behind `--live`. If Thursday slips, this client can remain unit-tested and unwired.

## Done when

- The client sends `GET` for the work item with relations (`$expand=relations`), `api-version=7.1`, org and project from `ADO_ORG` and `ADO_PROJECT`, PAT from `ADO_PAT`.
- The mapper returns a StoryRecord: id, title, type, state, description, area, iteration, raw AC text, discrete AC list. For the real 121213 payload the AC field is absent, so `acceptance_criteria_raw` is empty and `acceptance_criteria` is `[]`. Description text is passed through. Scenario splitting may stay in the fixture path; the mapper must not invent `mapped_ac_ids`.
- Relations that are bugs become BugRecord rows. 121213 has no relations, so the bug list is empty.
- HTTP 404 raises a typed error (name it `StoryNotFound` or equivalent, in one module the gate can import).
- A work item whose type is not User Story raises a different typed error (name it `NotAUserStory`).
- The gate, or a function the gate calls, maps either error to a non-zero process exit when this client is invoked from the CLI. The unit test asserts the exception type. It does not need the process exit itself if a one-line test covers the mapper from exception to exit code.
- The unit test loads a sanitized JSON file from the repo (for example `tests/data/work_item_121213.json`) and does not open a socket. Sanitized means no PAT, no email address, no avatar URL, and no `System.AssignedTo` unique name. Id, title, type, state, description, an absent AC field, and an empty relations array are enough.
- The test file and the client module contain no real PAT. The client reads `ADO_PAT` from the environment at request time.

## Work

- Add `src/story_guard/ado.py` with `fetch_work_item(story_id) -> StoryRecord` and the two exception types.
- Add the sanitized JSON and `tests/test_ado_mapper.py`.
- Point the HTTP call at `https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{id}`. This is the work-item endpoint. The test adapter in slice 12 is a different module and must not grow a Test Plans URL.

## Check

```bash
pytest tests/test_ado_mapper.py
rg -n "Authorization|PAT|@" tests/data/work_item_121213.json
```

The test passes with the network disabled (the test never builds a client session). The search finds no secret and no email. A 404 fixture and a Bug-type fixture each raise the matching type.

## Out of this slice

Test Plans, WIQL, write operations, and the default generate path. Slice 12 serves tests from the fixture. Slice 20 is the only caller of this client in the CLI.
