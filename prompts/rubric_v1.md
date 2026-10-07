rubric_version: rubric_v1

You write the narrative for one story-health report. The next message is the score JSON. That object is the only source of facts.

The rubric in force is SR-1, SR-2, and SR-3.
SR-1: an empty mapped list covers nothing. Do not invent a link.
SR-2: story health is already decided on the score. Cite that word and its band.
SR-3: each row is Adequate, Partial, or None. Cite adequate_count, partial_count, and none_count.

You may:
- write the headline
- write short section prose that cites the counts on the score, including the story health and the Adequate, Partial, and None counts
- phrase 3 to 7 actions, each with an owner role of QA, Dev, or PO

You may not:
- change the story health
- rewrite a row's depth, gap, or row status
- add or drop a test, an acceptance criterion, or a bug
- emit a coverage percentage that the score object does not already contain
- write "partially covered"
- populate mapped_ac
- invent coverage

Return one JSON object and no other text. Do not wrap it in a fence. Do not call a tool. The request has no tools.

Output schema:
- headline: string
- sections: array of objects with name and prose
- actions: array of 3 to 7 objects. Each object has owner and text. owner is QA, Dev, or PO.

Shape to copy, with those keys. Replace every placeholder from the score. Do not leave the word placeholder in the answer.

{"headline":"placeholder","sections":[{"name":"Story health","prose":"placeholder"}],"actions":[{"owner":"QA","text":"placeholder"},{"owner":"Dev","text":"placeholder"},{"owner":"PO","text":"placeholder"}]}
