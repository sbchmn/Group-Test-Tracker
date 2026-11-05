# Detailed cost explanation — 2026-10-24

Restored the step-by-step explanation from the group detail template before
`17c1da8`, keeping the current collapsed **How the split works** section. The shared
partial also supplies the explanation on Manage Participants.

The explanation shows lab and shipping inputs, the fixed total, division across
the cost-sharing roster, donor refund pool, non-donor uplift, and each role's final
share. Donor-shipping credits are shown separately in the donor equation. Frozen
groups use snapshot inputs/counts; current edits cannot rewrite their explanation.
Late buy-ins remain separate. Empty rosters, no donors, all donors, credits below
zero, and cent rounding receive appropriate wording without division by zero.
Older groups also show the full explanation. When no original breakdown was
recorded, `costs.explanation_costs` supplies read-only arithmetic from the test's
current costs and original cost-sharing participants. The explanation identifies
that basis and keeps recorded individual charges separate. Displaying the math
does not create a snapshot or reprice anyone.

Members approved after costs freeze are visibly tagged **Additional member** in
the participant lists, member dashboard, and personal test status. Pricing controls
and review screens use the same terminology. The cost summary states that these
members have separate buy-ins and do not enter the original participant count,
base split, or donor refund calculation. Additional vial donors also remain outside
the original donor counts; their separately assigned buy-in is preserved.

Pricing and assigned-charge logic are unchanged.

Validation:

```powershell
python -m pytest tests/test_cost_policy.py tests/test_lab_costs.py -q --disable-warnings --maxfail=1
```

Result: **33 tests and 2 subtests passed** (`tests.txt`). Tests verify the rendered
equations on both pages after live inputs diverge from the frozen snapshot, and
check empty/no-donor/all-donor cases. `git diff --check` passed.

Follow-up checks for older groups passed **35 tests and 4 subtests**
(`older-group-tests.txt`). One initial follow-up run failed because pre-existing
test assertions were accidentally placed in the new legacy fixture's test method;
correcting their placement resolved the fixture failure.

The final cost/lab/participant-removal command passed **49 tests and 6 subtests**
(`additional-member-tests.txt`):

```powershell
python -m pytest tests/test_cost_policy.py tests/test_lab_costs.py tests/test_participant_removal.py -q --disable-warnings --maxfail=1
```

It includes an eight-member Ready for Payment group with one vial donor, recorded
and missing older snapshots, unchanged assigned charges, additional-member badges
on both participant pages, member-facing status, and exclusion of additional vial
donors from the original base/refund math.

`check_responsive.py` now checks five views at 320, 390, 820, 1024, 1280, and 1440px
in both themes: **60 checks passed**. It verifies that the section initially starts
collapsed, opens correctly, and does not overflow. Data is temporary. Generated
screenshots stay local under the repository's review-PNG ignore rule; scripts and
text reports are retained. Browser fixtures include the one-member group, the
eight-member/one-donor older group, and additional members approved after freezing;
their badges appear while the eight-member original base remains unchanged.
