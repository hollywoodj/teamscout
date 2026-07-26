# Official Mock-Draft Roster Source

## Problem

The generated scouting dashboard and mock draft currently present one HTML
surface but resolve roster data differently:

- The generated dashboard embeds current captain budgets scraped from the LD2L
  season teams page.
- The mock draft treats `captains.json` as authoritative for both the bidder
  roster and budgets.
- `captains.json` is also the bridge for browser-only state such as player roles
  and removals.

This allows an older export to replace current website budgets. It also allows a
website-budget captain to have `steam32: null` when that player was not marked
with the dashboard's **C** control. The mock excludes captains from its player
pool by Steam ID, so a null ID can make the same person both a captain and a
draftable player.

## User-Facing Behavior

Mock mode supports two explicit roster sources:

```powershell
python ld2l_scout.py --mock --roster official
python ld2l_scout.py --mock --roster curated
```

`--official-roster` is accepted as a convenient alias for
`--roster official`.

### Official mode

- The LD2L season teams page is authoritative for the captain list, Steam IDs,
  team IDs, and starting budgets.
- A valid online response is cached by season for offline fallback.
- `budgets.json` remains the final intentional per-captain budget override.
- `captains.json` supplies only player roles and the removed-player list. Its
  captain identities and budget values cannot overwrite official values.
- The mock refuses to start if no valid current or cached official roster is
  available.

### Curated mode

- `captains.json` remains authoritative for captains and budgets, supporting
  preseason practice before teams are finalized.
- Missing captain Steam IDs are resolved against the cached signup pool by a
  normalized exact player-name match.
- An unresolved captain is reported clearly and is not allowed to remain both a
  captain and a draftable player.

`MockDraft.vbs` launches official mode now that the Season 22 roster is
finalized. Preseason use remains available through `--roster curated`.

## Architecture

Roster resolution has one owner rather than separate dashboard and mock
implementations.

A focused roster resolver will:

1. Fetch and cache official season-team rows.
2. Apply `budgets.json` overrides consistently.
3. Normalize and match captain identities against the signup pool.
4. Select official or curated captain authority explicitly.
5. Preserve roles and removals from `captains.json` independently of captain
   authority.

Dashboard generation and mock mode will consume the same official budget
resolution rules. The dashboard exporter will also resolve budget-only captain
names against its embedded player data before writing a null ID, providing
defense in depth for curated exports.

The mock state payload will include the selected roster source so the dashboard
can display `Roster: Official` or `Roster: Curated`.

## Validation and Failure Handling

- Official data is valid when it contains at least one captain with a usable
  name, budget, and resolvable Steam ID.
- A failed or invalid online fetch falls back to the last valid season-scoped
  official roster cache.
- Official mode fails loudly rather than silently mixing an incomplete official
  roster with curated captain rows.
- Curated rows with null IDs are name-matched case-insensitively after trimming
  whitespace.
- Ambiguous or unresolved name matches are reported and excluded from both the
  bidder roster and player pool until corrected.
- Existing `captains.json` files remain compatible.

## Testing

Automated regression tests will prove that:

1. A null-ID `champ0044` row resolves to Steam32 `154288911` from signups and is
   removed from the player pool.
2. Official mode replaces an older exported Champ budget with the current
   website budget.
3. Curated mode preserves exported budgets.
4. `budgets.json` overrides official values intentionally.
5. Official mode uses the season-scoped cache when offline.
6. Official mode fails clearly when neither live nor cached official data is
   valid.
7. The generated exporter fills a matching player's Steam ID for a budget-only
   captain.
8. Existing mock-draft and dashboard regression tests remain green.

## Scope

This change does not alter auction bidding strategy, player valuation, role
calculation, live-draft polling, or the separate hero-draft tool.
