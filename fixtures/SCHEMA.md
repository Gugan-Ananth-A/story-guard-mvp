# Fixture schema

This file is the canonical field contract for fixture records. Field names use `snake_case` throughout. Record shapes align with `docs/requirements.md` §6.3.

## StoryRecord

| Field | Meaning |
| --- | --- |
| `id` | Stable story identifier |
| `title` | Story title |
| `type` | Work-item type |
| `state` | Current story state |
| `description` | Story description |
| `area` | Area path or equivalent |
| `iteration` | Iteration path or equivalent |
| `raw_ac_text` | Original acceptance-criteria text from the source |
| `acceptance_criteria` | Discrete `AcceptanceCriterion` records for this story |

## AcceptanceCriterion

| Field | Meaning |
| --- | --- |
| `ac_id` | Stable criterion identifier within the story |
| `text` | Criterion text |
| `testable` | Whether the criterion has a pass/fail outcome |
| `ambiguity_flags` | Explicit ambiguity findings; empty when none are recorded |

## TestCase

| Field | Meaning |
| --- | --- |
| `id` | Stable test-case identifier |
| `title` | Test-case title |
| `type` | One of `happy`, `negative`, `edge`, `security`, or `adhoc` |
| `mapped_ac_ids` | Explicitly linked acceptance-criterion identifiers; an empty list means no criteria are linked |
| `last_result` | Most recent execution result, when available |
| `last_result_at` | Timestamp of the most recent execution result, when available |
| `linked_bug_ids` | Identifiers of bugs linked to this test case |

## CoverageSummary

| Field | Meaning |
| --- | --- |
| `by_type` | Precomputed test counts by coverage type |
| `mapped_count` | Precomputed count of mapped tests |
| `unmapped_count` | Precomputed count of unmapped tests |

Coverage values are fixture data. The evaluation layer reads them; it does not infer or recompute them from narrative text.

## BugRecord

| Field | Meaning |
| --- | --- |
| `id` | Stable bug identifier |
| `title` | Bug title |
| `severity` | Bug severity |
| `priority` | Bug priority |
| `status` | Current bug status |
| `age` | Bug age as represented by the source fixture |
| `found_in_env` | Environment where the bug was found |
| `linked_story_id` | Identifier of the linked story |
| `linked_tc_id` | Identifier of the linked test case, when present |

## HealthReport

The report record contains `story_header`, `rag`, `per_signal_scores`, `narrative`, `recommended_actions`, and `appendix_raw_ids`.

## Traceability

A test is linked to an acceptance criterion only when its `mapped_ac_ids` explicitly contains that criterion's `ac_id`. Missing links remain missing; they are never inferred from titles or text. This follows `docs/requirements.md` §6.4.
