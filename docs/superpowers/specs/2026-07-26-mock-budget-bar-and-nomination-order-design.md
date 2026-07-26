# Mock Budget Bar and Nomination Order Design

## Goal

Make mock drafts easier to read and start fairly: team budget bars show how
much money remains, and captains with the lowest starting budgets nominate
first.

## Scope

This change applies only to mock draft mode.

- A team's bar is fully blue when its remaining budget equals its starting
  budget.
- The blue width shrinks in proportion to spending.
- At $0 remaining, or below, the bar has no blue fill.
- The mock tooltip and percentage label describe the percentage remaining.
- Captains nominate in ascending order of starting budget.
- Captains with equal starting budgets keep their original website or curated
  roster order.
- Resetting a draft restores budgets and begins again with the same nomination
  order.
- Live draft mode keeps its current spent-budget bar and captain order.

## Architecture

The existing Teams renderer remains shared by live and mock modes. It will
choose the bar calculation and copy from the existing `MOCKMODE` flag:
remaining-budget percentage in mock mode and spent-budget percentage
otherwise. This avoids creating a second dashboard build or duplicate team
card component.

`MockState` will establish nomination order once while building its teams. It
will retain each captain's input position as a stable tie-breaker and sort the
finished order by `Team.start_budget` ascending. The existing round-robin
`_next_nominator` function and reset logic will continue to consume that
order.

## Data Flow

The mock server already exposes every team's `start_budget` and current
`budget`. Draft picks continue to flow through the shared live snapshot. The
Teams renderer derives remaining dollars from starting budget minus recorded
spending, then clamps the visual percentage to the inclusive range 0–100.

Nomination order is derived from the resolved captain rows after website
budgets and `budgets.json` overrides have been applied. It does not change as
money is spent during a draft.

## Edge Cases

- A missing or zero starting budget renders a clear bar and avoids division by
  zero.
- A negative remaining balance renders a clear bar while preserving the
  existing over-budget warning styling.
- Equal budgets preserve source order deterministically.
- Full or unable-to-bid teams are still skipped by the existing nominator
  selection logic.

## Testing

Regression coverage will verify:

1. Mock team cards calculate fill width and copy from remaining budget while
   live cards retain spent-budget semantics.
2. `MockState.order` sorts captains by starting budget ascending.
3. Equal-budget captains retain source order.
4. `_next_nominator` begins with the lowest-budget eligible captain and
   continues using the established order.

The focused regression tests will run first, followed by the full test suite
and dashboard regeneration/build verification.
