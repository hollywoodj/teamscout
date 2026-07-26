"""Hero -> position priors.

OpenDota's per-match `lane_role` only distinguishes Safe / Mid / Off / Jungle.
It cannot tell a pos 1 from the pos 5 standing next to them, nor a pos 3 from
the pos 4 rotating through the offlane. The hero played is the only signal in
the free-tier data that separates them, so this table encodes, for each hero,
the positions it is actually played at in pubs — ordered most common first.

Ordered tuples rather than hand-written weight vectors: a curated ordering is
far easier to audit and correct than 5 floats per hero, and POS_DECAY turns the
ordering into weights consistently. `(1,)` = essentially only ever a carry;
`(4, 1)` = usually a soft support, sometimes a carry.

Names are carried alongside the ids purely so `audit_names()` can catch a
mistyped id. They are not used for lookup, and they track heroes.HERO_FALLBACK
rather than live OpenDota: Valve renames heroes (Outworld Devourer /
Destroyer, Ringmaster / Ring Master) often enough that comparing against the
live constants reports renames as drift. Spelling differences are cosmetic —
only a name pointing at an entirely different hero means a real id error.

Positions are the standard 1-5: 1 safelane carry, 2 mid, 3 offlane,
4 soft/roaming support, 5 hard support.
"""

# Weight given to the 1st, 2nd, 3rd... listed position. Truncated to the length
# of each hero's tuple and renormalised, so a 1-entry hero gets the full 1.0.
POS_DECAY = (0.62, 0.26, 0.12)

# hero_id -> (display name, (positions, most common first))
HERO_POS = {
    1: ("Anti-Mage", (1,)),
    2: ("Axe", (3,)),
    3: ("Bane", (5,)),
    4: ("Bloodseeker", (1, 3)),
    5: ("Crystal Maiden", (5,)),
    6: ("Drow Ranger", (1,)),
    7: ("Earthshaker", (4, 5)),
    8: ("Juggernaut", (1,)),
    9: ("Mirana", (4, 1)),
    10: ("Morphling", (1,)),
    11: ("Shadow Fiend", (2,)),
    12: ("Phantom Lancer", (1,)),
    13: ("Puck", (2,)),
    14: ("Pudge", (4, 3)),
    15: ("Razor", (2, 3)),
    16: ("Sand King", (3, 4)),
    17: ("Storm Spirit", (2,)),
    18: ("Sven", (1, 3)),
    19: ("Tiny", (2, 4, 3)),
    20: ("Vengeful Spirit", (5, 4)),
    21: ("Windranger", (2, 4)),
    22: ("Zeus", (2,)),
    23: ("Kunkka", (2, 3, 1)),
    25: ("Lina", (2, 4)),
    26: ("Lion", (5,)),
    27: ("Shadow Shaman", (5,)),
    28: ("Slardar", (3,)),
    29: ("Tidehunter", (3,)),
    30: ("Witch Doctor", (5,)),
    31: ("Lich", (5,)),
    32: ("Riki", (4, 1)),
    33: ("Enigma", (4, 3)),
    34: ("Tinker", (2,)),
    35: ("Sniper", (1, 2)),
    36: ("Necrophos", (2, 3)),
    37: ("Warlock", (5,)),
    38: ("Beastmaster", (3,)),
    39: ("Queen of Pain", (2,)),
    40: ("Venomancer", (5, 3)),
    41: ("Faceless Void", (1,)),
    42: ("Wraith King", (1, 3)),
    43: ("Death Prophet", (2, 3)),
    44: ("Phantom Assassin", (1,)),
    45: ("Pugna", (2, 5)),
    46: ("Templar Assassin", (2, 1)),
    47: ("Viper", (2, 3, 1)),
    48: ("Luna", (1,)),
    49: ("Dragon Knight", (2, 3)),
    50: ("Dazzle", (5,)),
    51: ("Clockwerk", (4, 3)),
    52: ("Leshrac", (2,)),
    53: ("Nature's Prophet", (3, 2, 1)),
    54: ("Lifestealer", (1,)),
    55: ("Dark Seer", (3,)),
    56: ("Clinkz", (1,)),
    57: ("Omniknight", (5, 3)),
    58: ("Enchantress", (5, 4)),
    59: ("Huskar", (1, 2)),
    60: ("Night Stalker", (3, 4)),
    61: ("Broodmother", (3, 1)),
    62: ("Bounty Hunter", (4,)),
    63: ("Weaver", (1, 5)),
    64: ("Jakiro", (5,)),
    65: ("Batrider", (4, 3, 2)),
    66: ("Chen", (4,)),
    67: ("Spectre", (1,)),
    68: ("Ancient Apparition", (5,)),
    69: ("Doom", (3,)),
    70: ("Ursa", (1, 3)),
    71: ("Spirit Breaker", (4,)),
    72: ("Gyrocopter", (1,)),
    73: ("Alchemist", (1, 3)),
    74: ("Invoker", (2,)),
    75: ("Silencer", (5, 2)),
    76: ("Outworld Destroyer", (2, 1)),
    77: ("Lycan", (1, 3)),
    78: ("Brewmaster", (3,)),
    79: ("Shadow Demon", (5,)),
    80: ("Lone Druid", (1, 3)),
    81: ("Chaos Knight", (1,)),
    82: ("Meepo", (2, 1)),
    83: ("Treant Protector", (5,)),
    84: ("Ogre Magi", (5, 4)),
    85: ("Undying", (5, 3)),
    86: ("Rubick", (4, 5)),
    87: ("Disruptor", (5,)),
    88: ("Nyx Assassin", (4,)),
    89: ("Naga Siren", (1, 5)),
    90: ("Keeper of the Light", (5, 4)),
    91: ("Io", (5,)),
    92: ("Visage", (4, 3)),
    93: ("Slark", (1,)),
    94: ("Medusa", (1,)),
    95: ("Troll Warlord", (1,)),
    96: ("Centaur Warrunner", (3,)),
    97: ("Magnus", (3, 4)),
    98: ("Timbersaw", (3, 2)),
    99: ("Bristleback", (3, 1)),
    100: ("Tusk", (4,)),
    101: ("Skywrath Mage", (5, 4)),
    102: ("Abaddon", (5, 3, 1)),
    103: ("Elder Titan", (4, 5)),
    104: ("Legion Commander", (3, 4)),
    105: ("Techies", (4, 5)),
    106: ("Ember Spirit", (2,)),
    107: ("Earth Spirit", (4,)),
    108: ("Underlord", (3,)),
    109: ("Terrorblade", (1,)),
    110: ("Phoenix", (4, 5)),
    111: ("Oracle", (5,)),
    112: ("Winter Wyvern", (5,)),
    113: ("Arc Warden", (1, 2)),
    114: ("Monkey King", (1, 3, 4)),
    119: ("Dark Willow", (4, 5)),
    120: ("Pangolier", (4, 2, 3)),
    121: ("Grimstroke", (5,)),
    123: ("Hoodwink", (4, 2)),
    126: ("Void Spirit", (2,)),
    128: ("Snapfire", (4, 5)),
    129: ("Mars", (3,)),
    131: ("Ringmaster", (4, 5)),
    135: ("Dawnbreaker", (3, 4, 1)),
    136: ("Marci", (4, 3, 1)),
    137: ("Primal Beast", (3, 4)),
    138: ("Muerta", (1, 2)),
    145: ("Kez", (1, 2)),
}


def _weights(positions):
    """Ordered position tuple -> {pos: weight} summing to 1."""
    decay = POS_DECAY[:len(positions)]
    # tuples longer than POS_DECAY fall back to the smallest decay for the tail
    if len(positions) > len(POS_DECAY):
        decay = decay + (POS_DECAY[-1],) * (len(positions) - len(POS_DECAY))
    total = sum(decay)
    return {pos: w / total for pos, w in zip(positions, decay)}


# hero_id -> {pos: weight}, precomputed once.
POS_WEIGHTS = {hid: _weights(poss) for hid, (_, poss) in HERO_POS.items()}


def affinity(hero_games):
    """{hero_id: games} -> ({pos: share}, games_counted).

    Shares sum to 1 across the five positions and describe where this player's
    hero pool actually sits. Heroes missing from the table are skipped rather
    than guessed at, and games_counted reports how much of the pool was usable
    so the caller can shrink a thin signal.
    """
    shares = {p: 0.0 for p in range(1, 6)}
    counted = 0
    for hid, games in (hero_games or {}).items():
        weights = POS_WEIGHTS.get(hid)
        if not weights or games <= 0:
            continue
        counted += games
        for pos, w in weights.items():
            shares[pos] += w * games
    if not counted:
        return {p: 0.0 for p in range(1, 6)}, 0
    return {p: v / counted for p, v in shares.items()}, counted


def top_heroes_for(hero_games, pos, hero_map=None, limit=3):
    """The player's most-played heroes that read as `pos` — for the why-text."""
    scored = []
    for hid, games in (hero_games or {}).items():
        w = POS_WEIGHTS.get(hid, {}).get(pos, 0)
        if w >= 0.25 and games > 0:
            scored.append((w * games, hid, games))
    scored.sort(reverse=True)
    out = []
    for _, hid, games in scored[:limit]:
        name = hero_map.name(hid) if hero_map else HERO_POS[hid][0]
        out.append(f"{name} ({games}g)")
    return out


def audit_names(hero_map):
    """Names in this table that no longer match OpenDota's, i.e. id drift."""
    drift = []
    for hid, (name, _) in HERO_POS.items():
        live = hero_map.name(hid)
        if live and not live.startswith("Hero#") and live != name:
            drift.append((hid, name, live))
    return drift
