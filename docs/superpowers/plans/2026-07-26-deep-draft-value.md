# Deep Draft Value Scouting Implementation Plan

> **For agentic workers:** Execute sequentially with test-driven development.
> Do not modify or stage `captains.json`.

**Goal:** Rank the signup pool by confidence-weighted auction value and add
verified league, exact recent lane, dewarding, role-fit, and requested-hero
evidence to every player report.

**Architecture:** Expand the existing per-player match projection for cheap
long-window proxies, then add an immutable full-match cache for each player's
ten newest matches. Normalize those parsed matches into small player samples,
calculate pool-relative/shrunk scouting channels in the existing analysis
pass, and serialize compact dashboard fields while rendering full evidence in
the player reports.

**Tech stack:** Python standard library, `requests`, OpenDota REST API,
`unittest`, generated HTML/CSS/JavaScript.

## Global constraints

- Never call match win rate by assigned lane a lane-win rate.
- Only show exact lane-win percentage from a parsed full-match comparison at
  minute ten.
- Show every percentage with its sample size.
- Treat missing data as neutral and lower confidence.
- Cache completed match details indefinitely by immutable match ID.
- Limit the deep sample to ten newest matches per player.
- Keep generated reports self-contained and offline-safe.
- Preserve `captains.json` as an unstaged user change.

---

### Task 1: Deep parsed-match cache

**Files:**

- Modify `scout/cache.py`
- Modify `scout/opendota.py`
- Create `scout/deepstats.py`
- Create `tests/test_deepstats.py`

- [ ] Write failing tests for immutable match-cache reads/writes, unique match
  fetches, offline fallback, target-player extraction, ward kills, and physical
  lane resource totals.
- [ ] Add `OpenDota.match(match_id)`.
- [ ] Add cache methods under `cache/matches/<match_id>.json`.
- [ ] Normalize each target sample to match ID, timestamp, duration, parsed
  status, physical lane, lane role, roaming status, minute-ten player/team
  gold and XP, and observer/sentry kills.
- [ ] Select at most ten newest matches per player and reuse shared cached
  matches.
- [ ] Run `python -m unittest tests.test_deepstats -v`.

### Task 2: Long-window vision, lane, and hero inputs

**Files:**

- Modify `scout/fetch.py`
- Modify `scout/analysis.py`
- Modify `scout/esports.py`
- Modify `tests/test_deepstats.py`
- Modify `tests/test_esports.py`

- [ ] Write failing tests for the expanded match projection and cache-version
  bump.
- [ ] Project `version`, `lane`, `lane_efficiency_pct`, `is_roaming`,
  `purchase_ward_observer`, and `purchase_ward_sentry`.
- [ ] Aggregate EFF@10 by lane, observer/sentry purchases per 30 minutes, and
  parsed coverage.
- [ ] Preserve lifetime hero wins as well as games.
- [ ] Aggregate six-month recent hero games/wins from the match sample.
- [ ] Extend verified ticketed history with all-time hero games/wins.
- [ ] Create the stable requested-hero matrix with aliases for Zeus and
  Necrophos.
- [ ] Run focused analysis and esports tests.

### Task 3: Exact lane, league proof, dewarding, and role fit

**Files:**

- Modify `scout/stats.py`
- Modify `scout/analysis.py`
- Create `tests/test_draft_value.py`
- Modify `tests/test_regressions.py`

- [ ] Write failing tests for beta posterior, Wilson bound usage, proof labels,
  and unavailable history.
- [ ] Write failing tests for the 5% lane-win/draw threshold using combined
  lane gold and XP at minute ten.
- [ ] Write failing tests for exact dewards per 30 and role-normalized vision
  effort.
- [ ] Write failing tests for best/secondary role classification and specialist
  versus versatile labels.
- [ ] Implement channel calculations in the pool analysis pass so benchmarks
  use only the current signup pool.
- [ ] Rename the old lane-match record internally or label it explicitly at
  every presentation point.
- [ ] Run the focused tests.

### Task 4: Confidence-weighted draft-value ranking

**Files:**

- Modify `scout/analysis.py`
- Modify `tests/test_draft_value.py`

- [ ] Write failing tests proving auction value dominates the score, missing
  channels stay neutral, small league/lane samples shrink, and stable ranks are
  assigned.
- [ ] Implement the six channel scores and weights from the approved design.
- [ ] Derive high/medium/low confidence from weighted evidence coverage.
- [ ] Rank all draftable non-captains by score, then auction edge, while still
  assigning display ranks to other signup rows.
- [ ] Add a concise verdict and strongest evidence/risk list.
- [ ] Run the focused tests.

### Task 5: CLI orchestration and dashboard

**Files:**

- Modify `scout/cli.py`
- Modify `scout/report_html.py`
- Modify `tests/test_draft_value.py`
- Modify `tests/test_esports.py`

- [ ] Write failing serialization and generated-dashboard tests.
- [ ] Fetch ordinary sections first, enrich each player with cached deep
  samples, then run the existing analysis and auction passes.
- [ ] Serialize draft score/rank/confidence, exact lane result, role fit, vision
  rate, proof label, and compact requested-hero coverage.
- [ ] Add the sortable `Draft Value` dashboard column without removing the
  existing Worth/Est/Edge fields.
- [ ] Keep the cell compact and link its evidence to the player report.
- [ ] Run focused dashboard tests.

### Task 6: Detailed player reports

**Files:**

- Modify `scout/report_player_html.py`
- Modify `tests/test_draft_value.py`

- [ ] Write failing report-card tests.
- [ ] Add the draft recommendation card near the report header.
- [ ] Expand league history with posterior evidence and proof label.
- [ ] Add exact lane win/draw/loss, EFF@10 fallback, and explicit match-WR
  labeling.
- [ ] Add vision/dewarding rates and coverage.
- [ ] Add best-role and credible-secondary-role explanation.
- [ ] Add the ten-hero lifetime/recent/ticketed evidence matrix.
- [ ] Run focused report tests.

### Task 7: Documentation, verification, and regeneration

**Files:**

- Modify `README.md`
- Regenerate `LD2L_S22_Scouting.html`
- Regenerate `LD2L_S22_Scouting.xlsx`
- Regenerate `scout_reports/*.html`

- [ ] Document the deep match cache, definitions, samples, and refresh cost.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run an online Season 22 scout refresh to populate expanded and deep
  caches; communicate progress during the initial match-detail fetch.
- [ ] Run a second offline regeneration and verify it uses cached deep data.
- [ ] Inspect the dashboard and representative player-report HTML.
- [ ] Review `git diff` and confirm `captains.json` remains unstaged.
- [ ] Commit implementation and documentation.

