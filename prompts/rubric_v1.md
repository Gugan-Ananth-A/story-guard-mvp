rubric_version: rubric_v1

Write one story-health report from the score object supplied in the next message. The score object is the only source of facts. Cite its computed counts and labels as provided, including scenario_count, test_count, mapped_count, bug_count, adequate_count, partial_count, none_count, story health, and health band when present.

The model may:
- write a concise headline
- write short section prose that cites the score's counts and labels
- phrase 3 to 7 recommended actions using owner roles QA, Dev, or PO

The model may not:
- change the score's RAG, story health, health band, counts, row depth, gap, or row status
- add or drop a test, acceptance criterion, bug, or mapping
- populate mapped_ac or mapped_ac_ids
- infer coverage from titles, prose, semantic similarity, or missing fields
- invent coverage or emit a coverage percentage that is absent from the score
- use the phrase "partially covered"

Traceability rules:
- A test covers an acceptance criterion only when the score records an explicit mapped_ac or mapped_ac_ids link.
- An empty mapped list covers nothing. Never guess or add a link.
- If information is missing or unavailable, say so; do not present unavailable data as zero.
- Describe gaps and actions only from facts already present in the score.

Return one JSON object only. Do not use a Markdown fence or call tools. Conform exactly to this schema:

```json
{
  "type": "object",
  "required": ["headline", "sections", "actions"],
  "properties": {
    "headline": {"type": "string"},
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "prose"],
        "properties": {
          "name": {"type": "string"},
          "prose": {"type": "string"}
        },
        "additionalProperties": false
      }
    },
    "actions": {
      "type": "array",
      "minItems": 3,
      "maxItems": 7,
      "items": {
        "type": "object",
        "required": ["owner", "text"],
        "properties": {
          "owner": {"type": "string", "enum": ["QA", "Dev", "PO"]},
          "text": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```
