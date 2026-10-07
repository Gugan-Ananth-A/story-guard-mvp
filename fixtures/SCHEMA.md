# Fixture schema

Naming law for this sprint. Story, test, and bug records use one spelling. The scorer, the ADO mapper, and the dummy adapter use these keys.

The AC field and the description scenarios are different fields. On story 121213 the AC field is empty and the scenarios live in the description (`docs/requirements.md` §6.2, TBD-DATA-1). `acceptance_criteria` is the discrete list from the AC field. `scenarios` is the list split out of the description. Both lists use AcceptanceCriterion. They are not aliases of each other.

A new scenario starts on a line whose first non-space text is `Scenario:`. The 121213 sample yields eight blocks.

Records match `docs/requirements.md` §6.3.

## StoryRecord

Keys: `id`, `title`, `type`, `state`, `description`, `area`, `iteration`, `acceptance_criteria_raw`, `acceptance_criteria`, `scenarios`, `note`.

`type` for a story this sprint scores is `User Story`.

## AcceptanceCriterion

Keys: `ac_id`, `text`, `testable`, `flags`.

`ac_id` is a pack label such as `AC-1`. It is not a field on the work item.

## TestCase

Keys: `id`, `title`, `type`, `mapped_ac_ids`, `last_result`, `last_result_at`, `linked_bug_ids`.

`type` is one of `happy`, `negative`, `edge`, `security`, `adhoc`. An empty string means unset. The author prefix `P` / `N` / `A` on the 121213 titles is not this enum (`docs/requirements.md` §6.2.2). That prefix stays in the title. It is not copied into `type`.

`mapped_ac_ids` is an array of `ac_id` strings. An empty array is a real value. It means the test maps to no `ac_id` (`docs/requirements.md` §6.4).

## BugRecord

Keys: `id`, `title`, `severity`, `priority`, `status`, `age`, `found_in`, `linked_story_id`, `linked_tc_id`, `assigned_to`, `application`, `created`.

`priority` is `P1`, `P2`, `P3`, or `P4` when the source has it. The scorer does not copy `severity` into `priority`.

`assigned_to`, `application`, and `created` may be an empty string. The bug table in `docs/requirements.md` §10 prints a blank cell for an empty string. Story 121213 has no bug rows, so those three keys are unused on that file. A bug record that omits them still matches this sprint's contract. When the key is present it is a string.

## Fixture file

`fixtures/FIX-121213.json` is one StoryRecord plus `tests` (an array of TestCase) and `bugs` (an array of BugRecord).
