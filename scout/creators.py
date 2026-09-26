"""Content-creator meta signal for the hero draft.

What BSJ, Speeed and the like put out this week is a leading indicator of the
pub meta at LD2L's brackets - often ahead of the win-rate tables. This module
turns a watchlist of creators (scout/meta_creators.json) into a per-hero
signal the draft bot and the hints can use:

  1. Each creator's public YouTube RSS feed (no API key, no scraping of the
     watch page) gives the newest ~15 uploads with title, date and the full
     description. Only meta-flavoured titles count ("tier", "best", "broken",
     "every role", "patch", ...).
  2. Hero names (full names and the usual shorthand: WK, PA, KotL, Veno...)
     are pulled out of the title + description, with the position when the
     same line says "carry", "mid", "offlane", "pos 4", "hard support"...
     Timestamped descriptions ("2:10 Offlane - Axe") work well for this.
  3. Hand entries in the same JSON file can add videos the feed missed or
     override the heroes for one (video id / URL is the join key), for the
     videos whose description names nothing.

The result is cached (cache/creator_videos.json) and refreshed by
`python ld2l_scout.py --refresh-creators`, by the Team Scout auto-refresh
pass, and by an online --herodraft start. Fully offline otherwise.
"""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from . import config
from .heroes import HERO_FALLBACK

CREATORS_FILE = os.path.join(os.path.dirname(__file__), "meta_creators.json")
CACHE_BLOB = "creator_videos"

ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA = "{http://search.yahoo.com/mrss/}"

DEFAULT_KEYWORDS = ("tier", "best", "broken", "meta", "patch", "every role",
                    "each role", "top ", "climb", "spam", "pick", "heroes",
                    "op ", "strongest")

# Shorthand the community actually types. Ambiguous two-letter tags that are
# also ordinary words or other acronyms (vs, wr, et, es, od...) are left out
# on purpose; the full name still matches.
ALIASES = {
    "wk": "Wraith King", "pa": "Phantom Assassin", "pl": "Phantom Lancer",
    "kotl": "Keeper of the Light", "keeper": "Keeper of the Light",
    "cm": "Crystal Maiden", "sf": "Shadow Fiend", "veno": "Venomancer",
    "alch": "Alchemist", "am": "Anti-Mage", "antimage": "Anti-Mage",
    "anti mage": "Anti-Mage", "ta": "Templar Assassin", "ck": "Chaos Knight",
    "np": "Nature's Prophet", "furion": "Nature's Prophet",
    "natures prophet": "Nature's Prophet", "prophet": "Nature's Prophet",
    "bs": "Bloodseeker", "sb": "Spirit Breaker", "bara": "Spirit Breaker",
    "ls": "Lifestealer", "naix": "Lifestealer", "tb": "Terrorblade",
    "dk": "Dragon Knight", "qop": "Queen of Pain", "wd": "Witch Doctor",
    "ww": "Winter Wyvern", "wyvern": "Winter Wyvern", "ld": "Lone Druid",
    "lc": "Legion Commander", "legion": "Legion Commander", "mk": "Monkey King",
    "bm": "Beastmaster", "brew": "Brewmaster", "timber": "Timbersaw",
    "bristle": "Bristleback", "centaur": "Centaur Warrunner",
    "tide": "Tidehunter", "ns": "Night Stalker", "void": "Faceless Void",
    "jugg": "Juggernaut", "morph": "Morphling", "necro": "Necrophos",
    "treant": "Treant Protector", "ogre": "Ogre Magi", "sk": "Sand King",
    "aa": "Ancient Apparition", "dp": "Death Prophet", "ember": "Ember Spirit",
    "storm": "Storm Spirit", "primal": "Primal Beast", "bh": "Bounty Hunter",
    "bounty": "Bounty Hunter", "sky": "Skywrath Mage", "skywrath": "Skywrath Mage",
    "lesh": "Leshrac", "clock": "Clockwerk", "shaker": "Earthshaker",
    "drow": "Drow Ranger", "troll": "Troll Warlord", "pango": "Pangolier",
    "dawn": "Dawnbreaker", "omni": "Omniknight", "willow": "Dark Willow",
    "seer": "Dark Seer", "bat": "Batrider", "brood": "Broodmother",
    "gyro": "Gyrocopter", "naga": "Naga Siren", "sd": "Shadow Demon",
    "shaman": "Shadow Shaman", "rasta": "Shadow Shaman", "venge": "Vengeful Spirit",
    "arc": "Arc Warden", "nyx": "Nyx Assassin", "ench": "Enchantress",
    "pit lord": "Underlord", "outworld devourer": "Outworld Destroyer",
    "od": "Outworld Destroyer", "wisp": "Io", "ringmaster": "Ringmaster",
    "ring master": "Ringmaster", "phoenix": "Phoenix", "mkb": None,
}

ROLE_WORDS = [
    (re.compile(r"\b(?:pos(?:ition)?\s*\.?\s*|p)1\b|\bcarry\b|\bsafe ?lane\b|\bhard carry\b"), (1,)),
    (re.compile(r"\b(?:pos(?:ition)?\s*\.?\s*|p)2\b|\bmid(?:lane|laner|s)?\b"), (2,)),
    (re.compile(r"\b(?:pos(?:ition)?\s*\.?\s*|p)3\b|\boff ?lane(?:r|rs)?\b"), (3,)),
    (re.compile(r"\b(?:pos(?:ition)?\s*\.?\s*|p)4\b|\bsoft support\b|\broam(?:er|ing)?\b"), (4,)),
    (re.compile(r"\b(?:pos(?:ition)?\s*\.?\s*|p)5\b|\bhard support\b"), (5,)),
    (re.compile(r"\bsupports?\b"), (4, 5)),
]


def _norm(text):
    return re.sub(r"[^a-z0-9']+", " ", str(text or "").lower()).strip()


def hero_matcher(hero_names):
    """Build (compiled regex, {matched token: canonical name}) once."""
    lookup = {}
    for name in hero_names:
        lookup[_norm(name)] = name
    by_canon = {_norm(v): v for v in hero_names}
    for alias, canon in ALIASES.items():
        if canon is None:
            continue
        canon_key = _norm(canon)
        if canon_key in by_canon:
            lookup.setdefault(_norm(alias), by_canon[canon_key])
    tokens = sorted(lookup, key=len, reverse=True)      # longest first
    pattern = re.compile(r"(?<![a-z0-9'])(" + "|".join(re.escape(t) for t in tokens)
                         + r")(?![a-z0-9'])")
    return pattern, lookup


def _roles_in(line):
    """Positions named on one line. The generic "support" word only counts
    when no specific seat (pos 4 / pos 5 / hard support...) is on the line."""
    roles = []
    for rx, pos in ROLE_WORDS[:-1]:
        if rx.search(line):
            for p in pos:
                if p not in roles:
                    roles.append(p)
    if not roles and ROLE_WORDS[-1][0].search(line):
        roles = list(ROLE_WORDS[-1][1])
    return roles


def extract_heroes(text, matcher):
    """{hero name: [positions]} named in text, line by line."""
    pattern, lookup = matcher
    found = {}
    for raw in str(text or "").splitlines():
        line = _norm(raw)
        if not line:
            continue
        roles = _roles_in(line)
        for m in pattern.finditer(line):
            name = lookup[m.group(1)]
            slot = found.setdefault(name, [])
            for p in roles:
                if p not in slot:
                    slot.append(p)
    return found


def is_meta_video(title, keywords=None):
    t = str(title or "").lower()
    return any(k in t for k in (keywords or DEFAULT_KEYWORDS))


# ---------------------------------------------------------------------------
# Watchlist file
# ---------------------------------------------------------------------------

def load_watchlist(path=None):
    try:
        with open(path or CREATORS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"creators": [], "videos": [], "keywords": list(DEFAULT_KEYWORDS),
                "max_age_days": config.HERODRAFT_CREATOR_MAX_AGE_DAYS}
    if not isinstance(data, dict):
        data = {}
    creators = [c for c in (data.get("creators") or []) if isinstance(c, dict) and c.get("name")]
    videos = [v for v in (data.get("videos") or []) if isinstance(v, dict) and v.get("title")]
    keywords = [str(k).lower() for k in (data.get("keywords") or DEFAULT_KEYWORDS)]
    try:
        max_age = int(data.get("max_age_days") or config.HERODRAFT_CREATOR_MAX_AGE_DAYS)
    except (TypeError, ValueError):
        max_age = config.HERODRAFT_CREATOR_MAX_AGE_DAYS
    return {"creators": creators, "videos": videos, "keywords": keywords,
            "max_age_days": max_age}


VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|/embed/)([A-Za-z0-9_-]{11})")


def video_id_of(entry):
    vid = entry.get("id")
    if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(vid)):
        return str(vid)
    m = VIDEO_ID_RE.search(str(entry.get("url") or ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# YouTube RSS (public, keyless)
# ---------------------------------------------------------------------------

CHANNEL_ID_RE = re.compile(r'"(?:channelId|externalId)"\s*:\s*"(UC[0-9A-Za-z_-]{22})"')
CHANNEL_URL_RE = re.compile(r"youtube\.com/channel/(UC[0-9A-Za-z_-]{22})")


def resolve_channel_id(session, handle, timeout=20):
    """@handle -> UC... channel id, from the channel page's own metadata."""
    handle = str(handle or "").lstrip("@").strip()
    if not handle:
        return None
    try:
        r = session.get(f"https://www.youtube.com/@{handle}/videos", timeout=timeout,
                        headers={"Accept-Language": "en"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    m = CHANNEL_ID_RE.search(r.text) or CHANNEL_URL_RE.search(r.text)
    return m.group(1) if m else None


def fetch_feed(session, channel_id, timeout=20):
    """[{id, title, published, url, description}] newest first, or None."""
    try:
        r = session.get("https://www.youtube.com/feeds/videos.xml",
                        params={"channel_id": channel_id}, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return parse_feed(r.text)


def parse_feed(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    out = []
    for entry in root.findall(ATOM + "entry"):
        vid = entry.findtext(YT + "videoId") or ""
        title = entry.findtext(ATOM + "title") or ""
        published = entry.findtext(ATOM + "published") or ""
        link = entry.find(ATOM + "link")
        url = (link.get("href") if link is not None else "") or (
            f"https://www.youtube.com/watch?v={vid}" if vid else "")
        group = entry.find(MEDIA + "group")
        desc = group.findtext(MEDIA + "description") if group is not None else ""
        out.append({"id": vid, "title": title, "published": published[:10],
                    "url": url, "description": desc or ""})
    return out


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "ld2l-scout/2.0 (creator meta watch)"
    return s


def refresh_creators(cache, hero_names=None, path=None, verbose=True):
    """Pull every watched creator's feed, keep meta-flavoured videos, extract
    heroes, and store the lot. Returns a one-line summary."""
    watch = load_watchlist(path)
    if not watch["creators"]:
        return "no creators in the watchlist"
    names = list(hero_names or HERO_FALLBACK.values())
    matcher = hero_matcher(names)
    session = _session()
    stale = (cache.get_blob(CACHE_BLOB) or {})
    ids = dict(stale.get("channel_ids") or {})
    videos = {}
    kept = failed = 0
    for creator in watch["creators"]:
        name = str(creator["name"])
        cid = creator.get("channel_id") or ids.get(name)
        if not cid:
            cid = resolve_channel_id(session, creator.get("handle"))
            if cid:
                ids[name] = cid
        if not cid:
            failed += 1
            if verbose:
                print(f"  ⚠ {name}: couldn't resolve a YouTube channel id "
                      f"(set channel_id in meta_creators.json)")
            continue
        feed = fetch_feed(session, cid)
        if feed is None:
            failed += 1
            if verbose:
                print(f"  ⚠ {name}: feed unavailable")
            continue
        for entry in feed:
            if not is_meta_video(entry["title"], watch["keywords"]):
                continue
            heroes = extract_heroes(entry["title"] + "\n" + entry["description"], matcher)
            videos[entry["id"]] = {
                "who": name, "id": entry["id"], "title": entry["title"],
                "date": entry["published"], "url": entry["url"],
                "heroes": heroes,
            }
            kept += 1
    if not videos and stale.get("videos"):
        videos = stale["videos"]
        if verbose:
            print("  ⚠ Creator feeds unreachable; kept the cached videos")
    cache.set_blob(CACHE_BLOB, {"channel_ids": ids, "videos": videos})
    return (f"{len(watch['creators']) - failed}/{len(watch['creators'])} creators, "
            f"{kept} meta videos")


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------

def _age_days(date_str, now):
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0.0, (now - dt.timestamp()) / 86400.0)


def recency_weight(age_days, max_age_days):
    """1.0 for this week's upload, sliding to a floor, gone past max age."""
    if age_days is None or age_days > max_age_days:
        return 0.0
    return max(config.HERODRAFT_CREATOR_FLOOR,
               1.0 - age_days / config.HERODRAFT_CREATOR_DECAY_DAYS)


def creator_signal(cache, hero_names=None, path=None, now=None):
    """{hero name: [{who, title, date, url, pos, weight}]} from cached feeds
    plus the hand entries in meta_creators.json (which override by video)."""
    now = now or time.time()
    watch = load_watchlist(path)
    names = list(hero_names or HERO_FALLBACK.values())
    matcher = hero_matcher(names)
    weights = {str(c["name"]): float(c.get("weight") or 1.0) for c in watch["creators"]}
    cached = (cache.get_blob(CACHE_BLOB) or {}).get("videos") or {} if cache else {}
    merged = {vid: dict(v) for vid, v in cached.items()}
    for entry in watch["videos"]:
        vid = video_id_of(entry) or f"manual:{entry['title']}"
        base = merged.get(vid, {})
        heroes = entry.get("heroes")
        if isinstance(heroes, dict) and heroes:
            heroes = {k: [int(p) for p in (v or []) if str(p).isdigit()]
                      for k, v in heroes.items()}
        elif not base.get("heroes"):
            heroes = extract_heroes(entry.get("title", "") + "\n"
                                    + str(entry.get("notes") or ""), matcher)
        else:
            heroes = base["heroes"]
        merged[vid] = {
            "who": str(entry.get("who") or base.get("who") or "?"),
            "id": vid, "title": str(entry.get("title") or base.get("title") or ""),
            "date": str(entry.get("date") or base.get("date") or "")[:10],
            "url": str(entry.get("url") or base.get("url") or ""),
            "heroes": heroes, "pin": bool(entry.get("pin")),
        }
    signal = {}
    for video in merged.values():
        age = _age_days(video.get("date"), now)
        w = recency_weight(age, watch["max_age_days"])
        if video.get("pin") and w == 0.0:
            w = config.HERODRAFT_CREATOR_FLOOR
        if w <= 0:
            continue
        w *= weights.get(video.get("who"), 1.0)
        for hero, pos in (video.get("heroes") or {}).items():
            signal.setdefault(hero, []).append({
                "who": video.get("who"), "title": video.get("title"),
                "date": video.get("date"), "url": video.get("url"),
                "pos": list(pos or []), "weight": round(w, 2),
            })
    for rows in signal.values():
        rows.sort(key=lambda r: (-r["weight"], r["date"]), reverse=False)
    return signal


def creator_value(rows):
    """Rating credit for a hero's creator mentions: per-video credit × recency,
    one credit per creator (the same creator's three videos count once, at
    their freshest), capped."""
    if not rows:
        return 0.0
    best = {}
    for r in rows:
        who = r.get("who")
        best[who] = max(best.get(who, 0.0), float(r.get("weight") or 0))
    total = sum(config.HERODRAFT_CREATOR_BONUS * w for w in best.values())
    return round(min(config.HERODRAFT_CREATOR_CAP, total), 2)
