# Speed-Invariant Mock Bidding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve AI bidding opportunities and sale-price behavior when mock-draft speed changes during an active auction.

**Architecture:** Add a private timing-change event to `MockState` and signal it from `set_speed`. Replace the single precomputed AI sleep with a helper that tracks the unfinished interval in logical 1× seconds, wakes on speed changes, and recalculates against the new speed.

**Tech Stack:** Python 3, `threading.Event`, `time.monotonic`, standard-library `unittest`.

## Global Constraints

- Work inline on `main`.
- Do not modify auction valuation, bidder selection, bid steps, clock shrink, or sale floors.
- Keep stop/reset response latency at or below 100 milliseconds.
- Do not modify or stage the user's `captains.json`.

---

### Task 1: Reproduce the Mid-Wait Speed Race

**Files:**
- Modify: `tests/test_regressions.py`

**Interfaces:**
- Consumes: `MockState._open_auction`, `MockState.set_speed`, and `_run_open_auction`.
- Produces: a deterministic regression proving a mid-wait 1×→8× transition offers as many AI bidding rounds as an auction that starts at 8×.

- [ ] **Step 1: Import the auction runner**

Change the mockdraft import to:

```python
from scout.mockdraft import (
    MockState,
    _next_nominator,
    _resolve_sale,
    _run_open_auction,
)
```

- [ ] **Step 2: Add the controlled-clock regression**

Add the following method to `MockAuctionTests`:

```python
def test_speed_change_during_ai_wait_preserves_bid_opportunities(self):
    from scout import mockdraft

    class Clock:
        now = 100.0

        @classmethod
        def advance(cls, seconds):
            cls.now += seconds

    class Switch:
        changed = False

    class FakeStop:
        def __init__(self, state, switch):
            self.state = state
            self.switch = switch

        def is_set(self):
            return False

        def wait(self, seconds):
            if self.switch and not Switch.changed:
                Switch.changed = True
                self.state.set_speed(8)
            Clock.advance(seconds)
            return False

    class FakeTimingEvent:
        def __init__(self, state, switch):
            self.state = state
            self.switch = switch
            self.pending = False

        def clear(self):
            self.pending = False

        def set(self):
            self.pending = True

        def wait(self, timeout):
            if self.switch and not Switch.changed:
                Clock.advance(min(0.05, timeout))
                Switch.changed = True
                self.state.set_speed(8)
                return True
            Clock.advance(timeout)
            return self.pending

    def opportunities(switch):
        Clock.now = 100.0
        Switch.changed = False
        state = MockState(
            53,
            "S22",
            [self.player(worth=100)],
            [
                {"captain": "A", "budget": 500, "team_id": "1", "pos": [1]},
                {"captain": "B", "budget": 500, "team_id": "2", "pos": [2]},
            ],
            {},
            "A",
        )
        state._timing_changed = FakeTimingEvent(state, switch)
        stop = FakeStop(state, switch)
        rounds = []
        with mock.patch.object(
            mockdraft.time, "time", side_effect=lambda: Clock.now
        ), mock.patch.object(
            mockdraft.time, "monotonic", side_effect=lambda: Clock.now
        ), mock.patch.object(
            mockdraft,
            "_ai_bid_round",
            side_effect=lambda current: rounds.append(Clock.now),
        ):
            if not switch:
                state.set_speed(8)
            state._open_auction(state.pool[10], 1, "A")
            _run_open_auction(state, stop)
        return len(rounds)

    self.assertEqual(opportunities(switch=False), 6)
    self.assertEqual(opportunities(switch=True), 6)
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_speed_change_during_ai_wait_preserves_bid_opportunities -v
```

Expected: FAIL because the mid-wait transition yields one opportunity instead
of six.

### Task 2: Interrupt and Rescale AI Waits

**Files:**
- Modify: `scout/mockdraft.py:618-629`
- Modify: `scout/mockdraft.py:842-884`
- Modify: `scout/mockdraft.py:1097-1111`

**Interfaces:**
- Produces: `MockState._timing_changed: threading.Event`.
- Produces: `_wait_scaled_interval(state, stop, seconds) -> bool`.
- `True` means the full logical interval elapsed; `False` means stop, reset, or pause interrupted it.

- [ ] **Step 1: Add the timing-change event**

After initializing `self.speed`, add:

```python
self._timing_changed = threading.Event()
```

- [ ] **Step 2: Signal successful speed changes**

Inside the locked successful-change path of `set_speed`, immediately after
assigning `self.speed`, add:

```python
self._timing_changed.set()
```

- [ ] **Step 3: Add the logical interval helper**

Add before `_run_open_auction`:

```python
def _wait_scaled_interval(state, stop, seconds):
    """Wait `seconds` of logical 1× time, adapting to live speed changes."""
    remaining = max(0.0, float(seconds))
    while remaining > 1e-9:
        if stop.is_set() or state.reset_flag.is_set() or state.paused.is_set():
            return False
        with state._lock:
            state._timing_changed.clear()
            speed = state.speed
        started = time.monotonic()
        timeout = min(remaining / speed, 0.1)
        state._timing_changed.wait(timeout)
        elapsed = max(0.0, time.monotonic() - started)
        remaining = max(0.0, remaining - elapsed * speed)
    return True
```

Clearing the event and reading `speed` under the state lock prevents a speed
signal from being lost between those operations.

- [ ] **Step 4: Use the helper between AI bid rounds**

Replace:

```python
stop.wait(state.scale(config.MOCK_AI_TICK))
```

with:

```python
_wait_scaled_interval(state, stop, config.MOCK_AI_TICK)
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_speed_change_during_ai_wait_preserves_bid_opportunities -v
```

Expected: PASS with six opportunities in both cases.

### Task 3: Verify and Commit

**Files:**
- Modify: `README.md:264-273`
- Add: `docs/superpowers/plans/2026-07-26-speed-invariant-mock-bidding.md`

**Interfaces:**
- Documents that speed changes preserve bidding behavior.

- [ ] **Step 1: Update the mock-speed documentation**

Extend the fast-forward description with:

```markdown
Changing speed during an auction preserves the same AI bidding opportunities;
it changes elapsed time, not expected sale prices.
```

- [ ] **Step 2: Run the focused regression**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_speed_change_during_ai_wait_preserves_bid_opportunities -v
```

Expected: 1 test passes.

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 4: Review the diff**

Run:

```powershell
git diff --check
git status --short
git diff -- scout/mockdraft.py tests/test_regressions.py README.md
```

Expected: no whitespace errors; only planned tracked files plus the user's
pre-existing `captains.json` modification.

- [ ] **Step 5: Commit the implementation**

Run:

```powershell
git add -- scout/mockdraft.py tests/test_regressions.py README.md docs/superpowers/plans/2026-07-26-speed-invariant-mock-bidding.md
git commit -m "Preserve mock bidding at fast speeds"
```

Do not stage `captains.json`.
