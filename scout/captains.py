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

from .user_config import load_budget_overrides

OVERRIDES_FILE = "budgets.json"


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
