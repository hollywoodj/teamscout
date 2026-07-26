# Speed-Invariant Mock Bidding Design

## Goal

Changing a running mock auction from 1× to 8× must make the auction finish
faster without reducing the number of AI bidding opportunities or causing
players to sell unusually cheaply.

## Root Cause

Bid windows and AI tick intervals are both divided by the selected speed, so
an auction that starts at 8× preserves their ratio. The bug occurs when speed
changes during an existing AI wait:

1. At 1×, the engine begins a 2.5-second AI wait.
2. The user selects 8×.
3. `set_speed` immediately divides the remaining auction deadline by eight.
4. The already-running 2.5-second wait cannot wake or rescale.
5. The compressed deadline expires before another AI bid opportunity.

A controlled clock reproduction produced six AI opportunities when an auction
started at 8×, but only one when it switched from 1× to 8× during the first
wait.

## Scope

- Speed changes during a live mock auction wake the current AI wait.
- The unfinished logical portion of that wait continues at the new speed.
- Starting at 1×, 2×, 4×, or 8× continues to preserve the same expected number
  of bidding opportunities.
- Auction valuation, bidder selection, bid-step weights, sale floors, clock
  shrink rules, pause behavior, and live draft mode remain unchanged.
- Reset and shutdown remain responsive while the helper is waiting.

## Architecture

`MockState` will own a private timing-change event. `set_speed` will signal the
event whenever it successfully changes the speed.

A focused `_wait_scaled_interval(state, stop, seconds)` helper will replace the
single precomputed `stop.wait(state.scale(...))` call used between AI bid
opportunities. The helper tracks the remaining duration in logical 1× seconds.
It waits in bounded real-time slices and wakes immediately on the timing-change
event. Elapsed real time is charged at the speed that was active during that
slice, then the remaining logical duration is recalculated using the new
speed.

The event is cleared while holding the same state lock used by `set_speed`.
This prevents a speed change between clearing the event and reading the active
speed from being lost.

## Data Flow

For a 2.5-second logical AI interval:

- At a constant 1×, 2.5 real seconds elapse.
- At a constant 8×, 0.3125 real seconds elapse.
- If speed changes partway through, time already elapsed is charged at the old
  speed and only the unfinished logical duration is divided by the new speed.

The auction deadline continues to be rescaled immediately by `set_speed`.
Because the AI wait now follows the same transition, the deadline-to-tick ratio
remains stable.

## Edge Cases

- Invalid or unchanged speed values do not signal a timing change.
- Stop or reset ends the helper without waiting for the full logical interval.
- The helper uses monotonic elapsed time so wall-clock adjustments cannot
  create or erase bidding time.
- A bounded wait slice keeps stop/reset latency at or below 100 milliseconds.
- Multiple rapid speed changes are handled by recalculating after every signal.

## Testing

A deterministic regression test will use a controlled clock and wait primitive
to compare:

1. An auction that starts at 8×.
2. An auction that changes from 1× to 8× during its first AI wait.

Both cases must expose the same number of AI bid opportunities before the
auction deadline. The test must fail against the current single-wait behavior,
which produces six opportunities in the first case and one in the second.

The focused test will run first, followed by the complete test suite. This
server-side timing fix does not alter embedded dashboard code, so dashboard
regeneration is not required.
