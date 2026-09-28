"""Base attack type for Dota heroes, keyed by OpenDota hero ID.

Source: https://github.com/odota/dotaconstants/blob/master/build/heroes.json
Unknown future heroes are left unclassified instead of guessed.
"""

from .heroes import HERO_FALLBACK


# The remaining known heroes use melee attacks. Troll Warlord and Lone Druid
# use their base form; temporary form switches do not change this grouping.
RANGED_HERO_IDS = frozenset({
    3, 5, 6, 9, 10, 11, 13, 15, 17, 20, 21, 22, 25, 26, 27, 30, 31,
    33, 34, 35, 36, 37, 39, 40, 43, 45, 46, 47, 48, 50, 52, 53, 56,
    58, 59, 63, 64, 65, 66, 68, 72, 74, 75, 76, 79, 80, 86, 87, 90,
    91, 92, 94, 95, 101, 105, 110, 111, 112, 113, 119, 121, 123,
    128, 131, 138,
})
KNOWN_HERO_IDS = frozenset(HERO_FALLBACK) | {155}


def attack_type(hero_id):
    """Return 'Ranged', 'Melee', or None for an unknown hero ID."""
    try:
        hero_id = int(hero_id)
    except (TypeError, ValueError):
        return None
    if hero_id not in KNOWN_HERO_IDS:
        return None
    return "Ranged" if hero_id in RANGED_HERO_IDS else "Melee"
