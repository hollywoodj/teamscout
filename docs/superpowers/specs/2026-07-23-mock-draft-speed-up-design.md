# Mock draft speed-up — design

Date: 2026-07-23

## Problem

A mock draft runs in real time: ~15s of bidding per player, ~3.5s before each AI
nomination, across a pool of a hundred-odd players. Most of that is dead air —
the user only cares about the players still on their list. There is no way to
skip ahead to the next player worth bidding on.

## Goal

A speed dial that compresses the auction, plus an automatic brake that drops
back to 1x the moment a player the user still wants comes up for nomination.

"Still wants" is defined by inversion: the dashboard already has a per-player
**✕ cut** mark ("don't want to play with", `report_html.py:885`). The user
swipes through the board cutting people. Whoever is left uncut is who they want
to bid on. So the brake fires on **any player not marked ✕**.

Note that ✕ cut is a different mark from ⊘ removed. ⊘ takes a player out of the
auction pool entirely (`removed` in captains.json) — they are never nominated.
✕ keeps them fully draftable; it only says the user isn't interested. That
distinction is what makes ✕ the right signal here: cut players still come up for
auction, the fast-forward just doesn't brake for them.

## Non-goals

- No clockless "instant" simulation mode. The dial tops out at 8x and every
  auction still animates, so the user can jump into any bid war they pass.
- No new marking UI. The ✕ list already exists and is already maintained.
- No change to how ⊘ removed behaves.

## Design

### 1. Speed as a divisor on timed windows

`MockState` gains `self.speed` (float, default 1.0), guarded by the existing
`self._lock`. Every duration the engine sleeps on is divided by it:

| Constant | Used in |
|---|---|
| `MOCK_NOMINATION_SECONDS` | `_open_auction` |
| `MOCK_NOMINATION_SECONDS - bid_count`, floor `MOCK_BID_SECONDS_FLOOR` | `_place_bid` |
| `MOCK_AI_NOMINATE_DELAY` | `_run_draft` |
| `MOCK_AI_TICK` | `_run_open_auction` |
| `MOCK_START_COUNTDOWN` | `_countdown` |
| the 0.6s sold beat | `_run_draft` |

A single helper (`state.scale(seconds)`) does the division so the call sites stay
readable and there is one place to clamp.

**Scaling the AI tick and the bid window together is the core requirement.** The
ratio `MOCK_AI_TICK / window` determines how many AI raises land before the
hammer. Preserving that ratio means the expected number of raises per auction is
unchanged, so **players sell for the same price at 8x as at 1x**. A speed dial
that moved final prices would invalidate the mock as bidding practice, which is
the entire point of the tool.

At 8x the numbers stay sane: AI tick 0.31s, opening window 1.9s, floor 1.0s.

`self.window` already drives `bid_ms` on emitted events and `window_ms` in the
snapshot, so the dashboard countdown inherits the compression with no extra
plumbing.

### 2. Changing speed mid-window

`set_speed(new)` rescales the **remaining** time rather than restarting the
window:

```
rem_new = (deadline - now) * (old_speed / new_speed)
deadline = now + rem_new
window   = rem_new
```

So hitting 8x during a slow bid war compresses it immediately instead of waiting
for the next player.

The change is broadcast as a `speed` event carrying `bid_ms` (the new remaining
time) and `measured_at_ms`, mirroring exactly what `resume()` already does on the
`pause` event (`mockdraft.py:840-861`). The client updates `lastNom.bid_ms` /
`measured_at_ms` / `ts` and re-renders, same as its existing pause-resume branch
(`report_html.py:2312-2324`). `speed` is not added to `FEED_KINDS`, so it drives
the clock without spamming the feed.

Interaction with pause: while paused, `_paused_hold` pins the deadline and
`_paused_remaining` holds the frozen time. `set_speed` while paused rescales
`_paused_remaining` instead of `deadline`, so resume picks up the compressed
remainder.

### 3. Cut-list sync

The ✕ list lives in browser localStorage under `ld2l-excluded-s{SEASON}`
(`report_html.py:851-854`); the server has never seen it. The brake needs it
server-side so it can fire at nomination time, before the auction window opens.

- New endpoint `POST /mock/cuts` with body `{cuts: [steam32, ...]}` →
  `state.set_cuts(set_of_int)`.
- The client pushes from `saveExcluded()` (`report_html.py:854`) — the single
  choke point every ✕ mutation already routes through — guarded so it only fires
  when the mock is active.
- One additional push when the mock bar first appears (`applyMock`), so a page
  reload or a fresh browser resyncs the list.

localStorage remains the source of truth. The server holds a transient copy used
only for braking; nothing is persisted server-side and captains.json is
untouched.

Failure mode: if the sync has not landed (server-side set is empty), the brake
fires on the very next nomination. That is the safe direction — the user stops
too early rather than blowing past someone they wanted.

### 4. The brake

In `_ai_nominate`, after the AI selects `pick` and **before** `_open_auction`:

```
if state.speed > 1 and pick["steam32"] not in state.cuts:
    state.set_speed(1.0)
    state.add_event("status", text=f"⏩ stopped — {pick['name']} is up")
```

Ordering is the important part. Resetting speed first means `_open_auction`
computes a full-length 15s window, so the user gets the whole clock to react
rather than the 1.9s tail of a compressed one.

`_ai_nominate` already runs inside `with state._lock`, and `set_speed` acquires
the same lock. That is safe only because `_lock` is an `RLock`
(`mockdraft.py:551`) — it must stay one.

The brake also fires when the round-robin reaches the user's own seat, in
`_run_draft` where `is_me` is already computed. The engine blocks on
`human_nominated` there regardless, so nothing is being skipped — but without the
reset, the auction the user then opens would run compressed.

Per the approved behavior, the brake is **sticky**: speed stays at 1x until the
user moves the dial again. After winning or losing a player they cared about,
they want to look at their roster and budget, not have the room start racing.

### 5. UI

A `<select id="mb-speed">` with 1x / 2x / 4x / 8x, placed next to the Pause
button in the mock bar (`report_html.py:626-630`). Changing it POSTs
`/mock/speed {x: <float>}`.

`speed` is added to the `mock` sub-object in `live_snapshot`, and `renderMockBar`
syncs the select's value from it — so when the brake fires, the dial visibly
snaps back to 1x rather than lying about the current tempo.

When `speed > 1` the status line appends `⏩ 4x`, consistent with how it already
appends `⏸ paused`.

The select is visible in every phase, including `setup`, so a speed can be
chosen before pressing Start.

### 6. Defect this exposes

`report_html.py:2284` hardcodes `bid_ms: 15000` on incoming `nominate` events
("nominations always start at 15s"), discarding the value the server sends. At 8x
the displayed countdown would start from 15s while the real window is 1.9s,
hammering while the clock still reads ~13s.

Fix: `bid_ms: ev.bid_ms ?? 15000`. The server already sets `bid_ms` on every
nominate/bid event via `add_event`'s `setdefault` (`mockdraft.py:622-623`), so
the fallback only applies to the real `--live` follower path, where 15s is
correct.

## Config

```python
MOCK_SPEEDS = (1, 2, 4, 8)   # dial notches offered in the UI
MOCK_MAX_SPEED = 8           # server-side clamp on /mock/speed
```

`set_speed` clamps to `[1.0, MOCK_MAX_SPEED]` so a hand-crafted POST cannot drive
a sleep interval to zero and spin the engine thread.

## Testing

- **Price fidelity** — the property that justifies the whole approach. Run the
  same seeded draft at 1x and at 8x; final prices and roster assignments must
  match. This is the regression that matters most.
- **Brake timing** — with a cut list covering all but one player, the auction
  that opens for the uncut player must have a full `MOCK_NOMINATION_SECONDS`
  window and `speed == 1.0`.
- **Brake on own turn** — reaching the user's seat at 4x leaves speed at 1.0
  before `human_nominate` is accepted.
- **Mid-window rescale** — `set_speed` during a live bid halves/doubles the
  remaining time without resetting it, and the emitted `speed` event carries the
  matching `bid_ms`.
- **Pause interaction** — speed change while paused survives resume with the
  correct compressed remainder.
- **Clamp** — `POST /mock/speed {x: 0}` and `{x: 999}` are clamped, not applied.
- **Empty cut list** — brake fires on the first nomination rather than never.

## Files touched

- `scout/config.py` — `MOCK_SPEEDS`, `MOCK_MAX_SPEED`
- `scout/mockdraft.py` — `MockState.speed` / `scale` / `set_speed` / `set_cuts`,
  scaled sleeps in `_run_draft` / `_run_open_auction` / `_countdown`, brake in
  `_ai_nominate` and `_run_draft`, `speed` in `live_snapshot`, `/mock/speed` and
  `/mock/cuts` handlers, `speed` reset in `_reset_state`
- `scout/report_html.py` — `#mb-speed` select + handler, `renderMockBar` sync,
  status line, `saveExcluded` push, `applyMock` push, `speed` SSE branch, the
  `bid_ms` fix at line 2284
