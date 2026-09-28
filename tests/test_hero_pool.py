from scout.hero_pool import build_hero_pool
from scout.hero_attack import attack_type

NOW = 1_700_000_000
DAY = 86400


def _pub_row(hero, at=NOW - DAY, win=True, k=8, d=2, a=10, gpm=550, position=None):
    return {
        "hero": hero, "at": at, "win": win, "kills": k, "deaths": d, "assists": a,
        "gpm": gpm, "position": position,
    }


def test_shrinkage_keeps_a_thin_perfect_record_below_a_deep_one():
    heroes = [
        {"id": 1, "name": "Thin", "games": 1, "wins": 1, "last": NOW, "primaryPosition": 1},
        {"id": 2, "name": "Deep", "games": 30, "wins": 15, "last": NOW, "primaryPosition": 1},
    ]
    result = build_hero_pool(heroes, [], [], [])
    by_id = {row["id"]: row for row in result["heroes"]}
    # 1-0 shrinks hard toward 50%; 30-15 (50% on a real sample) should not be
    # displaced by a single lucky lifetime win.
    assert by_id[2]["score"] >= by_id[1]["score"] - 0.05


def test_recent_games_are_weighted_double_in_the_score():
    lifetime_only = build_hero_pool(
        [{"id": 1, "name": "H", "games": 10, "wins": 5, "last": NOW}], [], [], [],
    )
    with_recent_wins = build_hero_pool(
        [{"id": 1, "name": "H", "games": 10, "wins": 5, "last": NOW}],
        [_pub_row(1, win=True) for _ in range(5)],
        [], [], now=NOW,
    )
    a = lifetime_only["heroes"][0]["score"]
    b = with_recent_wins["heroes"][0]["score"]
    assert b > a


def test_comfort_top_five_are_excluded_from_gems():
    heroes = [
        {"id": i, "name": f"H{i}", "games": 50, "wins": 30, "last": NOW}
        for i in range(1, 6)
    ]
    # A sixth hero with a strong recent record that would otherwise qualify.
    pub_rows = [_pub_row(6, win=True) for _ in range(6)]
    result = build_hero_pool(heroes, pub_rows, [], [], now=NOW)
    comfort_ids = {row["id"] for row in result["heroes"] if "comfort" in row["tags"]}
    assert comfort_ids == {1, 2, 3, 4, 5}
    gem_ids = {row["id"] for row in result["gems"]}
    assert gem_ids.isdisjoint(comfort_ids)


def test_hero_with_two_official_games_is_excluded_from_gems():
    heroes = [{"id": 9, "name": "Gemmy", "games": 8, "wins": 6, "last": NOW}]
    pub_rows = [_pub_row(9, win=True) for _ in range(6)]
    official_rows = [
        {"hero_id": 9, "result": "W"},
        {"hero_id": 9, "result": "L"},
    ]
    result = build_hero_pool(heroes, pub_rows, official_rows, [])
    assert not any(row["id"] == 9 for row in result["gems"])


def test_stale_hero_is_excluded_from_gems():
    heroes = [{
        "id": 10, "name": "Stale", "games": 20, "wins": 14,
        "last": NOW - 400 * DAY,
    }]
    result = build_hero_pool(heroes, [], [], [], now=NOW)
    row = next(r for r in result["heroes"] if r["id"] == 10)
    assert "stale" in row["tags"]
    assert not any(g["id"] == 10 for g in result["gems"])


def test_kda_delta_uses_same_position_baseline():
    # Baseline overall KDA is dragged down by weak support games; this hero's
    # own position (2) baseline is much better, so the delta should be small,
    # not the large gap you'd get comparing against the whole-account average.
    pub_rows = (
        [_pub_row(1, k=1, d=10, a=1, position=5) for _ in range(5)]  # bad pos5 games
        + [_pub_row(2, k=10, d=2, a=10, position=2) for _ in range(3)]  # strong pos2
    )
    result = build_hero_pool([], pub_rows, [], [], now=NOW)
    hero2 = next(r for r in result["heroes"] if r["id"] == 2)
    assert hero2["recent"]["kdaDelta"] is not None
    assert abs(hero2["recent"]["kdaDelta"]) < 2


def test_league_only_tag_when_esports_share_dwarfs_pub_share():
    heroes = [{"id": 3, "name": "LeagueOnly", "games": 4, "wins": 2, "last": NOW}]
    esports_heroes = [{"id": 3, "games": 8, "wins": 5}]
    result = build_hero_pool(heroes, [], [], esports_heroes)
    row = next(r for r in result["heroes"] if r["id"] == 3)
    assert "league-only" in row["tags"]


def test_gem_reason_string_has_no_em_dash():
    # Five deep "comfort" heroes (huge lifetime sample) so the sixth hero,
    # with a strong but much smaller recent record, is the one that can
    # actually surface as a hidden gem rather than getting swept into
    # comfort just for being the only hero in the pool.
    heroes = [
        {"id": i, "name": f"Comfort{i}", "games": 200, "wins": 100, "last": NOW}
        for i in range(1, 6)
    ] + [{"id": 11, "name": "Gem", "games": 41, "wins": 30, "last": NOW - 10 * DAY}]
    pub_rows = (
        [_pub_row(i, win=(j == 0), position=None) for i in range(1, 6) for j in range(2)]
        + [_pub_row(11, win=i % 3 != 0, position=3) for i in range(9)]
    )
    result = build_hero_pool(heroes, pub_rows, [], [], now=NOW)
    assert result["gems"], "expected at least one gem for this fixture"
    gem_ids = {gem["id"] for gem in result["gems"]}
    assert 11 in gem_ids
    for gem in result["gems"]:
        assert "—" not in gem["reason"]
        assert "reason" in gem


def test_no_gems_returns_empty_list_not_an_error():
    result = build_hero_pool([], [], [], [])
    assert result["gems"] == []
    assert result["heroes"] == []
    assert result["pubWindowDays"] == 180


def test_attack_type_win_rates_use_each_players_picked_hero():
    heroes = [
        {"id": 1, "name": "Anti-Mage", "games": 10, "wins": 6, "last": NOW},
        {"id": 6, "name": "Drow Ranger", "games": 20, "wins": 8, "last": NOW},
    ]
    pubs = [
        _pub_row(1, win=True), _pub_row(1, win=False),
        _pub_row(6, win=True), _pub_row(6, win=True),
        _pub_row(6, win=False),
        _pub_row(6, at=NOW - 181 * DAY, win=True),
        _pub_row(999, win=True),  # unknown heroes are not guessed as melee
    ]
    result = build_hero_pool(heroes, pubs, [], [], now=NOW)
    split = result["attackSplit"]
    assert split["melee"]["recent"] == {"games": 2, "wins": 1, "winrate": 50.0}
    assert split["ranged"]["recent"] == {"games": 3, "wins": 2, "winrate": 66.7}
    assert split["melee"]["lifetime"] == {"games": 10, "wins": 6, "winrate": 60.0}
    assert split["ranged"]["lifetime"] == {"games": 20, "wins": 8, "winrate": 40.0}
    by_id = {row["id"]: row for row in result["heroes"]}
    assert by_id[1]["attackType"] == "Melee"
    assert by_id[6]["attackType"] == "Ranged"
    assert attack_type(999) is None
