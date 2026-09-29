# 20 — Optional live fetch behind a flag

**Owner:** Thabitha (S2)
**Depends on:** [11](11-ado-client.md), [12](12-dummy-test-adapter.md), [16](16-cli-generate.md)
**Size:** S
**Status:** Not started
**Slip:** drop this slice second, after slice 17. The demo does not need it.

## Outcome

`story-guard generate --story-id 121213 --live` loads the story through the ADO client and loads tests through the fixture adapter. The default command does not use `--live`. The demo script uses the default.

## Done when

- `--live` defaults to off. `story-guard generate --story-id 121213` uses `fixtures/FIX-121213.json` for the story and the tests, and it does not call Azure DevOps.
- With `--live`, `fetch` calls the slice 11 client for the story and the slice 12 adapter for the tests. Tests still come from `fixtures/FIX-121213.json`. `mapped_ac_ids` stay empty. The live path does not pull Test Plans.
- A 404 from the client, or a work item that is not a User Story, becomes a non-zero exit and writes no report file. The typed errors from slice 11 are what the gate catches.
- `scripts/demo.sh` runs the default command. Its text has no `--live`.
- The README says the default is the fixture, and that `--live` needs `ADO_PAT` in `.env`.

## Work

- Branch inside `fetch` on the flag. Keep the node list from slice 16.
- The live story mapper and the fixture must both satisfy `validate_contract`. If the live description still contains the eight `Scenario:` lines, the same splitter used for the fixture may run on that description. It must leave `acceptance_criteria` empty when the AC field is absent.
- Do not let `--live` overwrite `fixtures/FIX-121213.json`.

## Check

```bash
rg -n "live" scripts/demo.sh
pytest -k live
```

The demo script has no `--live` match. A unit test stubs the ADO client and asserts the default path does not call it, and that `--live` calls it once and still calls the fixture adapter for tests. A 404 stub exits non-zero and creates no file under a temp `artifacts/` directory.

A real `--live` against Ecom MVP is a manual check when a PAT is present. It is not required to merge the slice. Do not print the PAT in that check.

## Out of this slice

Fetching tests from Azure Test Plans, and making `--live` the demo.
