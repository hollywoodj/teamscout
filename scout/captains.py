"""Captains and their budgets, resolved in one place.

The season teams page (:func:`scout.ld2l.scrape_budgets`) yields one dict per
team — ``{captain, steam64, team_id, budget, unspent}``. Turning that into the
maps the dashboard, the read-only --live follower and the --mock auction all
need used to be re-derived in four different spots, each subtly different, with
the ``budgets.json`` override read in two of them. This module is the single
owner of those derivations and the override merge, so the shape has one home.

Nothing here touches the network; it only reshapes already-scraped team dicts
and reads the local ``budgets.json`` override file.
"""

import os

from . import config
from .user_config import load_budget_overrides

OVERRIDES_FILE = "budgets.json"


def normalized_name(value):
    """Canonical form for matching a team captain to a signup player."""
    return " ".join(str(value or "").split()).casefold()


def resolve_team_identities(teams, players):
    """Fill missing team Steam IDs from an unambiguous normalized name match.

    Rows that still cannot be identified are returned separately instead of
    being allowed to act as a bidder while their signup remains draftable.
    """
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
            row["steam64"] = (
                int(matches[0]["steam32"]) + config.STEAM64_OFFSET
            )
        resolved.append(row)
    return resolved, unresolved


def captain_map(teams):
    """``{str(team_id): captain}`` — skips teams with no id or no captain."""
    return {str(t["team_id"]): t["captain"]
            for t in teams if t.get("team_id") and t.get("captain")}


def budget_map(teams):
    """``{captain: budget}`` — skips rows with no captain name."""
    return {t["captain"]: t["budget"] for t in teams if t.get("captain")}


def _read_overrides(path):
    """Read budgets.json → ``(manual {captain: $}, error_msg | None)``.

    An absent file is not an error: ``({}, None)``. A malformed one returns
    ``({}, "<reason>")`` so the caller can warn and carry on, exactly as both
    call sites did inline before.
    """
    if not os.path.exists(path):
        return {}, None
    try:
        return load_budget_overrides(path), None
    except (ValueError, OSError) as e:
        return {}, str(e)


def resolve_budgets(teams, path=OVERRIDES_FILE):
    """Final ``{captain: budget}`` for the dashboard: scraped values with
    ``budgets.json`` layered on top.

    Returns ``(budgets, applied_count, error_msg)`` — the merged map, how many
    manual overrides applied, and any override-file error (``None`` if clean).
    """
    budgets = budget_map(teams)
    manual, err = _read_overrides(path)
    budgets.update(manual)
    return budgets, len(manual), err


def override_team_budgets(teams, path=OVERRIDES_FILE):
    """Layer ``budgets.json`` onto a list of team dicts **in place** (the mock's
    ``captains_raw``, whose budget lives on each row).

    Returns ``(applied_count, error_msg)``.
    """
    manual, err = _read_overrides(path)
    for t in teams:
        if t.get("captain") in manual:
            t["budget"] = manual[t["captain"]]
    return len(manual), err


def _valid_official_rows(rows):
    """Return copied official rows only when the whole response is usable."""
    if not rows:
        return []
    valid = [
        dict(row) for row in rows
        if row.get("captain")
        and row.get("steam64")
        and isinstance(row.get("budget"), int)
        and row["budget"] >= 0
    ]
    return valid if len(valid) == len(rows) else []


def load_official_teams(season, cache, offline=False, fetcher=None,
                        path=OVERRIDES_FILE):
    """Load the season's authoritative teams, preferring live data.

    A fully valid website response refreshes the season-scoped cache. Offline
    runs and failed/partial fetches reuse that last valid snapshot. Manual
    ``budgets.json`` entries are layered over either source after loading.
    """
    key = f"official_roster_s{season}"
    rows, source = [], "missing"

    if not offline:
        if fetcher is None:
            from .ld2l import scrape_budgets
            fetcher = scrape_budgets
        rows = _valid_official_rows(fetcher(season) or [])
        if rows:
            source = "website"
            cache.set_blob(key, rows)

    if not rows:
        rows = _valid_official_rows(cache.get_blob(key) or [])
        if rows:
            source = "cache"

    if not rows:
        return (
            [],
            "missing",
            "No valid official roster is available from the website or cache.",
        )

    _, error = override_team_budgets(rows, path=path)
    return rows, source, error
