# 04 — Freeze the fixture field names

**Owner:** Thabitha (S8)
**Depends on:** nothing
**Size:** S
**Status:** Not started

## Outcome

`fixtures/SCHEMA.md` is the naming law for this sprint. Story, test, and bug records use one spelling, and the scorer, the ADO mapper, and the dummy adapter all import that spelling.

This closes the naming half of TBD-DATA-2 for the 121213 demo. `docs/contracts.md` can follow; this slice’s deliverable is `fixtures/SCHEMA.md`.

## Done when

- `fixtures/SCHEMA.md` exists and uses `ac_id` and `mapped_ac_ids`.
- The file has one convention. A search of the file finds no `acId`, no `covers`, and no `mapped_ac` used as a field name. Prose may say “mapped AC” in a sentence. The field is `mapped_ac_ids`.
- The records match `docs/requirements.md` §6.3:
  - **StoryRecord** — id, title, type, state, description, area, iteration, raw AC text, discrete AC list
  - **AcceptanceCriterion** — `ac_id`, text, testable flag, ambiguity flags
  - **TestCase** — id, title, type (`happy` / `negative` / `edge` / `security` / `adhoc`), `mapped_ac_ids`, last result, last result time, linked bug ids
  - **BugRecord** — id, title, severity, priority, status, age, found-in environment, linked story id, linked test id
- The AC field and the description scenarios are different fields. The schema says so in one paragraph, because on 121213 the AC field is empty and the scenarios live in the description (`docs/requirements.md` §6.2, TBD-DATA-1).
- Test `type` is the §6.3 enum. The schema says the author prefix `P` / `N` / `A` on the 121213 titles is not that enum (`docs/requirements.md` §6.2.2).

## Work

Write `fixtures/SCHEMA.md` with snake_case JSON keys under the names above. Suggested keys, so later slices agree:

| Record | Keys |
| --- | --- |
| StoryRecord | `id`, `title`, `type`, `state`, `description`, `area`, `iteration`, `acceptance_criteria_raw`, `acceptance_criteria`, `scenarios`, `note` |
| AcceptanceCriterion | `ac_id`, `text`, `testable`, `flags` |
| TestCase | `id`, `title`, `type`, `mapped_ac_ids`, `last_result`, `last_result_at`, `linked_bug_ids` |
| BugRecord | `id`, `title`, `severity`, `priority`, `status`, `age`, `found_in`, `linked_story_id`, `linked_tc_id` |

`acceptance_criteria` is the discrete list from the AC field. `scenarios` is the list split out of the description. Both lists use AcceptanceCriterion. They are not aliases of each other.

`mapped_ac_ids` is an array of `ac_id` strings. An empty array is a real value. It means the test covers nothing (§6.4).

## Check

```bash
test -f fixtures/SCHEMA.md
rg -n "acId|covers" fixtures/SCHEMA.md
```

The file exists. The search prints no matches. The file contains `ac_id` and `mapped_ac_ids`, and it lists the StoryRecord, TestCase, and BugRecord fields from §6.3.

## Out of this slice

The 121213 payload itself (slice 05), the scorer (slice 09), and a second schema file. One convention, one file.
