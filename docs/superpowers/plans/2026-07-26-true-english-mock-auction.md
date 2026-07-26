# True English Mock Auction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent mock auctions from hammering while a non-leading AI captain can legally place a higher bid.

**Architecture:** Extend the existing `_ai_bid_round` path with a forced mode that bypasses only the random pacing gate and reports whether it raised. At deadline, `_run_open_auction` uses that same legal-bid path once before deciding whether the auction may close.

**Tech Stack:** Python 3, standard-library `unittest`, existing mock auction engine.

## Global Constraints

- Work inline on `main`.
- Never auto-bid for the human-controlled captain.
- Preserve valuation, reserves, bid steps, sale floors, clock shrink, and speed behavior.
- Do not modify or stage the user's `captains.json`.

---

### Task 1: Deadline Competition Regressions

**Files:**
- Modify: `tests/test_regressions.py`

**Interfaces:**
- Consumes: `_ai_bid_round(state, force=False) -> bool`.
- Consumes: `_run_open_auction(state, stop)`.
- Verifies that forced mode bypasses pacing only when an eligible AI competitor exists.

- [ ] **Step 1: Import the AI bid function**

Add `_ai_bid_round` to the grouped `scout.mockdraft` import.

- [ ] **Step 2: Add a three-captain fixture**

Add this helper to `MockAuctionTests`:

```python
def competitive_state(self):
    captains = [
        {"captain": "A", "budget": 500, "team_id": "1", "pos": [2]},
        {"captain": "B", "budget": 500, "team_id": "2", "pos": [3]},
        {"captain": "Me", "budget": 500, "team_id": "3", "pos": [4]},
    ]
    return MockState(
        53, "S22", [self.player(worth=100)], captains, {}, "Me"
    )
```

- [ ] **Step 3: Add the forced-mode regression**

```python
def test_forced_ai_round_bypasses_silence_only_for_eligible_competitor(self):
    state = self.competitive_state()
    player = state.pool[10]
    state._open_auction(player, 1, "A")

    with mock.patch("scout.mockdraft.random.random", return_value=1.0):
        self.assertFalse(_ai_bid_round(state))
        self.assertTrue(_ai_bid_round(state, force=True))

    self.assertEqual(state.high_bidder, "B")
    self.assertGreater(state.high_bid, 1)

    state.teams["A"].budget = 1
    state.high_bidder = "B"
    state.high_bid = state.teams["B"].max_bid(player, list(state.pool.values()))
    self.assertFalse(_ai_bid_round(state, force=True))
```

- [ ] **Step 4: Add the auction-runner regression**

```python
def test_expired_auction_runs_to_competitive_ceiling(self):
    from scout import mockdraft

    state = self.competitive_state()
    player = state.pool[10]
    clock = {"now": 100.0}
    stop = threading.Event()
    competitors = ("A", "B")

    with mock.patch.object(
        mockdraft.time, "time", side_effect=lambda: clock["now"]
    ):
        state._open_auction(player, 1, "A")
        ceilings = [
            state.teams[name].max_bid(player, list(state.pool.values()))
            for name in competitors
        ]
        state.deadline = clock["now"]

        def expire(current, _stop, _seconds):
            clock["now"] = current.deadline
            return True

        with mock.patch.object(
            mockdraft.random, "random", return_value=1.0
        ), mock.patch.object(
            mockdraft.random, "choice", side_effect=lambda eager: eager[0]
        ), mock.patch.object(
            mockdraft.random, "choices", return_value=[25]
        ), mock.patch.object(
            mockdraft, "_wait_scaled_interval", side_effect=expire
        ):
            _run_open_auction(state, stop)

    self.assertGreaterEqual(state.high_bid, min(ceilings))
    self.assertFalse(_ai_bid_round(state, force=True))
```

This exercises the real valuation, eligibility, increment, and deadline-reset
behavior. Only time passage and random selection are controlled.

- [ ] **Step 5: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_forced_ai_round_bypasses_silence_only_for_eligible_competitor tests.test_regressions.MockAuctionTests.test_expired_auction_runs_to_competitive_ceiling -v
```

Expected: FAIL because `_ai_bid_round` has no `force` argument and expired
auctions return without a competition check.

### Task 2: Forced Last-Chance Raise

**Files:**
- Modify: `scout/mockdraft.py:1027-1059`
- Modify: `scout/mockdraft.py:1116-1130`

**Interfaces:**
- Produces: `_ai_bid_round(state, force=False) -> bool`.
- Normal mode may return false due to pacing or eligibility.
- Forced mode bypasses pacing but preserves every legal-bid rule.

- [ ] **Step 1: Return explicit bid outcomes**

Change the function signature and early returns:

```python
def _ai_bid_round(state, force=False):
    with state._lock:
        if state.phase != "bidding" or not state.nominee:
            return False
        if not force and random.random() >= config.MOCK_AI_RAISE_PROB:
            return False
```

Change the empty eager set to `return False`. After a successful
`state._place_bid(...)`, return `True`; otherwise return `False`.

- [ ] **Step 2: Check competition at deadline**

Change the deadline branch in `_run_open_auction` to:

```python
if time.time() >= deadline:
    if _ai_bid_round(state, force=True):
        continue
    return
```

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_forced_ai_round_bypasses_silence_only_for_eligible_competitor tests.test_regressions.MockAuctionTests.test_expired_auction_runs_to_competitive_ceiling -v
```

Expected: both tests pass.

### Task 3: Documentation, Verification, and Commit

**Files:**
- Modify: `README.md:247-273`
- Add: `docs/superpowers/plans/2026-07-26-true-english-mock-auction.md`

**Interfaces:**
- Documents the mock auction's hammer rule.

- [ ] **Step 1: Update the AI drafting documentation**

Add:

```markdown
The clock can pause naturally, but a player cannot hammer while a non-leading
AI captain remains willing and able to raise; expired auctions perform one
last legal AI bid check before closing.
```

- [ ] **Step 2: Run the focused regressions**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_forced_ai_round_bypasses_silence_only_for_eligible_competitor tests.test_regressions.MockAuctionTests.test_expired_auction_runs_to_competitive_ceiling -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Run the full suite**

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
git add -- scout/mockdraft.py tests/test_regressions.py README.md docs/superpowers/plans/2026-07-26-true-english-mock-auction.md
git commit -m "Keep mock auctions open for willing bidders"
```

Do not stage `captains.json`.
