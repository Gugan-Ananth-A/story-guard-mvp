# Story health stand-in

TBD-HEALTH-1 is still open. SR-1, SR-2, and SR-3 are the sprint stand-in, not the published RAG rule.

The stand-in follows the single-story parts of `Story_Guard_Report_2_Banking.pdf` (`docs/requirements.md` §7.1 and §10). It is not a portfolio report.

## SR-1

A scenario is covered only when some test lists its `ac_id` in `mapped_ac_ids`. An empty list covers nothing. This is `docs/requirements.md` §6.4 applied to the fixture.

## SR-2

Story health is the highest open bug priority. An open bug is one whose status is not Resolved, Closed, Rejected, or Unable to Reproduce.

- An open P1 sets health to Critical and the band to At Risk.
- Otherwise an open P2 sets health to High and the band to At Risk.
- Otherwise an open P3 sets health to Medium and the band to Healthy.
- Otherwise an open P4 sets health to Low and the band to Healthy.
- When no bug is open, health is No open bugs. That is not Critical, High, Medium, Low, or Red.

Coverage does not change this health. SR-2 is why 121213 is No open bugs.

## SR-3

Each scenario row is Adequate, Partial, or None from the types of its mapped tests. Positive, Negative, and Adhoc are the three types that count. `happy` prints as Positive. `edge` and `security` do not fill those three.

- Adequate when Positive, Negative, and Adhoc are all present.
- Partial when at least one test is mapped and the row is not Adequate.
- None when no test is mapped. Depth is None and the gap is No coverage.

The row does not say "partially covered". That phrase is not computed. SR-3 is why 121213 has 8 rows at None, 0 Adequate, and 0 Partial.
