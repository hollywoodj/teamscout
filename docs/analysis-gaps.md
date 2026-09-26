# Statistics and scouting report: gap review

A review of the statistical methods behind LD2L Scout's dashboard, the
per-player scout reports, and Team Scout, with the gaps that matter most for
draft-night decisions and a concrete suggestion for each. Written 2026-09-26
against the code in `scout/`.

The short version: the tool is unusually honest about uncertainty (Wilson
bounds, shrinkage, family-wise correction, confidence labels everywhere), and
its weakest spots are not the formulas but **what is never measured**: nothing
is validated against outcomes, correlation between team-mates is acknowledged
but not handled, and several hand-set weights and thresholds have no
calibration behind them.

## 1. What is in place today

| Area | Method | Where |
| --- | --- | --- |
| Skill estimate (Plays Like) | Inverse-variance mean of medal-implied MMR and median lobby rank, with disagreement rules, a z-gated momentum nudge and a rust penalty | `analysis._skill_estimate`, `stats.ivw_mean` |
| Hot / cold form | Binomial z on the 30-day record, family-wise bar raised for pool size (`family_z`) | `analysis.flag_hot_cold` |
| Farm / KDA outliers | Median/MAD robust z against peers within ±700 listed MMR | `analysis`, `stats.robust_z` |
| Holds up a bracket | Wilson lower bound (z=1.28) on record in lobbies 2+ stars up | `analysis` |
| Verified league proof | Beta posterior (neutral prior, 10 games) plus Wilson 95% lower bound, banded labels | `analysis.league_proof` |
| Auction price | 7-nearest-by-MMR median over four past seasons, plus a rank premium calibrated by order statistics and a positional scarcity premium anchored to it | `pricing.py`, `config.AUCTION_*` |
| Draft Value (0–100) | Fixed-weight blend: 55% auction edge, 15% league proof, 12% lane results, 8% role fit, 5% vision, 5% requested heroes; secondary channels shrink to neutral on small samples | `keys.py` / `analysis` |
| Position ratings | Four evidence channels (lane share, hero-pool affinity, in-lane win rate, support gradient) with saturating curves and caps | `analysis.position_ratings`, `hero_positions.py` |
| Lane result | Minute-10 gold + 0.6×XP of both sides of the same lane; ±2.5% band is a draw | `deepstats`, `team_scout.deep_summary` |
| Best heroes / hidden gems | Beta-binomial style shrunk win rate; gem bar is the higher of 53% and pub baseline + 3 points | `hero_pool.py` |
| Team Scout win vs loss | Two-population comparison of KDA, farm, damage, wards, teamfight; largest differences called out; Wilson 95% range on win rate | `team_scout_html` |
| Key reads | Fisher exact test on good-vs-bad-game splits | `keys.py`, `stats.fisher_exact` |
| Observed position | Rule-based inference from lane, hero prior, farm, wards; high/medium/low confidence | `team_scout.infer_position` |
| Toxicity | Weighted token scan of the OpenDota word cloud | `toxicity.py` |

## 2. Gaps, in priority order

### 2.1 Nothing is validated against outcomes (highest value)

Draft Value, Plays Like, position ratings and the hero draft ratings are all
built from sensible priors, but the repository contains no back-test: no
comparison of last season's pre-draft numbers with what happened. The auction
price model is the one exception (LOOCV MAE ≈ 36, season-holdout bias
figures), and it shows what the rest should look like.

Suggestion. Add a `scout/backtest.py` that, for each past season already in
the auction harvest, freezes the pre-draft snapshot and scores it against
three outcomes that BBC already stores: team regular-season win rate, player
official win rate, and player official KDA/GPM relative to position. Report
Spearman rank correlation and a calibration table (predicted decile versus
observed). This single artefact tells you which of the six Draft Value
channels earns its weight and which weights to change. Without it every
tuning discussion is opinion.

### 2.2 Team-mate correlation is acknowledged but not handled

Team Scout notes that "player-games from the same match can be correlated",
then computes Wilson intervals and two-population differences as if every
player-game were independent. In a five-stack every official match
contributes five rows that share the same result, so the effective sample is
roughly one fifth of the row count and every interval is too narrow.

Suggestion. For team-level comparisons aggregate to the match first (one
row per match, team means or sums), then compare. For player-level
comparisons that must pool team-mates, use a cluster bootstrap: resample
matches, not rows, 1,000 times and report the 2.5/97.5 percentiles. It is a
40-line change and makes the "largest observed differences" panel honest.

### 2.3 Win-vs-loss comparisons invite reverse causation

The win/loss split reports that wins have higher GPM, more kills and fewer
deaths. That is true of every team in every game ever played; it is the
definition of winning, not a scouting insight. The panel does say
"descriptive, not causal", but the ranking by largest difference still
surfaces the tautologies first.

Suggestion. Restrict the comparison to **early-game and process metrics
that precede the result**: lane efficiency at 10, first-blood involvement,
ward counts before minute 15, camps stacked, rune pickups, first tower time,
and draft features (first pick, side). These separate "they win when they win
lane" (actionable: pressure their lanes) from "they win when they have more
gold at the end" (empty). Keep the late metrics in a secondary table.

### 2.4 Multiple comparisons on the matchup and key-read tables

Fisher exact tests are run per split and the official hero matchup table
flags "good with / struggle against" on samples as small as two games. Across
dozens of heroes and splits some flags are noise by construction. Hot/cold
form already fixes this with a family-wise bar, so the pattern exists in the
codebase.

Suggestion. Apply the same `family_z` idea, or a Benjamini–Hochberg
false-discovery rate at 10%, to the Fisher tests in `keys.py` and to the
2-game hero flags. Show the number of tests alongside the survivors so a
reader can see the base rate.

### 2.5 Fixed Draft Value weights and no confidence propagation

The 55/15/12/8/5/5 weights are documented as deliberate, but nothing ties
them to outcomes, and the final 0–100 number carries no interval. A player
with three thin channels and one strong one shows the same precision as one
with five deep samples. The confidence label helps, but it is a
three-level string.

Suggestion. Once 2.1 exists, fit the weights by a simple ridge regression of
the outcome on the six channel scores (constrained to be non-negative, so the
result stays interpretable), and carry each channel's shrinkage weight
through to a stated range on the final score. Even without the back-test,
switch the display to "68 (range 58–76)" using the channel sample sizes you
already compute.

### 2.6 Lane result is a fixed-band point estimate

The lane read uses gold + 0.6×XP at minute 10 with a ±2.5% draw band. The
0.6 and the 2.5% are unexplained constants, and the metric ignores who the
lane opponents were (a 55% lane against a Divine duo is a different fact from
55% against Crusaders).

Suggestion. Report the lane edge as a continuous number with its sample
(mean edge ± standard error), not only W/D/L; and adjust for opponent
strength with the lobby average rank you already fetch (edge residual after
regressing on rank gap). Keep W/D/L as the headline, but make the band a
config constant with a comment on how it was chosen.

### 2.7 Position inference has no ground truth

`infer_position` labels each match high/medium/low confidence from rules.
There is no measurement of how often "high" is right. The `hero_positions`
table is a curated prior and drifts with each patch (Snapfire, Hoodwink and
Earth Spirit have all moved position this year).

Suggestion. Use the official matches as a labelled set: in a five-stack the
pos 1–5 assignment is unambiguous from farm order and lane. Score the rule
inference against it once per season and print the confusion matrix. That
also gives you a data-driven way to update `HERO_POS` for the current patch
rather than by hand.

### 2.8 Skill estimate constants are stated, not fitted

SIGMA_MEDAL = 180, SIGMA_LOBBY_BASE = 500, the 500-MMR disagreement rule and
the 0.75/0.65 trust weights are reasonable but unsourced. The README's
note that OpenDota's computed MMR correlates only r≈0.5 with reality shows
you have done the check once; it is not repeated.

Suggestion. Fit the two sigmas from the players whose listed MMR was
admin-verified in past seasons (the "re-rated" baseline in
`cache/mmr_baseline_*.json` is exactly this population). Report the fitted
values next to the constants each season.

### 2.9 Player scout reports: missing or thin sections

- **Recent form is 30/90-day win rate only.** No rating-style trend
  (Elo/Glicko over the last 50 games) and no streak context. A Glicko-2
  pass over the 200-match sample is cheap and gives a rating with its own
  deviation, which is a better "momentum" than a z-gated nudge.
- **US-East vulnerability** compares a server win rate with lifetime win
  rate without an interval or a sample floor. Show the Wilson range and
  suppress the verdict under 15 games.
- **Toxicity** is a keyword count with no base rate. Show the score's
  percentile within the pool and the number of words scanned, and suppress
  under a minimum word-cloud size.
- **Requested-hero fit** covers ten fixed heroes. Replace the fixed list with
  the current curated meta (`scout/meta_heroes.json`) plus the team's own
  needs so the section stays relevant per patch.
- **Party vs solo** is reported but not used in the skill estimate, although
  the README notes that party queue drags lobby rank down. Weight the lobby
  median by solo share.

### 2.10 Team Scout: what a captain still cannot see

- **Draft tendencies beyond bans.** The Draft pane shows most banned and
  most banned against. The new hero draft book (`herodraft.build_draft_book`)
  already computes first-pick openers, per-slot habits, undefeated heroes and
  per-player official records. Surface those cards in the Draft pane too, so
  the scouting page and the practice bot show the same read.
- **Side and first-pick splits have no interval.** They are shown as W-L
  and percent on samples of 3–8 games. Add the Wilson range and grey out
  under 5 games, as the win-rate metrics already do.
- **Patch drift.** Team pages show patch history but no test of whether
  performance on the current patch differs from before. A two-proportion
  test with the interval is enough.
- **Stand-in effect.** Rosters record replacements, but results are not split
  by "posted five" versus "with a stand-in". That split is often the whole
  story of an upset.

## 3. Methods worth knowing about (alternatives)

- **Empirical Bayes shrinkage** instead of a fixed 10-game neutral prior:
  fit the prior's strength from the pool's spread of win rates. Same
  formula, one fewer magic number.
- **Glicko-2** for per-player form: rating plus rating deviation plus
  volatility; handles inactivity (rust) natively.
- **Cluster bootstrap** for any statistic that pools team-mates or repeated
  games from one player.
- **Benjamini–Hochberg** for any table of flags produced by many tests.
- **Bradley–Terry** on official results for team strength, which handles
  schedule strength; the current standings and win rate do not.
- **Isotonic calibration** for the hero draft win-probability meter once
  practice drafts are logged with real results.

## 4. Suggested order of work

1. Back-test harness (2.1). Everything else is easier to judge after it.
2. Match-level aggregation and cluster bootstrap in Team Scout (2.2, 2.3).
3. FDR control on flags (2.4).
4. Intervals on side/first-pick splits and US-East (2.9, 2.10).
5. Draft Value range display (2.5), then fitted weights once 1 exists.
6. Position inference confusion matrix and patch-driven `HERO_POS` update (2.7).
