# How Story Guard evaluates a story today

This is the behavior in the current code. A sprint is not scored as one object. Each User Story is fetched, judged, and written as its own report. The model proposes which tests cover which acceptance criteria. Python then decides the row status, the coverage percent, and story health.

There are two generate paths. They do not feed the model the same facts.

| Command | What is scored | Who maps tests to criteria |
| --- | --- | --- |
| `story-guard score --story-id 121213` | Fixture `fixtures/FIX-121213.json` only | Nobody. Empty `mapped_ac_ids` stay empty. No model call. |
| `story-guard generate --story-id 121213` | The same fixture | The narrative model writes prose over the score. It does not map tests or set the percent. |
| `story-guard generate --story-id <id> --live` | That User Story from Azure DevOps | The live reviewer, one criterion and one suite batch at a time. |
| `story-guard generate --story-ids 121213,123086 --live` | Each id, one after another | Same live reviewer. One story's failure does not stop the next. |
| `story-guard generate --sprint "<iteration path>" --live` | Every User Story on that exact iteration path | Same live reviewer, one story at a time. |
| `story-guard generate --sprint "<iteration path>"` | Every User Story on that path, with a narrower fetch | Still the live reviewer. The Acceptance Criteria field is not parsed on this path. |

`story-guard sprints` and `story-guard list-stories` only list iteration paths and story ids. They do not score anything.

## What the live reviewer is asked to do

`analyze_live` in `src/story_guard/analysis.py` sends one JSON request per text part. The system prompt is fixed. The user message is the only source of facts for that call. The payload is:

- `story_id`
- one acceptance-criterion part (`ac_id`, text, part number)
- one optional story-description part
- one suite (`id`, `name`)
- the tests in that batch (`id`, `type`, part number, text)

Bugs are not in the payload. Existing Azure DevOps links are not in the payload. `mapped_ac_ids` on the fetched cases stays empty, and the reviewer is told to ignore source links.

The model must return one object:

- `ac_id`, copied from the criterion
- `mapped_test_ids`, ids copied from this batch
- `test_types`, a path label per mapped id
- `coverage_status`: `adequate`, `partial`, or `none` for this batch only
- `quality`: `good`, `needs_improvement`, or `poor`, plus `testable` and short issues
- `finding`: one sentence

The prompt tells the model to list a test when its title, description, steps, or parameters check this criterion, including a negative or adhoc case of the same behavior. A shared generic word such as "login" is not a match. A title token such as `-P01`, `-N04`, or `-A06` is the path label: P is happy, N is negative, A is adhoc. An empty source type does not block a match. `positive` is stored as happy, `security` as negative, and `edge` as adhoc. Any other label is dropped.

The model must not invent a test id, use a percent sign, write "partially covered", or set story health. A finding that breaks those rules is replaced with a short default sentence. A test id that was not in this batch is dropped. A bad JSON body is sent back with the reason. After four rejected answers that story fails and no report is written. The next story still runs.

Calls for one story run one at a time. A story with no fetched tests makes no model call. Every criterion is then `none`.

## How a user story is loaded

`generate --story-id <id> --live` and `generate --sprint "<path>" --live` use the same loader, `ADOClient.load_live_story`.

The work item must be a User Story. A missing id, a deleted id, and a non-story exit with no report. Related work items that Azure DevOps returns 404 for are skipped.

Tests come from links on the story:

- A linked Test Plan loads every suite in that plan.
- A linked Test Suite loads only that suite, from the plan that contains it.
- A Test Case linked directly on the story is added when it is not already in a suite.
- `--test-plan-id` replaces that discovery and is allowed only when the batch is exactly one story. A plan id loads every suite. A suite id loads only that suite.

Suite membership is not coverage. Each case is stored with empty `mapped_ac_ids`, empty `type`, empty `last_result`, and empty `linked_bug_ids`. The loader then copies the case description, the step text, the parameters, and any shared-step text the case points at.

Bugs are the Bug work items related to the story. Priority 1–4 is stored as P1–P4. `Custom.Environment` is `found_in`. Description and repro steps are copied for the report. They are not sent to the coverage model. Bugs that hang only off a child Task, a Test Case, or a failed result are not loaded.

Nothing is written back to Azure DevOps.

## How a sprint is evaluated

A sprint is an Azure DevOps iteration path, matched exactly on `System.IterationPath`. The query is read-only WIQL for work items whose type is User Story, ordered by id.

`generate --sprint "<path>" --live` resolves those ids, then runs the live story pipeline above once per id. Each story gets `artifacts/<story-id>.md` and `artifacts/<story-id>.pdf`. A run of two or more stories also writes `artifacts/rollup.pdf`. Page one lists only the stories in that run. A story that fails is marked skipped on that page and has no PDF of its own. There is still no single sprint score and no combined coverage percent. Stories run one after another. The command exits 1 if any story fails.

`generate --sprint "<path>"` without `--live` still calls the live reviewer, but the fetch is different:

- Stories come from the same iteration query.
- Linked work is limited to `System.LinkTypes.*` and Tested By.
- Only Test Cases reached by Tested By are kept, and only when that case belongs to a test plan.
- The Acceptance Criteria field is left as an empty list. Criteria are parsed from the description only.
- Those cases do not carry suite id, description, parameters, or step text into the reviewer. Steps are stored as action and expected-result pairs, and the reviewer reads only string fields, so the model sees the title and any source type. It does not see the step text on this path.
- The model therefore judges description scenarios against those plan-member titles, not the Acceptance Criteria field and not the full case text.

`sprints` prints iteration paths. `list-stories --iteration-path` prints the story ids and titles. Neither judges coverage.

## Which acceptance criteria are judged

Live `--story-id` and live `--sprint` parse both Azure DevOps HTML fields in `graph._criteria_from_text`.

A criterion starts only on a line that begins with `Scenario:`. `Expected:` or `Expected result:` is the expected result. Other lines under that scenario are kept as part of the text. An `AC-01` label at the start of the scenario title is kept as `ac_id`. A scenario with no label is numbered `AC-1`, `AC-2`, and so on. The criterion is marked testable only when an Expected line was captured. Free text, bullets, numbered lists, tables, and Gherkin that has no `Scenario:` line produce no criterion.

The reviewer then walks:

1. Every item in the Acceptance Criteria field, when that list is non-empty. If the field is empty, the description scenarios are the scored list instead.
2. Any description scenario whose text is not already contained in one of those criteria. A repeated sentence is not judged twice. An `AC-01` label inside a description title does not, by itself, map a test.

Long text is not dropped. The criterion, the description, and each test are split into 1200-character parts. Test parts are packed so one call stays near 12000 characters of suite text. Every combination of criterion part, description part, and suite batch is a separate call. The description is context for the criterion. The model is told not to map a test for behavior the criterion does not require.

## What the code keeps after the model answers

Python unions the answers. The model's `coverage_status` is stored on the row as `model_coverage_status`. It does not set the printed status or the percent.

For each criterion the code:

1. Keeps a mapped id only when that test was fetched.
2. Keeps one path label per criterion and test. Votes across parts are counted. A tie prefers negative, then adhoc, then happy. The same test can be happy for AC-01 and negative for AC-02.
3. Fills a missing label from the source type, then from a `-P` / `-N` / `-A` title token, then from the test text. Words such as invalid, failed, empty, or injection infer negative. Words such as whitespace, keyboard, refresh, or length infer adhoc. Anything else infers happy.
4. Adds a further negative or adhoc case when the model has already linked this criterion, the extra case has an N or A title token, and it shares a distinctive word with the criterion or with a test already linked. A word is not distinctive when it appears more than twice and in at least half the suite. A word that appears once or twice still counts. Stop words such as user, button, field, page, and click never count. The prompt also tells the model that a generic word such as "login" is not enough on its own. `login` and `password` are not in the code stop list. They drop out only when they are common across the suite.
5. When the criterion itself expects a failure, and at least two linked cases are negative, and none is happy, one of those negative cases is relabeled happy. Another failure-path case stays negative. The promoted case is the one that shares the most distinctive words with the criterion.

AC quality is merged separately. Across batches the stricter status wins: poor over needs improvement over good. A `good` result clears its issues. Quality does not change the coverage percent. A criterion that is `needs_improvement` or `poor` gets a Product Owner action. The code fallback, used only when the model omits a valid quality object, is poor for empty text, good when the text has an observable result, and needs improvement otherwise.

## How test coverage is calculated

Coverage is three buckets per acceptance criterion: Positive, Negative, and Adhoc. `happy` and `positive` fill Positive. `negative` fills Negative. `adhoc` fills Adhoc. `edge`, `security`, and an empty type fill nothing unless the live reviewer has already mapped them onto happy, negative, or adhoc.

`coverage_row` in `src/story_guard/score.py` sets the row:

| Mapped tests | Buckets present | Row status | Gap |
| --- | --- | --- | --- |
| None | 0 | `none` | No coverage |
| One or more | 1 or 2 | `partial` | One line per missing bucket |
| One or more | All three | `adequate` | Adequate |

One extra rule can pull an adequate or partial row back to partial: if the criterion text says the email remains, and no mapped test text says "remain" or "retained", the gap adds "No test checks that the entered email remains in the field".

The PDF label **Avg Test Case Coverage** is not a test-count ratio and not a value the model returns. `report_layout._coverage_label` sums `buckets_present` across the criteria and divides by three buckets per criterion. The percent is rounded half up:

```text
points = sum of buckets_present
denom  = number of criteria × 3
percent = (points × 100 + denom // 2) // denom
```

Zero criteria print `n/a`. A stored model percent is removed before render, so a reply such as 99% is never printed.

Examples:

- 12 criteria and 15 filled buckets is 15 / 36, which rounds to 42%.
- 2 criteria, one with two buckets and one with none, is 2 / 6, which rounds to 33%.
- One criterion with all three buckets is 100%, and its row status is adequate.
- A criterion with tests but only a Negative bucket is partial. It contributes 1/3, not 100%.

Mapped count is the number of criterion-to-test links, so one test linked to two criteria counts twice. That count is not the coverage percent.

The coverage RAG is separate from both the percent and story health:

- Red when every row is `none`
- Amber when any row is not adequate
- Green when every row is adequate
- Unavailable when there are no criteria

## What does not come from the model

Story health is SR-2 in `score.py`. It is the highest open bug. Open means the status does not contain resolved, closed, rejected, or unable to reproduce. "Rejected / Unable to Reproduce" is closed and counts in the Unable to Reproduce KPI.

| Highest open bug | Health | Band |
| --- | --- | --- |
| P1 | Critical | At Risk |
| P2 | High | At Risk |
| P3 | Medium | Healthy |
| P4 | Low | Healthy |
| Open bug with no P1–P4 | Open bugs, priority unset | Open bugs, priority unset |
| No open bug | No open bugs | No open bugs |

Coverage does not change health. Zero tests with no open bugs is still "No open bugs". Closed bugs stay on the bug table.

The headline names the highest open bugs. Observations start with `Story health - {health}`, then the criterion counts, the test and mapped counts, and the open-bug count. Actions are one Dev action per open bug, one QA action per criterion that is not adequate, and one Product Owner action per criterion whose quality is not good.

The offline fixture score does not use this reviewer. `story-guard score --story-id 121213` applies SR-1, SR-2, and SR-3 to `fixtures/FIX-121213.json`: a test covers a criterion only when `mapped_ac_ids` contains that `ac_id`. The fixture leaves every list empty, so the eight scenarios are `none` and coverage is 0%.
