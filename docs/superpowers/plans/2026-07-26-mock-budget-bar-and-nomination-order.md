# Mock Budget Bar and Nomination Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mock team budget bars visualize remaining money and make lower-starting-budget captains nominate first.

**Architecture:** Keep the existing shared Teams renderer and isolate its mode-specific math in a small JavaScript `budgetBarState` function. Establish the mock nomination order once in `MockState` by stable-sorting captains on `Team.start_budget`, leaving the existing round-robin and reset machinery unchanged.

**Tech Stack:** Python 3 standard-library `unittest`, embedded browser JavaScript, Node.js for exercising the generated JavaScript helper.

## Global Constraints

- Apply both behavior changes only to mock draft mode.
- Preserve live draft spent-budget bar behavior.
- Sort by resolved starting budget ascending; preserve source order for ties.
- Preserve the same nomination order after reset.
- Do not modify or stage the user's `captains.json`.
- Work inline on `main`, as explicitly requested.

---

### Task 1: Stable Lowest-Budget Nomination Order

**Files:**
- Modify: `tests/test_regressions.py`
- Modify: `scout/mockdraft.py:581-600`

**Interfaces:**
- Consumes: `MockState(..., captains_raw, ...)`, where each captain row has `captain` and `budget`.
- Produces: `MockState.order: list[str]`, sorted by each corresponding `Team.start_budget` ascending and stable for ties.

- [ ] **Step 1: Write the failing test**

Add `_next_nominator` to the test import and add this test to
`MockAuctionTests`:

```python
def test_lowest_starting_budget_nominates_first_with_stable_ties(self):
    captains = [
        {"captain": "High", "budget": 500, "team_id": "1", "pos": [1]},
        {"captain": "Low A", "budget": 200, "team_id": "2", "pos": [2]},
        {"captain": "Low B", "budget": 200, "team_id": "3", "pos": [3]},
        {"captain": "Mid", "budget": 300, "team_id": "4", "pos": [4]},
    ]
    state = MockState(
        53, "S22", [self.player()], captains, {}, "Low A"
    )

    self.assertEqual(state.order, ["Low A", "Low B", "Mid", "High"])
    self.assertEqual(_next_nominator(state), "Low A")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_lowest_starting_budget_nominates_first_with_stable_ties -v
```

Expected: FAIL because `state.order` still follows source order and begins
with `High`.

- [ ] **Step 3: Implement the minimal stable sort**

After all `Team` objects are built in `MockState.__init__`, add:

```python
self.order.sort(key=lambda captain: self.teams[captain].start_budget)
```

Python's stable sort preserves the original relative order of equal-budget
captains.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_lowest_starting_budget_nominates_first_with_stable_ties -v
```

Expected: PASS.

### Task 2: Mock Remaining-Budget Bar

**Files:**
- Modify: `tests/test_regressions.py`
- Modify: `scout/report_html.py:1569-1604`

**Interfaces:**
- Produces: JavaScript `budgetBarState(budget, spent, mockMode)`.
- Returns: `null` for a missing budget, otherwise
  `{left, pct, fillPct, title, percentText}`.
- Consumes: existing `MOCKMODE`, team starting `budget`, and team `spent`.

- [ ] **Step 1: Write the failing JavaScript behavior test**

Add `re`, `shutil`, and `subprocess` imports, then add this test:

```python
def test_budget_bar_uses_remaining_money_only_in_mock_mode(self):
    from scout import report_html

    node = shutil.which("node")
    if node is None:
        self.skipTest("Node.js is required to exercise dashboard JavaScript")
    match = re.search(
        r"function budgetBarState\(.*?^\}",
        report_html.TEMPLATE,
        re.MULTILINE | re.DOTALL,
    )
    self.assertIsNotNone(match)
    script = match.group(0) + """
const cases = [
  budgetBarState(100, 0, true),
  budgetBarState(100, 25, true),
  budgetBarState(100, 100, true),
  budgetBarState(100, 25, false),
];
process.stdout.write(JSON.stringify(cases));
"""
    got = json.loads(subprocess.check_output(
        [node, "-e", script], text=True
    ))

    self.assertEqual([case["fillPct"] for case in got], [100, 75, 0, 25])
    self.assertEqual(got[1]["percentText"], "75% remaining")
    self.assertEqual(got[3]["percentText"], "25% used")
    self.assertEqual(got[1]["title"], "remaining $75 of $100 (75%)")
```

The production break caught by this test is reversing the wrong mode or
computing mock fill from money spent.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.PricingTests.test_budget_bar_uses_remaining_money_only_in_mock_mode -v
```

Expected: FAIL because `budgetBarState` does not exist.

- [ ] **Step 3: Implement the JavaScript helper**

Add immediately before `renderTeams`:

```javascript
function budgetBarState(budget, spent, mockMode){
  if (budget == null) return null;
  const left = budget - spent;
  const rawPct = budget > 0
    ? Math.round((mockMode ? left : spent) / budget * 100)
    : 0;
  const pct = mockMode ? Math.max(0, Math.min(100, rawPct)) : rawPct;
  const fillPct = Math.max(0, Math.min(100, rawPct));
  const percentText = `${pct}% ${mockMode ? "remaining" : "used"}`;
  const title = mockMode
    ? `remaining $${left} of $${budget} (${pct}%)`
    : `spent $${spent} of $${budget} (${pct}%)`;
  return {left, pct, fillPct, title, percentText};
}
```

- [ ] **Step 4: Use the helper in the shared renderer**

Replace the inline `pct` calculation with:

```javascript
const budgetState = budgetBarState(budget, t.spent, MOCKMODE);
const bar = budgetState
  ? `<div class="moneybar ${over?"over":""}" title="${budgetState.title}"><i class="spent" style="width:${budgetState.fillPct}%"></i></div>`
  : "";
```

Change the percentage suffix in the money row to:

```javascript
${budget && budgetState
  ? ` <span class="dim">(${budgetState.percentText})</span>`
  : ""}
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_regressions.PricingTests.test_budget_bar_uses_remaining_money_only_in_mock_mode -v
```

Expected: PASS.

### Task 3: Documentation, Full Verification, and Commit

**Files:**
- Modify: `README.md:174-204`
- Regenerate: `LD2L_S22_Scouting.html` (gitignored runtime artifact)

**Interfaces:**
- Documents the user-visible mock nomination and bar semantics.
- Produces a regenerated local dashboard containing the new embedded code.

- [ ] **Step 1: Update mock draft documentation**

Add a concise sentence to the mock draft section:

```markdown
Captains nominate from lowest to highest starting budget (source order breaks
ties), and each team card's blue budget bar shows the share of starting money
remaining.
```

- [ ] **Step 2: Run focused regression tests**

Run:

```powershell
python -m unittest tests.test_regressions.MockAuctionTests.test_lowest_starting_budget_nominates_first_with_stable_ties tests.test_regressions.PricingTests.test_budget_bar_uses_remaining_money_only_in_mock_mode -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 4: Regenerate the dashboard offline**

Run:

```powershell
python ld2l_scout.py --offline
```

Expected: exit code 0 and `LD2L_S22_Scouting.html` is regenerated with the
new embedded dashboard JavaScript.

- [ ] **Step 5: Review the final diff**

Run:

```powershell
git diff --check
git status --short
git diff -- scout/mockdraft.py scout/report_html.py tests/test_regressions.py README.md
```

Expected: no whitespace errors; only the planned tracked files plus the user's
pre-existing `captains.json` modification are present.

- [ ] **Step 6: Commit tracked implementation files**

Run:

```powershell
git add -- scout/mockdraft.py scout/report_html.py tests/test_regressions.py README.md docs/superpowers/plans/2026-07-26-mock-budget-bar-and-nomination-order.md
git commit -m "Update mock budget and nomination order"
```

Do not stage `captains.json`.
