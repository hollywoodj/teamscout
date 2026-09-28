"""Dota rank-tier labels and optional Discord application emoji tokens."""

MEDAL_NAMES = {
    1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
    5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal",
}


def medal_tier(value):
    """Return a supported Dota rank tier, or None for missing/bad data."""
    try:
        tier = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool):
        return None
    if tier >= 80 and tier // 10 == 8:
        return 80
    if 1 <= tier // 10 <= 7 and 1 <= tier % 10 <= 5:
        return tier
    return None


def medal_label(value):
    tier = medal_tier(value)
    if tier is None:
        return None
    name = MEDAL_NAMES[tier // 10]
    return name if tier == 80 else f"{name} {tier % 10}"


def medal_prefix(value, emoji_map=None):
    tier = medal_tier(value)
    if tier is None or not emoji_map:
        return ""
    token = emoji_map.get(str(tier)) or emoji_map.get(tier)
    return f"{token} " if token else ""
