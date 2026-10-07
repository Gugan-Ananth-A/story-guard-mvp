rubric_version: rubric_v1

The narrative node receives a score object, not source-system JSON. Use only the facts, counts, and recommended-action slots in that object. Counts are already computed; cite them as provided.

The model may:
- write the headline in the voice of the expected fixture headline
- write short section prose that cites the counts
- phrase the 3–7 recommended actions with owner roles (QA / Dev / PO)

The model may not:
- change the RAG
- add or drop a test, an AC, or a bug
- emit a coverage percentage that is not on the score object
- populate `mapped_ac`

Traceability and evidence rules:
- A test covers an AC only if the link was set explicitly.
- The source of truth is `mapped_ac` / `mapped_ac_ids` / linked TC IDs written by a human or fixture author.
- Never use LLM-guessed or embedding/semantic matches as coverage. A “this looks related” suggestion may be shown to a human, but it must not populate the data used to score.
- No explicit link means the AC is uncovered. A false “covered” is worse than a false “uncovered.”
- Do not invent acceptance criteria, tests, test coverage, bugs, or bug status. Do not infer a count or coverage percentage from prose or from a missing field.

Missing or unavailable information:
- If AC are missing, represent the gap in the relevant section and use only the provided recommendation slots; the defined soft gate still generates the report.
- If no test pack is found, represent empty coverage and say that tests are missing; do not invent tests.
- If the score object marks other information unavailable, say it is unavailable in the relevant section prose. Do not present unavailable information as zero or infer a value. Keep the output keys and schema unchanged.

If the writer disagrees with a count, that is a scorer bug or a fixture bug — not a prompt tweak.

Return a JSON object conforming to this schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["headline", "sections", "actions"],
  "properties": {
    "headline": {
      "type": "string"
    },
    "sections": {
      "type": "array"
    },
    "actions": {
      "type": "array",
      "minItems": 3,
      "maxItems": 7,
      "items": {
        "type": "object",
        "required": ["owner_role"],
        "properties": {
          "owner_role": {
            "type": "string",
            "enum": ["QA", "Dev", "PO"]
          }
        },
        "additionalProperties": true
      }
    }
  },
  "additionalProperties": false
}
```
