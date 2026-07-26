# Deep Draft Value Scouting

Date: 2026-07-26
Status: Approved

## Goal

Identify the best players to draft for their expected auction price, while
showing the evidence behind the recommendation. The analysis must answer:

- whether the player is a proven winner in verified ticketed leagues
- how much vision and dewarding work the player performs
- how often the player produces a strong lane
- which positions the evidence supports
- whether the player has credible experience on Lone Druid, Meepo, Huskar,
  Phantom Lancer, Medusa, Sniper, Viper, Witch Doctor, Zeus, and Necrophos

The main dashboard receives a compact ranking signal. Each player scouting
report receives the detailed samples, rates, confidence, and caveats.

## Statistical principles

Raw percentages do not enter the draft ranking without sample-size shrinkage.
The report always shows the numerator and denominator beside a rate.

Channels are kept separate:

- skill value measures expected performance relative to expected auction cost
- league proof measures verified ticketed results
- lane strength measures laning evidence rather than match results
- vision work measures support activity and successful dewards where available
- role fit measures demonstrated position evidence
- hero fit measures experience on the requested heroes

Missing evidence is neutral. It is never converted to a zero or a negative
grade. The ranking shows a confidence label so private and thin profiles do not
look equally certain to well-sampled players.

## Dashboard

Add a sortable `Draft Value` column. The cell contains:

- a 0–100 value score
- a short confidence label
- the player's estimated value edge in auction dollars when available

The score is a ranking aid, not a replacement for the existing `Worth$`,
`Est$`, and `Edge$` columns.

The score combines:

- 55% auction value: expected skill/role value versus expected price
- 15% verified league proof
- 12% recent lane strength
- 8% role fit and versatility
- 5% vision/dewarding evidence
- 5% requested-hero fit

Every non-price channel is reliability-weighted. A missing channel contributes
the neutral midpoint and lowers confidence rather than lowering the player.
The resulting weighted signal is centered on 50 and bounded to 0–100.

## Verified league proof

Ticketed matches remain the only source used for claims about other leagues.
The report shows all-time and six-month records and the existing per-league
history.

Add:

- a beta-binomial posterior win rate using a neutral 50% prior equivalent to
  10 games
- a Wilson 95% lower bound
- number of distinct leagues
- a proof label

Proof labels:

- `Proven winner`: at least 20 games, at least two leagues, and Wilson lower
  bound at or above 50%
- `Winning record`: at least 10 games and posterior win rate above 52%
- `Experienced`: at least 20 games without statistically positive results
- `Limited sample`: one to nineteen games
- `No verified history`: zero ticketed games
- `Unavailable`: the ticketed data source could not be loaded

Recent results affect the narrative but do not erase career evidence.

## Lane strength

The current `lane_wr` field is match win rate while assigned to a lane. It is
renamed internally and in explanations so it cannot be mistaken for lane
outcome.

The normal 200-match OpenDota projection gains:

- `lane_efficiency_pct`
- `is_roaming`
- `purchase_ward_observer`
- `purchase_ward_sentry`
- `version`

The hybrid deep pass selects each player's ten newest match IDs and loads the
full parsed match once. Parsed match records are immutable and cached by match
ID without expiry. Shared matches across signup players cost one request.

For a parsed, non-roaming match with known lane assignments, compare the
player's side with the opposing side in the same physical lane at minute ten.
The lane resource score is team gold at minute ten plus experience at minute
ten weighted by the pool-wide gold-to-experience ratio. A side wins the lane
when its score leads by at least 5%; it loses when behind by at least 5%;
otherwise the lane is a draw. Every player assigned to that physical lane
receives the same lane result.

When a full parsed match is unavailable, lane efficiency remains a fallback
signal. The 200-match lane-efficiency sample uses parsed, non-roaming matches
with a known lane and is compared with the pool median for the same lane
assignment.

The scouting report displays:

- exact lane-win percentage, draw percentage, and sample size
- median EFF@10
- lane-specific win percentages where the deep sample permits
- the existing match win rate by assigned lane, explicitly labeled as match WR

The dashboard and report use `Lane win %` only for the exact deep sample. Where
that sample is absent, the report displays `EFF@10` and explicitly says exact
lane results are unavailable.

## Vision and dewarding

The 200-match projection exposes observer and sentry purchases for parsed
matches. Compute duration-normalized:

- sentries purchased per 30 minutes
- observers purchased per 30 minutes
- number of parsed matches behind the rate

Sentries per 30 is the scalable dewarding-effort metric. It is compared only
with credible support candidates and shrunk toward the support-pool median.

The deep parsed-match cache exposes successful observer and sentry ward kills.
The report shows each count and combined dewards per 30 minutes over the exact
sample. If successful deward data is unavailable, the report says so and does
not infer kills from purchases.

The dashboard score uses both vision effort and successful dewards when their
samples permit. Both are role-normalized so cores are not penalized for doing a
different job.

## Role fit

Use the existing five-position rating model as the base. Add a role-fit
summary:

- `Best role`: the highest rated position
- `Secondary role`: another position only when its rating is within 175 MMR of
  the best and has credible lane/hero/support evidence
- `Versatile`: two or more credible positions
- `Specialist`: one credible position
- `Unclear`: insufficient evidence

The narrative recommends where the player should play and explains the
evidence. Safelane location alone must not classify a player as position 1 or
5; hero affinity, farm, assists per death, ward purchases, and declared role
are supporting signals.

## Requested hero fit

Create a stable requested-hero list:

- Lone Druid
- Meepo
- Huskar
- Phantom Lancer
- Medusa
- Sniper
- Viper
- Witch Doctor
- Zeus
- Necrophos

For each hero show:

- lifetime games, wins, and win rate
- recent games and wins in the 200-match/six-month sample
- verified ticketed games and wins
- an evidence label

Labels:

- `Proven`: at least 20 lifetime games and at least 52% posterior win rate, or
  at least five ticketed games with a winning record
- `Current`: at least three games in the six-month sample
- `Historical`: at least five lifetime games without current evidence
- `Tried`: one to four lifetime games
- `No evidence`: zero public games

The hero-fit score rewards breadth of `Proven` and `Current` coverage but is
small enough that a niche hero checklist cannot override player value.

## Player scouting report

Add a `Draft recommendation` card near the top with:

- draft-value score, rank within the pool, and confidence
- estimated auction edge
- best role and secondary roles
- one-line verdict
- strongest evidence and principal risks

Add or expand detailed cards for:

- league proof
- strong-lane results
- vision/dewarding
- role fit
- requested-hero matrix

Each card identifies its time window and sample. Tooltips and notes distinguish
observed data from modeled conclusions.

## Caching and refresh

Normal refreshes reuse the current per-player cache. Expanding the match
projection bumps its section version so the next online run fetches the new
fields once.

The deep cache stores the normalized player and minute-ten lane fields for each
selected match. Because completed match data does not change, cached matches do
not expire. The initial online deep run may request up to roughly ten matches
per signup player. Later runs request only newly selected matches. Offline runs
use whatever deep samples are already cached and mark thinner coverage.

## Testing

Tests cover:

- posterior and Wilson calculations
- league-proof labels and missing-data behavior
- lane benchmark construction, strong-lane rates, and roaming exclusion
- duration-normalized ward-purchase rates
- exact ticketed ward-kill aggregation when available
- role-fit classification
- hero-name aliases and requested-hero evidence labels
- value-score reliability weighting, neutral missing channels, and stable rank
- dashboard serialization and sorting
- all detailed report cards and explanatory notes

The full regression suite must pass. Then regenerate the dashboard and all
player reports with online data so the expanded match projection is populated.
