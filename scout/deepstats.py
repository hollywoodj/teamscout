"""Cached parsed-match enrichment for exact recent lane and deward evidence."""


DEEP_MATCH_LIMIT = 10
MINUTE_TEN_INDEX = 10


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _minute_ten(values):
    if not isinstance(values, list) or len(values) <= MINUTE_TEN_INDEX:
        return None
    return _int_or_none(values[MINUTE_TEN_INDEX])


def _same_side(slot_a, slot_b):
    return (slot_a < 128) == (slot_b < 128)


def _completed_match_payload(payload):
    return (
        isinstance(payload, dict)
        and bool(payload.get("version"))
        and isinstance(payload.get("players"), list)
    )


def _target_player(players, account_id, target_slot):
    for player in players:
        if _int_or_none(player.get("account_id")) == int(account_id):
            return player
    if target_slot is not None:
        for player in players:
            if _int_or_none(player.get("player_slot")) == int(target_slot):
                return player
    return None


def player_sample(match, account_id, target_slot=None):
    """Return the small immutable slice needed to scout one player.

    The physical-lane totals include every non-roaming player assigned to the
    target's map lane. This makes safelane-versus-offlane comparisons line up
    across Radiant and Dire rather than comparing lane-role labels.
    """
    match = match if isinstance(match, dict) else {}
    players = match.get("players") if isinstance(match.get("players"), list) else []
    target = _target_player(players, account_id, target_slot)
    base = {
        "match_id": _int_or_none(match.get("match_id")),
        "start_time": _int_or_none(match.get("start_time")),
        "duration": _int_or_none(match.get("duration")),
        "parsed": False,
        "player_slot": _int_or_none(target_slot),
        "lane": None,
        "lane_role": None,
        "is_roaming": None,
        "gold10": None,
        "xp10": None,
        "ally_lane_gold10": None,
        "enemy_lane_gold10": None,
        "ally_lane_xp10": None,
        "enemy_lane_xp10": None,
        "observer_kills": None,
        "sentry_kills": None,
    }
    if target is None:
        return base

    slot = _int_or_none(target.get("player_slot"))
    lane = _int_or_none(target.get("lane"))
    gold10 = _minute_ten(target.get("gold_t"))
    xp10 = _minute_ten(target.get("xp_t"))
    base.update({
        "player_slot": slot,
        "lane": lane,
        "lane_role": _int_or_none(target.get("lane_role")),
        "is_roaming": target.get("is_roaming"),
        "gold10": gold10,
        "xp10": xp10,
    })

    parsed = bool(match.get("version")) and gold10 is not None and xp10 is not None
    if not parsed:
        return base
    base["parsed"] = True
    base["observer_kills"] = _int_or_none(target.get("observer_kills"))
    base["sentry_kills"] = _int_or_none(target.get("sentry_kills"))

    if lane not in (1, 2, 3) or slot is None or bool(target.get("is_roaming")):
        return base

    totals = {
        "ally_lane_gold10": 0,
        "enemy_lane_gold10": 0,
        "ally_lane_xp10": 0,
        "enemy_lane_xp10": 0,
    }
    counts = {"ally": 0, "enemy": 0}
    for player in players:
        player_slot = _int_or_none(player.get("player_slot"))
        if (
            player_slot is None
            or _int_or_none(player.get("lane")) != lane
            or bool(player.get("is_roaming"))
        ):
            continue
        player_gold = _minute_ten(player.get("gold_t"))
        player_xp = _minute_ten(player.get("xp_t"))
        if player_gold is None or player_xp is None:
            continue
        side = "ally" if _same_side(slot, player_slot) else "enemy"
        counts[side] += 1
        totals[f"{side}_lane_gold10"] += player_gold
        totals[f"{side}_lane_xp10"] += player_xp

    if not counts["ally"] or not counts["enemy"]:
        return base
    base.update(totals)
    return base


def _newest_matches(matches, limit):
    valid = [
        match for match in (matches or [])
        if isinstance(match, dict) and _int_or_none(match.get("match_id")) is not None
    ]
    valid.sort(
        key=lambda match: (
            _int_or_none(match.get("start_time")) or 0,
            _int_or_none(match.get("match_id")) or 0,
        ),
        reverse=True,
    )
    seen = set()
    selected = []
    for match in valid:
        match_id = _int_or_none(match.get("match_id"))
        if match_id in seen:
            continue
        seen.add(match_id)
        selected.append(match)
        if len(selected) >= limit:
            break
    return selected


def load_player_deep_stats(
    od,
    cache,
    player,
    matches,
    offline=False,
    limit=DEEP_MATCH_LIMIT,
):
    """Load up to ``limit`` newest full matches and extract one player sample."""
    account_id = int(player["steam32"])
    samples = []
    for summary in _newest_matches(matches, limit):
        match_id = int(summary["match_id"])
        payload = cache.get_match(match_id)
        if not offline and not _completed_match_payload(payload):
            fetched = od.match(match_id)
            if isinstance(fetched, dict):
                payload = fetched
                if _completed_match_payload(fetched):
                    cache.set_match(match_id, fetched)
        if not isinstance(payload, dict):
            continue
        samples.append(
            player_sample(
                payload,
                account_id,
                target_slot=summary.get("player_slot"),
            )
        )
    return samples
