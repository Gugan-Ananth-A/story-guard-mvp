# RAG stand-in

TBD-HEALTH-1 is still open. SR-1 and SR-2 are the sprint stand-in, not the published RAG rule.

## SR-1

A scenario is covered only when some test lists its `ac_id` in `mapped_ac_ids`. An empty list covers nothing. This is `docs/requirements.md` §6.4 applied to the fixture.

## SR-2

When the story has one or more description scenarios and the mapped count is 0, the overall RAG is Red. SR-2 is why 121213 is Red.
