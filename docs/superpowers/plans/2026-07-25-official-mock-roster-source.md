# Official Mock-Draft Roster Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give mock drafts an explicit official or curated roster source so finalized LD2L captains and budgets cannot be replaced by stale browser exports.

**Architecture:** Extend the existing `scout.captains` ownership boundary to load, validate, cache, identity-resolve, and override official roster rows. Mock mode selects official or curated captain authority explicitly, while roles and removals always remain independent browser-curated data from `captains.json`; dashboard generation consumes the same official loader.

**Tech Stack:** Python 3 standard library, `requests`, existing JSON `Cache`, `argparse`, generated HTML/JavaScript, `unittest`.

## Global Constraints

- `--roster official` makes the LD2L teams page authoritative for captains, Steam IDs, team IDs, and starting budgets.
- `--official-roster` is an alias for `--roster official`.
- `--roster curated` preserves preseason `captains.json` captain and budget behavior.
- `captains.json` supplies player roles and removals in both modes.
- `budgets.json` remains the final intentional budget override.
- Valid official rows are cached by season; offline official mode uses that cache and fails clearly without it.
- Missing exported Steam IDs are resolved by normalized exact player-name matching.
- `MockDraft.vbs` launches official mode for the finalized Season 22 roster.
- Do not modify or discard the user's current uncommitted `captains.json`.

---

### Task 1: Shared official roster resolution

**Files:**
- Modify: `scout/captains.py`
- Test: `tests/test_regressions.py`

**Interfaces:**
- Consumes: existing `Cache.get_blob`, `Cache.set_blob`, `load_budget_overrides`, and LD2L team rows shaped as `{captain, steam64, team_id, budget, unspent}`.
- Produces:
  - `normalized_name(value: str) -> str`
  - `resolve_team_identities(teams: list[dict], players: list[dict]) -> tuple[list[dict], list[str]]`
  - `load_official_teams(season: int, cache, offline: bool = False, fetcher=None, path: str = "budgets.json") -> tuple[list[dict], str, str | None]`

- [ ] **Step 1: Add failing identity-resolution tests**

Add tests to the existing `CaptainsTests` class in
`tests/test_regressions.py`:

```python
def test_null_steam_id_resolves_by_normalized_player_name(self):
    from scout.captains import resolve_team_identities
    teams = [{"captain": "  CHAMP0044 ", "steam64": None,
              "team_id": None, "budget": 260}]
    players = [{"name": "champ0044", "steam32": 154288911}]
    rows, unresolved = resolve_team_identities(teams, players)
    self.assertEqual(unresolved, [])
    self.assertEqual(rows[0]["steam64"],
                     154288911 + config.STEAM64_OFFSET)

def test_ambiguous_name_is_not_resolved(self):
    from scout.captains import resolve_team_identities
    teams = [{"captain": "Champ", "steam64": None, "budget": 260}]
    players = [{"name": "champ", "steam32": 1},
               {"name": " CHAMP ", "steam32": 2}]
    rows, unresolved = resolve_team_identities(teams, players)
    self.assertEqual(rows, [])
    self.assertEqual(unresolved, ["Champ"])
```

- [ ] **Step 2: Run the identity tests and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.CaptainsTests.test_null_steam_id_resolves_by_normalized_player_name tests.test_regressions.CaptainsTests.test_ambiguous_name_is_not_resolved -v
```

Expected: both tests error because `resolve_team_identities` does not exist.

- [ ] **Step 3: Implement normalized identity resolution**

In `scout/captains.py`, add:

```python
def normalized_name(value):
    return " ".join(str(value or "").split()).casefold()


def resolve_team_identities(teams, players):
    by_name = {}
    for player in players:
        by_name.setdefault(normalized_name(player.get("name")), []).append(player)

    resolved, unresolved = [], []
    for source in teams:
        row = dict(source)
        if not row.get("steam64"):
            matches = by_name.get(normalized_name(row.get("captain")), [])
            if len(matches) != 1:
                unresolved.append(row.get("captain") or "")
                continue
            row["steam64"] = int(matches[0]["steam32"]) + config.STEAM64_OFFSET
        resolved.append(row)
    return resolved, unresolved
```

Import `config` from `scout` at module scope.

- [ ] **Step 4: Run the identity tests and verify GREEN**

Run the command from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Add failing official-loader tests**

Add tests using a real temporary `Cache(root=root)`:

```python
def test_official_loader_caches_rows_and_applies_budget_override(self):
    from scout.cache import Cache
    from scout.captains import load_official_teams
    with tempfile.TemporaryDirectory() as root:
        cache = Cache(root)
        override = os.path.join(root, "budgets.json")
        with open(override, "w", encoding="utf-8") as f:
            json.dump({"champ0044": 275}, f)
        live = [{"captain": "champ0044", "steam64": 76561198114554639,
                 "team_id": "10", "budget": 260, "unspent": 260}]
        rows, source, error = load_official_teams(
            53, cache, fetcher=lambda _: live, path=override)
        self.assertIsNone(error)
        self.assertEqual(source, "website")
        self.assertEqual(rows[0]["budget"], 275)
        cached, cached_source, cached_error = load_official_teams(
            53, cache, offline=True, path=override)
        self.assertIsNone(cached_error)
        self.assertEqual(cached_source, "cache")
        self.assertEqual(cached[0]["budget"], 275)

def test_official_loader_fails_without_live_or_cached_rows(self):
    from scout.cache import Cache
    from scout.captains import load_official_teams
    with tempfile.TemporaryDirectory() as root:
        rows, source, error = load_official_teams(
            53, Cache(root), fetcher=lambda _: [])
        self.assertEqual(rows, [])
        self.assertEqual(source, "missing")
        self.assertIn("official roster", error.lower())
```

- [ ] **Step 6: Run the official-loader tests and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.CaptainsTests.test_official_loader_caches_rows_and_applies_budget_override tests.test_regressions.CaptainsTests.test_official_loader_fails_without_live_or_cached_rows -v
```

Expected: both tests error because `load_official_teams` does not exist.

- [ ] **Step 7: Implement validated season-scoped official loading**

Add `load_official_teams` to `scout/captains.py`:

```python
def load_official_teams(season, cache, offline=False, fetcher=None,
                        path=OVERRIDES_FILE):
    key = f"official_roster_s{season}"
    rows = []
    source = "missing"
    if not offline:
        if fetcher is None:
            from .ld2l import scrape_budgets
            fetcher = scrape_budgets
        fetched = fetcher(season) or []
        valid = [dict(row) for row in fetched
                 if row.get("captain") and row.get("steam64")
                 and isinstance(row.get("budget"), int)
                 and row["budget"] >= 0]
        if valid and len(valid) == len(fetched):
            rows, source = valid, "website"
            cache.set_blob(key, valid)
    if not rows:
        cached = cache.get_blob(key) or []
        valid = [dict(row) for row in cached
                 if row.get("captain") and row.get("steam64")
                 and isinstance(row.get("budget"), int)
                 and row["budget"] >= 0]
        if valid and len(valid) == len(cached):
            rows, source = valid, "cache"
    if not rows:
        return [], "missing", "No valid official roster is available from the website or cache."
    _, error = override_team_budgets(rows, path=path)
    return rows, source, error
```

- [ ] **Step 8: Run all captain resolver tests**

Run:

```powershell
python -m unittest tests.test_regressions.CaptainsTests -v
```

Expected: all captain derivation, identity, cache, and override tests pass.

- [ ] **Step 9: Commit Task 1**

```powershell
git add scout/captains.py tests/test_regressions.py
git commit -m "Add shared official roster resolution"
```

---

### Task 2: Explicit mock roster selection

**Files:**
- Modify: `scout/mockdraft.py`
- Modify: `scout/cli.py`
- Modify: `scout/broadcast.py`
- Test: `tests/test_regressions.py`

**Interfaces:**
- Consumes: `load_official_teams`, `resolve_team_identities`, curated rows/roles/removals from `_load_captains_file`.
- Produces:
  - `_load_pool(season: int, offline: bool, roster_source: str = "curated")`
  - `run_mock(html_path, season, me=None, port=8322, offline=False, open_browser=True, roster_source="curated")`
  - `MockState(season, label, pool, captains_raw, by_steam, me, roster_source="curated")`
  - `/live/state.mock.roster_source`
  - CLI `args.roster` with values `curated` or `official`.

- [ ] **Step 1: Add a failing regression for the reported Champ duplication**

Add a test that patches the expensive data loaders but executes `_load_pool`:

```python
def test_official_roster_overrides_stale_export_and_drops_champ_from_pool(self):
    from scout import mockdraft
    official = [{"captain": "champ0044",
                 "steam64": config.STEAM64_OFFSET + 154288911,
                 "team_id": "10", "budget": 260}]
    curated = ([{"captain": "champ0044", "steam64": None,
                 "team_id": None, "budget": 255, "pos": None}],
               {154288911: [3, 4, 5]}, set())
    players = [{"name": "champ0044", "steam32": 154288911,
                "steam64": config.STEAM64_OFFSET + 154288911,
                "mmr": 4178, "captain": "N"},
               {"name": "Player", "steam32": 7,
                "steam64": config.STEAM64_OFFSET + 7,
                "mmr": 3000, "captain": "N"}]
    fake_cache = mock.Mock()
    fake_cache.get_blob.return_value = None
    with mock.patch.object(mockdraft, "Cache", return_value=fake_cache), \
         mock.patch.object(mockdraft, "players_from_snapshot",
                           return_value=("S22", players)), \
         mock.patch.object(mockdraft, "load_hero_map", return_value=mock.Mock()), \
         mock.patch.object(mockdraft, "fetch_player_sections",
                           return_value=({}, 0)), \
         mock.patch.object(mockdraft, "build_metrics",
                           side_effect=lambda player, sections, heroes:
                           {"adj_skill": player["mmr"], "worth_cost": 100,
                            "est_cost": 90}), \
         mock.patch.object(mockdraft, "annotate_players", return_value=None), \
         mock.patch.object(mockdraft, "pool_analysis"), \
         mock.patch.object(mockdraft, "_load_captains_file",
                           return_value=curated), \
         mock.patch.object(mockdraft, "load_official_teams",
                           return_value=(official, "website", None)), \
         mock.patch.object(mockdraft, "_player_slots",
                           return_value={1: 3000}), \
         mock.patch.object(mockdraft, "position_ratings",
                           return_value={"primary": 1, "ratings": {}}), \
         mock.patch.object(mockdraft, "value_tier", return_value="C"):
        label, pool, captains, _ = mockdraft._load_pool(
            53, True, roster_source="official")
    self.assertEqual(captains[0]["budget"], 260)
    self.assertNotIn("champ0044", [player["name"] for player in pool])
```

Use `unittest.mock.patch` context managers to return the fixtures above and
return at least one valid role slot for `Player`.

- [ ] **Step 2: Run the Champ regression and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.MockRosterSourceTests.test_official_roster_overrides_stale_export_and_drops_champ_from_pool -v
```

Expected: fail because `_load_pool` does not accept `roster_source`.

- [ ] **Step 3: Implement roster selection in `_load_pool`**

Change the signature to:

```python
def _load_pool(season, offline, roster_source="curated"):
```

Always load `(curated_rows, roles_map, removed)` from `captains.json`. Then:

```python
players_only = [pd["player"] for pd in all_data]
if roster_source == "official":
    captains_raw, official_from, error = load_official_teams(
        season, cache, offline=offline)
    if error:
        print(f"  ⚠ {error}")
    print(f"  👑 Official captains from {official_from}: "
          + ", ".join(t["captain"] for t in captains_raw))
else:
    captains_raw = curated_rows or _captains_from_signups(all_data)

captains_raw, unresolved = resolve_team_identities(
    captains_raw or [], players_only)
```

For each resolved official captain, set `pos` from `roles_map[steam32]` when
available so official identity/budget authority does not discard curated role
circles. If `unresolved` is non-empty, print the names and do not add those rows
to the bidder roster.

- [ ] **Step 4: Run the Champ regression and verify GREEN**

Run the command from Step 2.

Expected: pass with official budget `260` and no Champ pool row.

- [ ] **Step 5: Add failing CLI and wire-state tests**

Add:

```python
def test_parser_accepts_official_roster_alias(self):
    from scout.cli import build_parser
    self.assertEqual(build_parser().parse_args(
        ["--mock", "--official-roster"]).roster, "official")
    self.assertEqual(build_parser().parse_args(
        ["--mock", "--roster", "curated"]).roster, "curated")

def test_mock_snapshot_names_roster_source(self):
    state = MockState(53, "S22", [MockAuctionTests.player()],
                      [{"captain": "Me", "budget": 100,
                        "team_id": "1", "pos": [1]}],
                      {}, "Me", roster_source="official")
    self.assertEqual(state.live_snapshot()["mock"]["roster_source"], "official")
```

- [ ] **Step 6: Run CLI and wire-state tests and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.MockRosterSourceTests.test_parser_accepts_official_roster_alias tests.test_regressions.MockRosterSourceTests.test_mock_snapshot_names_roster_source -v
```

Expected: fail because `build_parser`, the constructor parameter, and the wire
field do not exist.

- [ ] **Step 7: Implement CLI propagation and wire-state source**

- Extract the parser construction in `scout/cli.py` to `build_parser()`.
- Add `--roster` with choices `curated` and `official`.
- Add `--official-roster` with `dest="roster"`, `action="store_const"`, and
  `const="official"`.
- Set the parser default with `parser.set_defaults(roster="curated")`.
- Pass `args.roster` through `run_mock_mode` to `run_mock`.
- Pass `roster_source` through `run_mock` to `_load_pool` and `MockState`.
- Store `self.roster_source` and include it inside the existing `mock` object
  returned by `live_snapshot`.

- [ ] **Step 8: Run all mock regression tests**

Run:

```powershell
python -m unittest tests.test_regressions.MockRosterSourceTests tests.test_regressions.MockAuctionTests tests.test_regressions.BroadcastContractTests -v
```

Expected: all pass.

- [ ] **Step 9: Commit Task 2**

```powershell
git add scout/mockdraft.py scout/cli.py scout/broadcast.py tests/test_regressions.py
git commit -m "Add explicit mock roster sources"
```

---

### Task 3: Unify dashboard budgets and harden captain export

**Files:**
- Modify: `scout/cli.py`
- Modify: `scout/report_html.py`
- Test: `tests/test_regressions.py`

**Interfaces:**
- Consumes: `load_official_teams`, `normalized_name`, dashboard `all_data`,
  embedded `BUDGETS`, and `/live/state.mock.roster_source`.
- Produces: `_captain_id_map(all_data, budgets) -> dict[str, int]`, cached
  official budgets in normal/offline dashboard runs, non-null export IDs when a
  budget captain matches `DATA`, and visible mock roster-source text.

- [ ] **Step 1: Add a failing captain export mapping test**

Add a behavioral unit test for the Python mapping the generated exporter will
consume:

```python
def test_budget_only_captain_maps_to_signup_steam_id(self):
    from scout.report_html import _captain_id_map
    all_data = [{"player": {"name": "champ0044", "steam32": 154288911},
                 "data": {}}]
    self.assertEqual(
        _captain_id_map(all_data, {" CHAMP0044 ": 260}),
        {" CHAMP0044 ": 154288911},
    )
```

- [ ] **Step 2: Run the mapping test and verify RED**

Run:

```powershell
python -m unittest tests.test_regressions.PricingTests.test_budget_only_captain_maps_to_signup_steam_id -v
```

Expected: error because `_captain_id_map` does not exist.

- [ ] **Step 3: Implement the mapping and harden the dashboard exporter**

In `scout/report_html.py`, import `normalized_name` and add:

```python
def _captain_id_map(all_data, budgets):
    by_name = {}
    for pd in all_data:
        player = pd["player"]
        by_name.setdefault(normalized_name(player.get("name")), []).append(player)
    result = {}
    for captain in budgets:
        matches = by_name.get(normalized_name(captain), [])
        if len(matches) == 1:
            result[captain] = int(matches[0]["steam32"])
    return result
```

Embed the result as `CAPTAIN_IDS` beside `BUDGETS`. In the budget-only
`captainList()` export loop, use that ID to locate the player and its roles:

```javascript
const steam32 = CAPTAIN_IDS[name] ?? null;
const player = steam32 == null ? null : DATA.find(p => p.id === steam32);
const roles = player ? manualRoles[player.id] : null;
rows.push({
  name,
  steam32,
  budget: teamBudget(name),
  pos: roles && roles.length ? roles.slice().sort() : null,
});
```

- [ ] **Step 4: Display the active mock roster source**

When applying mock state, render `Roster: Official` or `Roster: Curated` in the
mock header using `m.roster_source`. Do not add a second dashboard or mock-only
HTML template.

- [ ] **Step 5: Use the shared official loader in dashboard generation**

Replace direct `scrape_budgets` plus `resolve_budgets` calls in `run_scout` with
`load_official_teams(args.season, cache, offline=args.offline)`. Derive the
embedded budget map from the returned rows. This makes online generation refresh
and cache official rows and lets offline regeneration retain the last valid
official budgets.

- [ ] **Step 6: Run the HTML and captain resolver tests**

Run:

```powershell
python -m unittest tests.test_regressions.PricingTests tests.test_regressions.CaptainsTests -v
```

Expected: all pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add scout/cli.py scout/report_html.py tests/test_regressions.py
git commit -m "Unify dashboard and mock roster data"
```

---

### Task 4: Launcher, documentation, regeneration, and end-to-end verification

**Files:**
- Modify: `MockDraft.vbs`
- Modify: `README.md`
- Regenerate: `LD2L_S22_Scouting.html`
- Preserve uncommitted: `captains.json`

**Interfaces:**
- Consumes: `--official-roster`, regenerated dashboard template, existing mock
  launcher.
- Produces: an official-mode double-click launcher and documented preseason
  escape hatch.

- [ ] **Step 1: Update the launcher**

Change the command in `MockDraft.vbs` to:

```vbscript
cmd = "cmd /c title LD2L Mock Draft & python ld2l_scout.py --mock --official-roster || pause"
```

Update its comments to say the finalized website roster and budgets override the
export, while exported roles and removals are retained.

- [ ] **Step 2: Update README roster-source documentation**

Replace the statement that `captains.json` always controls mock captains and
budgets with:

- official mode owns captains and budgets after roster finalization;
- curated mode owns them during preseason;
- roles and removals always come from the export;
- official rows are cached by season for offline use;
- `budgets.json` is the explicit final override.

Include both commands:

```powershell
python ld2l_scout.py --mock --roster official
python ld2l_scout.py --mock --roster curated
```

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with no tracebacks or warnings.

- [ ] **Step 4: Regenerate the dashboard**

Run the normal online scout command used by the project:

```powershell
python ld2l_scout.py
```

Expected: `LD2L_S22_Scouting.html` is rewritten with current website data,
official roster cache, hardened export logic, and the roster-source indicator.

- [ ] **Step 5: Verify official mock loading without starting an auction**

Run a short diagnostic through the project Python environment:

```powershell
python -c "from scout.mockdraft import _load_pool; label,pool,caps,_=_load_pool(53,False,'official'); print(label); print([(c['captain'],c['budget']) for c in caps]); print('champ-in-pool', any(p['name'].casefold()=='champ0044' for p in pool))"
```

Expected: current official budgets are printed and
`champ-in-pool False`.

- [ ] **Step 6: Inspect the final diff without altering user state**

Run:

```powershell
git status --short
git diff --check
git diff -- captains.json
```

Expected: `captains.json` remains the user's separate export change; no
implementation step overwrote it.

- [ ] **Step 7: Commit implementation and regenerated dashboard**

Stage only implementation, tests, docs, launcher, plan, and regenerated
dashboard. Do not stage `captains.json`:

```powershell
git add scout/captains.py scout/mockdraft.py scout/cli.py scout/broadcast.py scout/report_html.py tests/test_regressions.py MockDraft.vbs README.md LD2L_S22_Scouting.html docs/superpowers/plans/2026-07-25-official-mock-roster-source.md
git commit -m "Use finalized official roster in mock drafts"
```
