"""LD2L weekly schedule parsing and cache. No network."""

import json

import requests

from scout import config, ld2l
from scout.team_scout import _schedule_matchups


def _series(week, home_id, home, away_id, away, score="0 - 0"):
    return (
        f"<tr class=\"clickable\" onclick=\"ld2l.expandSeries('53-{week}-{home_id}-{away_id}');\">"
        f'<td><div class="team-name" data-title="{home}"><a href="/teams/about/{home_id}">{home}</a></div></td>'
        f'<td style="width: 40px;">{score}</td>'
        f'<td><div class="team-name" data-title="{away}"><a href="/teams/about/{away_id}">{away}</a></div></td></tr>'
        f'<tr data-series="53-{week}-{home_id}-{away_id}" style="display: none;"><td colspan="3">'
        f'<div>Game 1 not yet played [<a href="/matches/1">Link</a>]</div></td></tr>'
    )


SCHEDULE_HTML = (
    '<div class="ld2l-season-body">'
    '<h3>Week 7</h3><table class="ld2l-table"><tbody>'
    + _series(7, 432, "LineDetail.com", 428, "Lane Tyrants")
    + _series(7, 435, "posh goldfinch", 434, "The Democratic People&#39;s Republic of Kyrix")
    + '</tbody></table><h3>Week 6</h3><table class="ld2l-table"><tbody>'
    + _series(6, 432, "LineDetail.com", 435, "posh goldfinch", "2 - 0")
    + "</tbody></table></div>"
)


def test_parse_schedule_splits_weeks_and_unescapes_names():
    weeks = ld2l.parse_schedule(SCHEDULE_HTML)
    assert [row["week"] for row in weeks] == [7, 6]
    assert weeks[0]["series"][1] == {
        "homeId": "435", "home": "posh goldfinch",
        "awayId": "434", "away": "The Democratic People's Republic of Kyrix",
        "score": "0 - 0",
    }
    assert weeks[1]["series"][0]["score"] == "2 - 0"


def test_current_week_is_the_highest_number_not_the_first_listed():
    weeks = [{"week": 6, "series": [1]}, {"week": 7, "series": [2]}]
    assert ld2l.current_week(weeks)["week"] == 7
    assert ld2l.current_week([]) is None


def test_load_schedule_keeps_cache_when_fetch_fails(tmp_path, monkeypatch):
    path = tmp_path / "schedule.json"
    cached = {"seasonId": 53, "week": 6, "series": [{"home": "A", "away": "B"}], "fetchedAt": 0}
    path.write_text(json.dumps(cached), encoding="utf-8")

    def boom(_season):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(ld2l, "fetch_schedule", boom)
    assert ld2l.load_schedule(53, path=str(path))["week"] == 6


def test_load_schedule_ignores_an_empty_page(tmp_path, monkeypatch):
    path = tmp_path / "schedule.json"
    cached = {"seasonId": 53, "week": 6, "series": [{"home": "A", "away": "B"}], "fetchedAt": 0}
    path.write_text(json.dumps(cached), encoding="utf-8")
    monkeypatch.setattr(ld2l, "fetch_schedule",
                        lambda season: {"seasonId": season, "week": None, "series": [], "fetchedAt": 1})
    assert ld2l.load_schedule(53, path=str(path))["week"] == 6


def test_load_schedule_uses_fresh_cache_without_fetching(tmp_path, monkeypatch):
    path = tmp_path / "schedule.json"
    import time
    fresh = {"seasonId": 53, "week": 7, "series": [{"home": "A", "away": "B"}], "fetchedAt": time.time()}
    path.write_text(json.dumps(fresh), encoding="utf-8")

    def fail(_season):
        raise AssertionError("fresh cache should not refetch")

    monkeypatch.setattr(ld2l, "fetch_schedule", fail)
    assert ld2l.load_schedule(53, path=str(path))["week"] == 7
    assert config.LD2L_SCHEDULE_CACHE_HOURS > 0


def test_refresh_schedule_reports_a_new_week(tmp_path, monkeypatch):
    path = tmp_path / "schedule.json"
    old = {"seasonId": 53, "week": 6, "series": [{"homeId": "1", "awayId": "2"}], "fetchedAt": 0}
    path.write_text(json.dumps(old), encoding="utf-8")
    new = {"seasonId": 53, "week": 7, "series": [{"homeId": "1", "awayId": "3"}], "fetchedAt": 1}
    monkeypatch.setattr(ld2l, "fetch_schedule", lambda season: dict(new))
    assert ld2l.refresh_schedule_if_new_week(53, path=str(path)) is True
    assert ld2l.refresh_schedule_if_new_week(53, path=str(path)) is False


def test_schedule_matchups_map_onto_posted_teams():
    teams = [
        {"key": "linedetailcom", "name": "LineDetail.com", "short": "LD", "captain": "Cap A"},
        {"key": "lanetyrants", "name": "Lane Tyrants", "short": "LT", "captain": "Cap B"},
    ]
    schedule = {"week": 7, "series": [
        {"home": "LineDetail.com", "away": "Lane Tyrants", "score": "0 - 0"},
        {"home": "Unknown Team", "away": "Lane Tyrants", "score": "0 - 0"},
    ]}
    rows = _schedule_matchups(schedule, teams, "LD2L Season 22")
    assert rows == [{
        "a": "LineDetail.com", "aShort": "LD", "aCaptain": "Cap A", "aKey": "linedetailcom",
        "b": "Lane Tyrants", "bShort": "LT", "bCaptain": "Cap B", "bKey": "lanetyrants",
        "week": 7, "label": "WEEK 7", "score": "0 - 0", "league": "LD2L Season 22",
    }]


def test_schedule_matchups_fall_back_when_nothing_maps():
    assert _schedule_matchups(None, [], "LD2L") is None
    assert _schedule_matchups({"week": 7, "series": [{"home": "X", "away": "Y"}]}, [], "LD2L") is None
