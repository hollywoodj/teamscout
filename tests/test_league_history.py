from scout.cache import Cache
from scout.league_history import (
    league_history_for, refresh_league_history, unavailable_history,
)


class FakeOD:
    """Enough of OpenDota for refresh_league_history: no network, no rate
    limiting, just call counting."""

    def __init__(self, matches_by_sid=None, match_payloads=None,
                 leagues=None, league_ids=None):
        self.calls = 0
        self.matches_by_sid = matches_by_sid or {}
        self.match_payloads = match_payloads or {}
        self.leagues = leagues or {}
        self.league_ids = league_ids or {}

    def matches(self, sid, **params):
        self.calls += 1
        return self.matches_by_sid.get(sid, [])

    def match(self, match_id):
        self.calls += 1
        return self.match_payloads.get(match_id)

    def league(self, league_id):
        self.calls += 1
        return self.leagues.get(league_id, {})

    def league_match_ids(self, league_id):
        self.calls += 1
        return self.league_ids.get(league_id, [])


class Heroes:
    def name(self, hero_id):
        return f"Hero {hero_id}"


def _lobby_row(match_id, start_time, hero_id=1, radiant=True, win=True, **extra):
    row = {
        "match_id": match_id, "start_time": start_time, "hero_id": hero_id,
        "player_slot": 0 if radiant else 128,
        "radiant_win": win if radiant else not win,
        "kills": 5, "deaths": 2, "assists": 8,
        "gold_per_min": 500, "xp_per_min": 600, "duration": 1800,
        "game_mode": 1, "lane_role": 1, "last_hits": 100,
    }
    row.update(extra)
    return row


def test_league_expansion_resolves_sibling_matches_without_detail_calls(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(
        matches_by_sid={1: [
            _lobby_row(100, 1000, win=True),
            _lobby_row(101, 900, win=False),
        ]},
        match_payloads={100: {"leagueid": 555}},
        leagues={555: {"name": "Learn Dota 2 League", "tier": "excluded"}},
        league_ids={555: [100, 101]},
    )
    refresh_league_history(od, cache, [1])
    # Only one /matches/{id} call (for 100); 101 resolved for free via the
    # league's own match id list.
    assert od.calls == 4  # matches() + match(100) + league(555) + league_match_ids(555)

    history = league_history_for(cache, 1, Heroes(), now=2000)
    assert history["status"] == "ok"
    assert history["games"] == 2
    assert history["wins"] == 1
    assert history["winrate"] == 50.0
    assert history["leagues"] == [{
        "id": 555, "name": "Learn Dota 2 League", "tier": "excluded",
        "games": 2, "wins": 1, "first": 900, "latest": 1000,
    }]


def test_leagueid_zero_is_stored_and_counted_as_inhouse(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(
        matches_by_sid={2: [_lobby_row(200, 1000)]},
        match_payloads={200: {"leagueid": 0}},
    )
    refresh_league_history(od, cache, [2])
    history = league_history_for(cache, 2, Heroes(), now=2000)
    assert history["inhouse"] == 1
    assert history["unresolved"] == 0
    assert history["games"] == 0


def test_none_response_leaves_match_unresolved_not_zero(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(
        matches_by_sid={3: [_lobby_row(300, 1000)]},
        match_payloads={},  # od.match(300) returns None
    )
    refresh_league_history(od, cache, [3])
    history = league_history_for(cache, 3, Heroes(), now=2000)
    assert history["unresolved"] == 1
    assert history["inhouse"] == 0
    assert history["games"] == 0
    # Not marked 0: a later run should still try to resolve it.
    index = cache.get_blob("league_match_index_v1")
    assert "300" not in index["matches"]


def test_budget_stops_detail_calls(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(
        matches_by_sid={
            4: [_lobby_row(400, 1000)],
            5: [_lobby_row(500, 900)],
        },
        match_payloads={400: {"leagueid": 111}, 500: {"leagueid": 222}},
        leagues={111: {"name": "A"}, 222: {"name": "B"}},
        league_ids={111: [400], 222: [500]},
    )
    refresh_league_history(od, cache, [4, 5], budget=1)
    h4 = league_history_for(cache, 4, Heroes(), now=2000)
    h5 = league_history_for(cache, 5, Heroes(), now=2000)
    resolved = [h for h in (h4, h5) if h["unresolved"] == 0]
    unresolved = [h for h in (h4, h5) if h["unresolved"] == 1]
    assert len(resolved) == 1
    assert len(unresolved) == 1


def test_six_month_window_and_heroes_counted_ticketed_only(tmp_path):
    cache = Cache(root=str(tmp_path))
    now = 100 * 86400
    cache.set_section(6, "lobby_matches_v1", [
        _lobby_row(600, now - 10 * 86400, hero_id=1, win=True),   # recent, ticketed
        _lobby_row(601, now - 200 * 86400, hero_id=1, win=False),  # old, ticketed
        _lobby_row(602, now - 5 * 86400, hero_id=2, win=True),     # recent, inhouse
    ])
    cache.set_blob("league_match_index_v1", {
        "matches": {"600": 777, "601": 777, "602": 0},
        "leagues": {"777": {"name": "LD2L", "tier": "excluded", "ids_fetched_at": 0}},
    })
    history = league_history_for(cache, 6, Heroes(), now=now)
    assert history["games"] == 2
    assert history["wins"] == 1
    assert history["winrate"] == 50.0
    assert history["sixMonth"] == {"games": 1, "wins": 1, "winrate": 100.0}
    assert history["inhouse"] == 1
    assert history["heroes"] == [{"id": 1, "games": 2, "wins": 1}]


def test_leagues_sorted_newest_first(tmp_path):
    cache = Cache(root=str(tmp_path))
    cache.set_section(7, "lobby_matches_v1", [
        _lobby_row(700, 1000),
        _lobby_row(701, 5000),
    ])
    cache.set_blob("league_match_index_v1", {
        "matches": {"700": 111, "701": 222},
        "leagues": {
            "111": {"name": "Older League"},
            "222": {"name": "Newer League"},
        },
    })
    history = league_history_for(cache, 7, Heroes(), now=10000)
    assert [row["name"] for row in history["leagues"]] == ["Newer League", "Older League"]


def test_unavailable_shape_when_no_section_cached(tmp_path):
    cache = Cache(root=str(tmp_path))
    assert league_history_for(cache, 999, Heroes()) == unavailable_history()


def test_failed_lobby_fetch_is_not_cached_as_empty(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(matches_by_sid={1: None})
    refresh_league_history(od, cache, [1], budget=0)
    assert league_history_for(cache, 1, Heroes())["status"] == "unavailable"


def test_seeded_league_gets_name_and_siblings(tmp_path):
    cache = Cache(root=str(tmp_path))
    od = FakeOD(
        matches_by_sid={1: [_lobby_row(300, 1000), _lobby_row(301, 900)]},
        leagues={19389: {"name": "Learn Dota 2 League", "tier": "excluded"}},
        league_ids={19389: [300, 301]},
    )
    refresh_league_history(od, cache, [1], budget=0, bbc_match_ids=[300])
    history = league_history_for(cache, 1, Heroes())
    assert history["games"] == 2 and history["unresolved"] == 0
    assert history["leagues"][0]["name"] == "Learn Dota 2 League"
