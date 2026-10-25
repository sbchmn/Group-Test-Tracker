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
Legacy groups with no recorded calculation retain the existing historical-data
notice rather than displaying reconstructed prices.

Pricing and assigned-charge logic are unchanged.

Validation:

```powershell
python -m pytest tests/test_cost_policy.py tests/test_lab_costs.py -q --disable-warnings --maxfail=1
```

Result: **33 tests and 2 subtests passed** (`tests.txt`). Tests verify the rendered
equations on both pages after live inputs diverge from the frozen snapshot, and
check empty/no-donor/all-donor cases. `git diff --check` passed.

`check_responsive.py` checks three views at 320, 390, 820, 1024, 1280, and 1440px
in both themes: **36 checks passed**. It verifies that the section initially starts
collapsed, opens correctly, and does not overflow. Data is temporary. Generated
screenshots stay local under the repository's review-PNG ignore rule; scripts and
text reports are retained.
