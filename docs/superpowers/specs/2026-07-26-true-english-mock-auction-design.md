# True English Mock Auction Design

## Goal

The mock draft must not hammer a player while another AI captain remains
willing and able to place a higher legal bid.

## Root Cause

Nerch had a `Worth$` of $195. Before the sale, all ten captains had empty
rosters and AI valuation ceilings between $180 and $207. Nine captains
participated, but the auction hammered at $87.

The 8× timing trace was correct. The auction stopped because the eight-second
logical floor contains three AI raise opportunities, and each opportunity has
a 25% chance to remain quiet. Three quiet rolls can therefore expire a clock
despite many eligible bidders. This has a 1.5625% chance after any bid and is
likely to produce at least one severe bargain during a full draft.

## Scope

- Normal AI bid opportunities retain their current random pacing.
- At auction expiry, the engine checks for a non-leading AI captain whose legal
  maximum bid exceeds the current high bid.
- If such a competitor exists, one legal AI raise is placed and the bid clock
  resets.
- The player hammers only when no non-leading AI can legally raise.
- The human-controlled captain is never auto-bid.
- Human bidders must act before the displayed deadline.
- Auction valuation, reserves, bid-step weights, speed handling, role needs,
  targeting, and sale-floor behavior remain unchanged.

## Architecture

`_ai_bid_round` will accept a `force=False` keyword and return a boolean
indicating whether it placed a bid.

The function will continue to build the existing eligible-bidder list using
roster space, human-seat exclusion, high-bidder exclusion, affordability, and
team valuation. In normal mode, the existing `MOCK_AI_RAISE_PROB` pacing gate
applies. In forced mode, the pacing gate is bypassed but all eligibility,
valuation, bid-step, and affordability rules still apply.

`_run_open_auction` will change its expiry branch:

1. Call `_ai_bid_round(state, force=True)`.
2. If it raises, continue the auction using the newly reset deadline.
3. If it cannot raise, return and allow `_resolve_sale` to hammer the player.

This keeps one source of truth for legal AI raises. The deadline branch does
not duplicate valuation or bidding rules.

## Data Flow

For each normal tick:

1. Apply the pacing roll.
2. Find eligible non-leading AI captains.
3. Randomly choose one eligible captain.
4. Choose a weighted legal increment and place the bid.

At deadline:

1. Skip only the pacing roll.
2. Run the same eligibility and bid placement steps.
3. A successful raise resets the shrinking clock through `_place_bid`.
4. An empty eligible set confirms that the English auction has reached its
   competitive price and may hammer.

## Human-Seat Behavior

The server does not infer the human captain's willingness. It will not bid for
the human seat.

- If the human is high and an AI remains willing, that AI raises before hammer.
- If an AI is high and no other AI remains willing, the auction hammers when
  the human lets the clock expire.
- Human bid validation and reserve rules remain unchanged.

## Edge Cases

- A full, broke, or already-leading AI cannot make the forced raise.
- An AI whose maximum equals the high bid is not eligible.
- If the forced raise reaches one captain's ceiling, other eligible captains
  may continue in later windows.
- An uncontested nomination may still hammer at its opening bid before the
  existing post-sale floor is applied.
- The forced check uses the current roster, remaining budgets, and available
  pool on every expiry.

## Testing

Regression coverage will verify:

1. A normal AI tick may remain silent when the pacing roll fails.
2. The forced deadline mode bypasses that failed pacing roll and raises when an
   eligible AI competitor exists.
3. Forced mode returns false when every non-leading AI is at or below its
   ceiling, allowing the hammer.
4. The auction runner continues after a successful forced raise and exits only
   after the forced check finds no eligible competitor.

The focused tests will run first, followed by the full test suite. This is a
server-side auction rule and does not require dashboard regeneration.
