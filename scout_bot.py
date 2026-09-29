#!/usr/bin/env python3
"""
scout_bot.py — Team Scout Discord bot.

Reads BBC's local cache only, via scout.bbc_source: Show Graphics/feed.json
(rosters, standings, upcoming) and scrapers/.od_match_cache.json (official
match payloads), read-only. Does not import scout.team_scout / scout.briefing,
call OpenDota, ld2l.org, or use the BBC production bot token in-process, with
three exceptions: `--sync-hero-emojis` (fetches hero art from OpenDota/Steam,
uploads it as Discord application emojis), `--sync-medal-emojis` (fetches Dota
medal art and uploads it as application emojis), and briefing snapshot rendering,
which always shells out to `python -m scout.briefing_cli` as a subprocess
rather than importing it.

Usage:  python scout_bot.py
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv

from scout.bbc_source import bbc_source_paths
from scout.medals import medal_label, medal_prefix


def project_root() -> Path:
    return Path(__file__).resolve().parent


LOG_FILE = project_root() / "logs" / "scout_bot.log"
FEED_PATH, MATCH_CACHE_PATH = (Path(p) for p in bbc_source_paths())
MAX_MESSAGE = 1900
SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
INVITE_URL = (
    "https://discord.com/oauth2/authorize?client_id=1550190834018689034"
    "&permissions=379904&scope=bot%20applications.commands"
)
DEFAULT_SCOUTING_REPORT_TEAM = "Team Anony: Fun Police"

log = logging.getLogger("scout_bot")

_cache = {
    "feed": None,
    "feed_mtime": None,
    "matches": None,
    "matches_mtime": None,
}


def team_key(name):
    text = str(name or "").strip().casefold()
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _cached(path: Path, slot: str, fallback):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return fallback
    if _cache[slot] is not None and _cache[f"{slot}_mtime"] == mtime:
        return _cache[slot]
    try:
        value = _read_json(path)
    except (OSError, ValueError):
        return fallback
    _cache[slot] = value
    _cache[f"{slot}_mtime"] = mtime
    return value


def load_feed():
    feed = _cached(FEED_PATH, "feed", {})
    return feed if isinstance(feed, dict) else {}


def load_matches():
    matches = _cached(MATCH_CACHE_PATH, "matches", {})
    return matches if isinstance(matches, dict) else {}


def team_names(feed=None):
    feed = feed if feed is not None else load_feed()
    names = []
    seen = set()
    for row in feed.get("standings") or []:
        if isinstance(row, dict) and row.get("name"):
            name = str(row["name"])
            key = team_key(name)
            if key and key not in seen:
                seen.add(key)
                names.append(name)
    for matchup in feed.get("upcoming") or []:
        if not isinstance(matchup, dict):
            continue
        for side in ("a", "b"):
            name = str(matchup.get(side) or "").strip()
            key = team_key(name)
            if name and key and key not in seen:
                seen.add(key)
                names.append(name)
    return names


def report_team_names(rd2l=None, league=None):
    """Report autocomplete names: LD2L (BBC feed), RD2L (rd2l_cache.json),
    or both when `league` is None."""
    names = team_names() if league in (None, "LD2L") else []
    if league == "LD2L":
        return names
    seen = {team_key(name) for name in names}
    if rd2l is None:
        try:
            rd2l = _read_json(project_root() / "rd2l_cache.json")
        except (OSError, ValueError):
            rd2l = {}
    for row in (rd2l or {}).get("teams") or []:
        name = str(row.get("name") or "").strip() if isinstance(row, dict) else ""
        key = team_key(name)
        if key and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def resolve_team(query, feed=None):
    """Return (canonical name, standing row or {}, key) or None."""
    feed = feed if feed is not None else load_feed()
    want = team_key(query)
    if not want:
        return None
    for row in feed.get("standings") or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        name = str(row["name"])
        short = str(row.get("nameShort") or name)
        if team_key(name) == want or team_key(short) == want:
            return name, row, team_key(name)
    for name in team_names(feed):
        if team_key(name) == want:
            return name, {}, team_key(name)
    return None


def format_week(feed=None):
    feed = feed if feed is not None else load_feed()
    if not feed:
        return "No BBC feed cache. Run the LD2L scrape."
    league = feed.get("league") or "LD2L"
    week = feed.get("week")
    results_week = feed.get("results_week")
    generated = feed.get("generated") or "unknown"
    lines = [
        f"**{league}** — week {week}",
        f"Results through week {results_week}. Feed generated {generated}.",
    ]
    return "\n".join(lines)


def format_standings(feed=None):
    feed = feed if feed is not None else load_feed()
    rows = [r for r in (feed.get("standings") or []) if isinstance(r, dict) and r.get("name")]
    if not rows:
        return "No standings in the BBC feed cache."
    lines = [f"**{feed.get('league') or 'LD2L'} standings**"]
    for i, row in enumerate(rows, start=1):
        short = row.get("nameShort") or row["name"]
        record = row.get("value") or "?"
        captain = row.get("captain") or ""
        cap = f" ({captain})" if captain else ""
        lines.append(f"{i}. {short}  {record}{cap}")
    return "\n".join(lines)


def format_matchups(feed=None):
    feed = feed if feed is not None else load_feed()
    upcoming = [m for m in (feed.get("upcoming") or []) if isinstance(m, dict)]
    if not upcoming:
        return "No upcoming matchups in the BBC feed cache."
    week = feed.get("week")
    lines = [f"**Week {week} matchups**"]
    for matchup in upcoming:
        a = matchup.get("aShort") or matchup.get("a") or "?"
        b = matchup.get("bShort") or matchup.get("b") or "?"
        ac = matchup.get("ac") or ""
        bc = matchup.get("bc") or ""
        label = matchup.get("label") or ""
        prefix = f"{label} · " if label else ""
        lines.append(f"{prefix}{a} ({ac}) vs {b} ({bc})")
    return "\n".join(lines)


def _roster_for(feed, key):
    for matchup in feed.get("upcoming") or []:
        if not isinstance(matchup, dict):
            continue
        rosters = matchup.get("rosters") or {}
        for side in ("a", "b"):
            name = str(matchup.get(side) or "")
            if team_key(name) != key:
                continue
            return str(matchup.get(side + "Short") or name), rosters.get(side) or []
    return None, []


def format_roster(query, feed=None):
    feed = feed if feed is not None else load_feed()
    found = resolve_team(query, feed)
    if not found:
        return f"No team matching `{query}` in the BBC feed."
    name, standing, key = found
    short = standing.get("nameShort") or name
    record = standing.get("value") or ""
    captain = standing.get("captain") or ""
    header = f"**{short}**"
    if record:
        header += f"  {record}"
    if captain:
        header += f"  captain {captain}"
    listed, roster = _roster_for(feed, key)
    if not roster:
        return header + "\nNo posted roster in the current upcoming matchups."
    lines = [header]
    medal_emoji = load_medal_emoji_map()
    for player in roster:
        if not isinstance(player, dict):
            continue
        mark = " (C)" if player.get("captain") else ""
        tier = player.get("medal")
        badge = medal_prefix(tier, medal_emoji)
        rank = medal_label(tier)
        lines.append(f"- {badge}{player.get('name') or '?'}{mark}"
                     + (f" · {rank}" if rank else ""))
    return "\n".join(lines)


def _side_name(match, side):
    return str(match.get(f"{side}_name") or side.title())


def _result_line(match, key):
    radiant = team_key(_side_name(match, "radiant"))
    dire = team_key(_side_name(match, "dire"))
    if key not in (radiant, dire):
        return None
    radiant_win = bool(match.get("radiant_win"))
    won = (key == radiant and radiant_win) or (key == dire and not radiant_win)
    opponent = _side_name(match, "dire") if key == radiant else _side_name(match, "radiant")
    match_id = match.get("match_id") or "?"
    start = match.get("start_time") or 0
    when = ""
    try:
        when = datetime.fromtimestamp(int(start), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        when = ""
    stamp = f"{when} " if when else ""
    wl = "W" if won else "L"
    return int(start or 0), f"{stamp}{wl} vs {opponent}  <https://www.opendota.com/matches/{match_id}>"


def format_recent(query, feed=None, matches=None, limit=5):
    feed = feed if feed is not None else load_feed()
    found = resolve_team(query, feed)
    if not found:
        return f"No team matching `{query}` in the BBC feed."
    name, standing, key = found
    short = standing.get("nameShort") or name
    matches = matches if matches is not None else load_matches()
    if not matches:
        return f"**{short}**\nNo official match cache yet (`scrapers/.od_match_cache.json`)."
    rows = []
    for raw in matches.values():
        if not isinstance(raw, dict):
            continue
        line = _result_line(raw, key)
        if line:
            rows.append(line)
    rows.sort(key=lambda item: item[0], reverse=True)
    if not rows:
        return f"**{short}**\nNo official matches in the BBC cache for this name."
    lines = [f"**{short}** — last {min(limit, len(rows))} official"]
    lines.extend(item[1] for item in rows[:limit])
    return "\n".join(lines)


def clip(text):
    if len(text) <= MAX_MESSAGE:
        return text
    return text[: MAX_MESSAGE - 20].rstrip() + "\n…truncated"


def load_scout_env():
    load_dotenv(project_root() / ".env")
    return {
        "token": os.getenv("SCOUT_BOT_TOKEN", "").strip(),
        "application_id": os.getenv("SCOUT_BOT_APPLICATION_ID", "").strip(),
        "guild_id": os.getenv("SCOUT_BOT_GUILD_ID", "").strip(),
        "channel_id": os.getenv("SCOUT_BOT_CHANNEL_ID", "").strip(),
        "extra_guild_id": os.getenv("SCOUT_BOT_EXTRA_GUILD_ID", "").strip(),
        "extra_channel_id": os.getenv("SCOUT_BOT_EXTRA_CHANNEL_ID", "").strip(),
    }


def require_snowflake(value, name):
    text = str(value or "").strip()
    if text and not SNOWFLAKE_RE.match(text):
        raise ValueError(f"{name} must be a Discord snowflake id, got {text!r}")
    return text


def wrong_channel_message(used_channel_id, allowed_channel_id):
    allowed = str(allowed_channel_id or "").strip()
    if not allowed:
        return None
    if str(used_channel_id or "") == allowed:
        return None
    return f"Please use this command in <#{allowed}>."


def effective_guild_id(configured_guild_id, channel_guild_id):
    configured = str(configured_guild_id or "").strip()
    if configured:
        return configured
    return str(channel_guild_id or "").strip()


def guild_channel_mismatch(configured_guild_id, channel_guild_id):
    configured = str(configured_guild_id or "").strip()
    derived = str(channel_guild_id or "").strip()
    return bool(configured and derived and configured != derived)


def require_scout_channel(channel_id):
    def deco(fn):
        @wraps(fn)
        async def wrapped(interaction, *args, **kwargs):
            msg = wrong_channel_message(
                getattr(interaction, "channel_id", None), channel_id
            )
            if msg:
                await interaction.response.send_message(msg, ephemeral=True)
                return
            return await fn(interaction, *args, **kwargs)
        return wrapped
    return deco


async def resolve_scout_channel(client, channel_id, force_fetch=False):
    import discord

    cid = int(channel_id)
    channel = client.get_channel(cid)
    if channel is None or force_fetch:
        try:
            channel = await client.fetch_channel(cid)
        except discord.NotFound as exc:
            raise RuntimeError(
                f"SCOUT_BOT_CHANNEL_ID {channel_id} does not exist. "
                f"Invite the bot: {INVITE_URL}"
            ) from exc
        except discord.Forbidden as exc:
            raise RuntimeError(
                f"Scout Bot cannot see channel {channel_id} "
                f"(not invited, or missing access). Invite: {INVITE_URL}"
            ) from exc
    guild = getattr(channel, "guild", None)
    if guild is None:
        raise RuntimeError(
            f"SCOUT_BOT_CHANNEL_ID {channel_id} is not a server channel."
        )
    return channel, guild


def register_commands(tree, guild, channel_id="", default_team=DEFAULT_SCOUTING_REPORT_TEAM,
                      league="LD2L"):
    """Register one server's slash commands. `league` ("LD2L" or "RD2L")
    locks that server's scouting reports to its own league's teams."""
    import discord
    from discord import app_commands

    gate = require_scout_channel(channel_id)

    async def team_autocomplete(interaction: discord.Interaction, current: str):
        cur = current.lower()
        return [
            app_commands.Choice(name=name[:100], value=name[:100])
            for name in team_names()
            if cur in name.lower()
        ][:25]

    async def report_team_autocomplete(interaction: discord.Interaction, current: str):
        cur = current.lower()
        return [app_commands.Choice(name=name[:100], value=name[:100])
                for name in report_team_names(league=league) if cur in name.lower()][:25]

    if league == "LD2L":
        # BBC feed commands are LD2L data; keep them off the RD2L server.
        @tree.command(name="week", description="Current LD2L week from the BBC feed cache", guild=guild)
        @gate
        async def week_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(clip(format_week()), ephemeral=False)

        @tree.command(name="standings", description="Season standings from the BBC feed cache", guild=guild)
        @gate
        async def standings_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(clip(format_standings()), ephemeral=False)

        @tree.command(name="matchups", description="This week's upcoming series from the BBC feed cache", guild=guild)
        @gate
        async def matchups_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(clip(format_matchups()), ephemeral=False)

        @tree.command(name="roster", description="Posted roster for a team", guild=guild)
        @app_commands.describe(team="Team name")
        @app_commands.autocomplete(team=team_autocomplete)
        @gate
        async def roster_cmd(interaction: discord.Interaction, team: str):
            await interaction.response.send_message(clip(format_roster(team)), ephemeral=False)

        @tree.command(name="recent", description="Recent official matches from the BBC OpenDota cache", guild=guild)
        @app_commands.describe(team="Team name")
        @app_commands.autocomplete(team=team_autocomplete)
        @gate
        async def recent_cmd(interaction: discord.Interaction, team: str):
            await interaction.response.defer()
            await interaction.followup.send(clip(format_recent(team)))

    async def post_report_command(interaction, team, vs, command_name):
        await interaction.response.defer(ephemeral=True)
        try:
            meta = await render_snapshot_async(team, vs=vs, league=league)
            snap = load_snapshot(meta["id"])
            if snap is None:
                raise RuntimeError("snapshot rendered but could not be loaded back")
            cfg = load_scout_env()
            token = cfg["token"]
            channel_id = require_snowflake(str(interaction.channel_id), "channel_id")
            body, files = build_message_body(snap["briefing"], snap["dir"], meta["id"], "briefing")
            _posted, errors = await asyncio.to_thread(
                _post_replacing_briefing, channel_id, token, body, files,
            )
            reply = ("Posted. Earlier reports could not all be removed; check the bot log."
                     if errors else "Posted. Earlier scouting reports removed.")
            await interaction.followup.send(reply, ephemeral=True)
        except Exception as exc:
            log.exception("/%s failed", command_name)
            await interaction.followup.send(f"Failed to post scouting report: {exc}", ephemeral=True)

    @tree.command(name="briefing", description="Post a Team Scout scouting briefing", guild=guild)
    @app_commands.describe(team="Team to scout", vs="Opponent (optional - defaults to the current matchup)")
    @app_commands.autocomplete(team=report_team_autocomplete, vs=report_team_autocomplete)
    @gate
    async def briefing_cmd(interaction: discord.Interaction, team: str, vs: str = None):
        await post_report_command(interaction, team, vs, "briefing")

    @tree.command(name="scoutingreport", description="Post the scouting report with Briefing, Wards and Recon", guild=guild)
    @app_commands.describe(team="Team to scout (defaults to the current prototype)",
                           vs="Opponent (optional - defaults to the current matchup)")
    @app_commands.autocomplete(team=report_team_autocomplete, vs=report_team_autocomplete)
    @gate
    async def scoutingreport_cmd(interaction: discord.Interaction, team: str = None,
                                 vs: str = None):
        selected_team = team or default_team
        if not selected_team:
            await interaction.response.send_message(
                "Choose a team to scout with the `team` option.", ephemeral=True)
            return
        await post_report_command(interaction, selected_team, vs, "scoutingreport")

    @tree.error
    async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        log.exception("slash command failed", exc_info=error)
        msg = "Scout cache read failed. Check logs/scout_bot.log."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


def run():
    import discord

    cfg = load_scout_env()
    token = cfg["token"]
    if not token:
        log.error("SCOUT_BOT_TOKEN is empty in .env. Paste the token from the Discord Bot page.")
        sys.exit(1)
    try:
        guild_id = require_snowflake(cfg["guild_id"], "SCOUT_BOT_GUILD_ID")
        channel_id = require_snowflake(cfg["channel_id"], "SCOUT_BOT_CHANNEL_ID")
        extra_guild_id = require_snowflake(cfg["extra_guild_id"], "SCOUT_BOT_EXTRA_GUILD_ID")
        extra_channel_id = require_snowflake(cfg["extra_channel_id"], "SCOUT_BOT_EXTRA_CHANNEL_ID")
        if bool(extra_guild_id) != bool(extra_channel_id):
            raise ValueError("SCOUT_BOT_EXTRA_GUILD_ID and SCOUT_BOT_EXTRA_CHANNEL_ID must be set together")
    except ValueError as exc:
        log.error("%s", exc)
        sys.exit(1)

    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    guild = discord.Object(id=int(guild_id)) if guild_id else None
    register_commands(tree, guild, channel_id)
    if extra_guild_id:
        register_commands(tree, discord.Object(id=int(extra_guild_id)), extra_channel_id,
                          default_team=None, league="RD2L")
    startup_error = []

    @client.event
    async def on_interaction(interaction):
        # Briefing/Wards/Recon tab-row buttons: handled raw (REST callback,
        # type 7 UPDATE_MESSAGE) because they swap the whole Components V2
        # body. No View is registered for these custom_ids, so discord.py's
        # own component dispatch never tries to respond to them too.
        if getattr(interaction, "type", None) == discord.InteractionType.component:
            try:
                handled = await handle_tab_interaction(interaction)
            except Exception:
                log.exception("tab interaction failed")
                handled = False
            if handled:
                return

    @client.event
    async def on_ready():
        try:
            resolved_guild_id = guild_id
            if channel_id:
                channel, channel_guild = await resolve_scout_channel(client, channel_id)
                if guild_channel_mismatch(guild_id, channel_guild.id):
                    raise RuntimeError(
                        f"SCOUT_BOT_GUILD_ID {guild_id} is not the server that "
                        f"owns channel {channel_id} (guild {channel_guild.id})."
                    )
                resolved_guild_id = effective_guild_id(guild_id, channel_guild.id)
                log.info("scout channel ok: #%s (%s) in guild %s",
                         getattr(channel, "name", "?"), channel_id, resolved_guild_id)
            if resolved_guild_id:
                target = discord.Object(id=int(resolved_guild_id))
                synced = await tree.sync(guild=target)
                where = f"guild {resolved_guild_id}"
            else:
                synced = await tree.sync()
                where = "global (can take up to an hour)"
            log.info("scout bot ready as %s — %d command(s) synced %s",
                     client.user, len(synced), where)
            if extra_guild_id:
                try:
                    extra_channel, extra_guild = await resolve_scout_channel(
                        client, extra_channel_id, force_fetch=True)
                    if str(extra_guild.id) != extra_guild_id:
                        raise RuntimeError("Extra scout channel belongs to another server")
                    log.info("extra scout channel ok: #%s (%s) in guild %s",
                             getattr(extra_channel, "name", "?"), extra_channel_id, extra_guild_id)
                except RuntimeError as exc:
                    log.warning("extra scout channel access pending: %s", exc)
                extra_synced = await tree.sync(guild=discord.Object(id=int(extra_guild_id)))
                log.info("scout bot ready as %s — %d command(s) synced guild %s",
                         client.user, len(extra_synced), extra_guild_id)
        except Exception as exc:
            log.exception("scout bot startup failed")
            startup_error.append(exc)
            await client.close()

    log.info("starting scout bot…")
    client.run(token, log_handler=None)
    if startup_error:
        sys.exit(1)


def _team_scout_root() -> Path:
    """LD2L Scout checkout: TEAM_SCOUT_ROOT env var, else this bot's own
    root (Scout Bot lives inside the LD2L Scout repo)."""
    configured = os.environ.get("TEAM_SCOUT_ROOT", "").strip()
    if configured:
        return Path(configured)
    return project_root()


# --------------------------------------------------------------------------
# Snapshot rendering: scout.briefing_cli runs as a subprocess (never an
# in-process import) so the normal bot process never touches Team Scout's
# payload-building modules (scout.team_scout / scout.briefing).
# --------------------------------------------------------------------------

SNAPSHOT_ROOT = project_root() / "cache" / "scout_briefings"
CUSTOM_ID_RE = re.compile(r"^sb:tab:(briefing|wards|recon):([0-9a-f]{12})$")
WARD_VIEW_ID_RE = re.compile(r"^sb:ward-view:(heatmap|individual):([0-9a-f]{12})$")
TAB_LABELS = {"briefing": ("Briefing", "\U0001F4CB"), "wards": ("Wards", "\U0001F5FA️"),
              "recon": ("Recon", "\U0001F50E")}
V2_FLAG = 1 << 15


def _emoji_map_path():
    path = HERO_EMOJI_CACHE_DIR / "emoji_map.json"
    return path if path.exists() else None


def _medal_emoji_map_path():
    path = MEDAL_EMOJI_CACHE_DIR / "emoji_map.json"
    return path if path.exists() else None


def load_medal_emoji_map():
    path = _medal_emoji_map_path()
    if path is None:
        return {}
    try:
        data = _read_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _snapshot_argv(team, vs, out_dir, league=None):
    argv = [sys.executable, "-m", "scout.briefing_cli", "--team", team, "--out", str(out_dir)]
    if vs:
        argv += ["--vs", vs]
    if league:
        argv += ["--league", league]
    season = os.environ.get("TEAM_SCOUT_SEASON", "").strip()
    if season:
        argv += ["--season", season]
    emoji_map = _emoji_map_path()
    if emoji_map:
        argv += ["--emoji-map", str(emoji_map)]
    medal_emoji_map = _medal_emoji_map_path()
    if medal_emoji_map:
        argv += ["--medal-emoji-map", str(medal_emoji_map)]
    return argv


def _subprocess_extra_kwargs():
    # windows-only: never let the launched interpreter allocate a console.
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _finish_snapshot(tmp_dir, stdout, returncode, stderr):
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "scout.briefing_cli exited non-zero")
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise RuntimeError("scout.briefing_cli produced no output")
    meta = json.loads(text.splitlines()[-1])
    dest = SNAPSHOT_ROOT / meta["id"]
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(tmp_dir, dest)
    return meta


def render_snapshot(team, vs=None, league=None):
    """Sync: run scout.briefing_cli as a subprocess (cwd = LD2L Scout,
    never shell=True, never inherited stdio), then move its output under
    cache/scout_briefings/<id>/. Returns the meta dict."""
    root = _team_scout_root()
    with tempfile.TemporaryDirectory(prefix="scout_snapshot_") as tmp:
        argv = _snapshot_argv(team, vs, tmp, league=league)
        result = subprocess.run(
            argv, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **_subprocess_extra_kwargs(),
        )
        return _finish_snapshot(tmp, result.stdout, result.returncode, result.stderr)


async def render_snapshot_async(team, vs=None, league=None):
    """Async twin of render_snapshot, same subprocess flags."""
    root = _team_scout_root()
    with tempfile.TemporaryDirectory(prefix="scout_snapshot_") as tmp:
        argv = _snapshot_argv(team, vs, tmp, league=league)
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **_subprocess_extra_kwargs(),
        )
        stdout, stderr = await proc.communicate()
        return _finish_snapshot(tmp, stdout, proc.returncode, stderr)


def load_snapshot(snapshot_id):
    """Load a previously rendered snapshot dir back into memory, or None if
    it's missing/unreadable (e.g. cleaned up, or never rendered)."""
    if not re.match(r"^[0-9a-f]{12}$", str(snapshot_id or "")):
        return None
    snap_dir = SNAPSHOT_ROOT / snapshot_id
    if not snap_dir.is_dir():
        return None
    try:
        with (snap_dir / "meta.json").open(encoding="utf-8") as handle:
            meta = json.load(handle)
        with (snap_dir / "briefing.json").open(encoding="utf-8") as handle:
            briefing_doc = json.load(handle)
        with (snap_dir / "wards.json").open(encoding="utf-8") as handle:
            wards_doc = json.load(handle)
    except (OSError, ValueError):
        return None
    try:
        with (snap_dir / "recon.json").open(encoding="utf-8") as handle:
            recon_doc = json.load(handle)
    except FileNotFoundError:
        # Snapshots posted before Recon was added still have working tabs.
        recon_doc = {"components": [{"type": 17, "accent_color": 0xE74C3C,
                     "components": [{"type": 10, "content":
                     "Recon was added after this briefing. Run /briefing again to see it."}]}],
                     "attachments": []}
    except (OSError, ValueError):
        return None
    try:
        with (snap_dir / "wards_individual.json").open(encoding="utf-8") as handle:
            wards_individual_doc = json.load(handle)
    except FileNotFoundError:
        wards_individual_doc = None
    except (OSError, ValueError):
        return None
    return {"dir": snap_dir, "meta": meta, "briefing": briefing_doc,
            "wards": wards_doc, "wards_individual": wards_individual_doc,
            "recon": recon_doc}


# --------------------------------------------------------------------------
# Local, import-free renderers over the Components V2 JSON scout.briefing_cli
# wrote to disk. Deliberately duplicated (not imported) from
# scout/briefing.py's page_text/_count_components/_text_chars - the whole
# point of the subprocess boundary above is that the normal gateway process
# never imports scout.team_scout / scout.briefing.
# --------------------------------------------------------------------------

def render_components_text(components):
    lines = []

    def walk(node):
        t = node.get("type")
        if t == 10:  # text display
            lines.append(node.get("content") or "")
        elif t == 14:  # separator
            lines.append("---")
        elif t == 9:  # section
            for child in node.get("components") or []:
                walk(child)
            accessory = node.get("accessory")
            if accessory and accessory.get("type") == 11:
                lines.append(f"[thumbnail: {(accessory.get('media') or {}).get('url')}]")
        elif t in (17, 1):  # container / action row
            for child in node.get("components") or []:
                walk(child)
        elif t == 12:  # media gallery
            for item in node.get("items") or []:
                lines.append(f"[image: {(item.get('media') or {}).get('url')}]")
        elif t == 2:  # button
            lines.append(f"[button: {node.get('label')}]")

    for node in components:
        walk(node)
    return "\n\n".join(lines)


def _count_components(nodes):
    total = 0
    for node in nodes:
        total += 1
        if isinstance(node.get("components"), list):
            total += _count_components(node["components"])
        accessory = node.get("accessory")
        if isinstance(accessory, dict):
            total += _count_components([accessory])
    return total


def _text_chars(nodes):
    total = 0
    for node in nodes:
        if node.get("type") == 10:
            total += len(node.get("content") or "")
        if isinstance(node.get("components"), list):
            total += _text_chars(node["components"])
    return total


def tab_row(snapshot_id, active_tab):
    buttons = []
    for tab, (label, emoji) in TAB_LABELS.items():
        buttons.append({
            "type": 2,
            "style": 1 if tab == active_tab else 2,
            "label": label,
            "emoji": {"name": emoji},
            "custom_id": f"sb:tab:{tab}:{snapshot_id}",
        })
    return {"type": 1, "components": buttons}


def ward_view_row(snapshot_id, active_view):
    return {"type": 1, "components": [
        {"type": 2, "style": 1 if view == active_view else 2,
         "label": label, "custom_id": f"sb:ward-view:{view}:{snapshot_id}"}
        for view, label in (("heatmap", "Heatmap"), ("individual", "Individual Wards"))
    ]}


def build_message_body(page_doc, snapshot_dir, snapshot_id, active_tab,
                       ward_view="heatmap", ward_toggle=False):
    """{"flags": ..., "components": [container, tab_row], "attachments":
    [...]} plus the (filename, bytes) files to send multipart alongside it."""
    components = list(page_doc.get("components") or []) + [tab_row(snapshot_id, active_tab)]
    if active_tab == "wards" and ward_toggle:
        components.append(ward_view_row(snapshot_id, ward_view))
    attachments_meta = []
    files = []
    for i, filename in enumerate(page_doc.get("attachments") or []):
        attachments_meta.append({"id": i, "filename": filename})
        files.append((filename, (Path(snapshot_dir) / filename).read_bytes()))
    body = {"flags": V2_FLAG, "components": components, "attachments": attachments_meta}
    return body, files


def _build_multipart(payload_json_obj, files):
    boundary = uuid.uuid4().hex
    parts = []
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode("utf-8")
    )
    parts.append(json.dumps(payload_json_obj).encode("utf-8"))
    parts.append(b"\r\n")
    for i, (filename, data) in enumerate(files):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode("utf-8")
        )
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post_multipart_message(channel_id, token, body, files):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    if files:
        payload, content_type = _build_multipart(body, files)
        headers = {"Authorization": f"Bot {token}", "Content-Type": content_type,
                   "User-Agent": "DiscordBot (local, 1)"}
    else:
        payload = json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json",
                   "User-Agent": "DiscordBot (local, 1)"}
    request = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord POST failed: {exc.code} {detail}") from exc


def _is_scout_briefing(message):
    """Identify current tabbed reports and legacy Scout briefing embeds."""
    def has_tab(nodes):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("custom_id") or "").startswith("sb:tab:"):
                return True
            if has_tab(node.get("components") or []):
                return True
        return False

    if has_tab(message.get("components") or []):
        return True
    for embed in message.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        author = (embed.get("author") or {}).get("name") or ""
        footer = (embed.get("footer") or {}).get("text") or ""
        if author.startswith("🔎 SCOUT BRIEFING") and footer.startswith("Team Scout ·"):
            return True
    return False


def _discord_open(request):
    """Respect Discord's retry interval during briefing history cleanup."""
    for attempt in range(5):
        try:
            return urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            retry = exc.headers.get("Retry-After") if exc.headers else None
            if retry is None:
                try:
                    retry = json.loads(exc.read().decode("utf-8")).get("retry_after")
                except (ValueError, AttributeError):
                    retry = None
            try:
                delay = float(retry)
            except (TypeError, ValueError):
                delay = 1.0
            time.sleep(max(0.2, min(delay, 30.0)))


def _channel_messages(channel_id, token, before=None):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100"
    if before:
        url += f"&before={before}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (local, 1)",
    })
    with _discord_open(request) as response:
        return json.load(response)


def _delete_briefing_message(channel_id, token, message_id):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    request = urllib.request.Request(url, method="DELETE", headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (local, 1)",
    })
    try:
        with _discord_open(request):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code != 404:  # Already removed by another post is fine.
            raise


def _remove_older_briefings(channel_id, token, posted):
    """Keep the newest Scout Bot briefing in the configured channel."""
    keep_id = str(posted.get("id") or "")
    author_id = str((posted.get("author") or {}).get("id") or "")
    if not keep_id.isdigit() or not author_id:
        return 0, ["Discord did not return the new message and author IDs"]
    removed, errors, before = 0, [], None
    while True:
        try:
            rows = _channel_messages(channel_id, token, before)
        except (OSError, ValueError) as exc:
            errors.append(f"Could not read channel history: {exc}")
            break
        if not isinstance(rows, list):
            errors.append("Discord returned invalid channel history")
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            message_id = str(row.get("id") or "")
            if (not message_id.isdigit() or int(message_id) >= int(keep_id)
                    or str((row.get("author") or {}).get("id") or "") != author_id
                    or not _is_scout_briefing(row)):
                continue
            try:
                _delete_briefing_message(channel_id, token, message_id)
                removed += 1
            except OSError as exc:
                errors.append(f"Could not remove message {message_id}: {exc}")
        if len(rows) < 100:
            break
        next_before = str((rows[-1] or {}).get("id") or "")
        if not next_before.isdigit() or next_before == before:
            errors.append("Could not continue channel history scan")
            break
        before = next_before
    return removed, errors


def _post_replacing_briefing(channel_id, token, body, files):
    posted = _post_multipart_message(channel_id, token, body, files)
    removed, errors = _remove_older_briefings(channel_id, token, posted)
    for error in errors:
        log.warning("briefing cleanup: %s", error)
    log.info("Posted briefing to channel %s, message id %s; removed %d earlier briefing(s)",
             channel_id, posted.get("id"), removed)
    return posted, errors


def post_briefing(team, vs=None, dry_run=False):
    """One-shot CLI path (no gateway login): render a snapshot and either
    preview all pages or post the Briefing page to the scout channel."""
    try:
        meta = render_snapshot(team, vs=vs)
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    snap = load_snapshot(meta["id"])
    if snap is None:
        log.error("Snapshot %s rendered but could not be loaded back", meta.get("id"))
        sys.exit(1)

    if dry_run:
        for name in TAB_LABELS:
            doc = snap[name]
            print(f"=== {name} ===")
            print(render_components_text(doc["components"]))
            print(f"components: {_count_components(doc['components'])}  "
                  f"chars: {_text_chars(doc['components'])}")
            for filename in doc.get("attachments") or []:
                print(f"PNG: {snap['dir'] / filename}")
            print()
        return

    cfg = load_scout_env()
    token = cfg["token"]
    if not token:
        log.error("SCOUT_BOT_TOKEN is empty in .env. Paste the token from the Discord Bot page.")
        sys.exit(1)
    try:
        channel_id = require_snowflake(cfg["channel_id"], "SCOUT_BOT_CHANNEL_ID")
    except ValueError as exc:
        log.error("%s", exc)
        sys.exit(1)
    if not channel_id:
        log.error("SCOUT_BOT_CHANNEL_ID is empty in .env.")
        sys.exit(1)

    body, files = build_message_body(snap["briefing"], snap["dir"], meta["id"], "briefing")
    try:
        _posted, errors = _post_replacing_briefing(channel_id, token, body, files)
        if errors:
            log.warning("Briefing posted, but earlier messages may remain in the scout channel")
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)


async def handle_tab_interaction(interaction):
    """Component interactions for the Briefing/Wards/Recon tab row: responds
    directly over the REST interaction-callback endpoint (type 7,
    UPDATE_MESSAGE) instead of discord.py's response wrapper, since this
    swaps the whole Components V2 body (and attachments) in place."""
    import aiohttp

    custom_id = (getattr(interaction, "data", None) or {}).get("custom_id", "")
    tab_match = CUSTOM_ID_RE.match(custom_id)
    view_match = WARD_VIEW_ID_RE.match(custom_id)
    if not tab_match and not view_match:
        return False
    if view_match:
        tab, ward_view, snapshot_id = "wards", view_match.group(1), view_match.group(2)
    else:
        tab, ward_view, snapshot_id = tab_match.group(1), "heatmap", tab_match.group(2)
    callback_url = f"https://discord.com/api/v10/interactions/{interaction.id}/{interaction.token}/callback"

    async with aiohttp.ClientSession() as session:
        snap = load_snapshot(snapshot_id)
        if snap is None:
            data = {"type": 4, "data": {
                "content": "This briefing snapshot is gone. Run /briefing again.",
                "flags": 64,
            }}
            async with session.post(callback_url, json=data) as resp:
                await resp.read()
            return True

        page = (snap["wards_individual"] if ward_view == "individual"
                and snap["wards_individual"] is not None else snap[tab])
        body, files = build_message_body(page, snap["dir"], snapshot_id, tab,
                                         ward_view=ward_view,
                                         ward_toggle=snap["wards_individual"] is not None)
        if tab == "briefing":
            body["attachments"] = []
            files = []

        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps({"type": 7, "data": body}),
                        content_type="application/json")
        for i, (filename, data) in enumerate(files):
            form.add_field(f"files[{i}]", data, filename=filename,
                            content_type="application/octet-stream")
        async with session.post(callback_url, data=form) as resp:
            await resp.read()
    return True



# --------------------------------------------------------------------------
# --sync-hero-emojis: OpenDota hero art -> Discord application emojis
# --------------------------------------------------------------------------

OPENDOTA_HEROES_URL = "https://api.opendota.com/api/constants/heroes"
STEAM_CDN_BASE = "https://cdn.cloudflare.steamstatic.com"
HERO_EMOJI_CACHE_DIR = project_root() / "cache" / "scout_hero_emojis"
MEDAL_EMOJI_CACHE_DIR = project_root() / "cache" / "scout_medal_emojis"
RANK_ICON_CACHE_DIR = project_root() / "cache" / "rank_icons"
RANK_ICON_URL = "https://www.opendota.com/assets/images/dota2/rank_icons/"
EMOJI_MAX_BYTES = 256 * 1024
CROP_SIZE = 112
FINAL_SIZE = 128
CONTACT_SHEET_COLS = 12

# Focal points in the 256x144 source art. Most hero faces sit near (128, 70),
# but these portraits put the face noticeably to one side. The optional third
# number keeps wide or multiple faces in frame. Values scale for small art.
HERO_FACE_CROPS = {
    1: (145, 67),    # Anti-Mage
    7: (144, 74),    # Earthshaker
    8: (147, 76),    # Juggernaut
    12: (148, 68),   # Phantom Lancer
    14: (122, 75, 128),  # Pudge
    15: (204, 75),   # Razor
    16: (106, 80),   # Sand King
    18: (177, 76),   # Sven
    25: (68, 70),    # Lina
    29: (130, 79, 128),  # Tidehunter
    43: (198, 68),   # Death Prophet
    46: (107, 69),   # Templar Assassin
    54: (113, 78),   # Lifestealer
    58: (101, 73),   # Enchantress
    61: (135, 75, 128),  # Broodmother
    64: (128, 74, 144),  # Jakiro: two heads
    70: (83, 80),    # Ursa
    73: (128, 76, 144),  # Alchemist: two faces
    80: (155, 74),   # Lone Druid
    90: (103, 72),   # Keeper of the Light
    91: (128, 72, 144),  # Io: full light form
    97: (157, 77),   # Magnus
    105: (194, 74),  # Techies: focus the front goblin
    110: (119, 77, 128),  # Phoenix
    119: (102, 72),  # Dark Willow
    121: (174, 75),  # Grimstroke
    123: (99, 77),   # Hoodwink
    131: (109, 74),  # Ringmaster
    137: (138, 80, 136),  # Primal Beast
}


def _http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot (local, 1)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_bytes(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "DiscordBot (local, 1)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _team_scout_heroes_full_cache():
    """LD2L Scout's own hero cache (id -> {n, key, attr}), already fetched
    from OpenDota through its normal cache flow. Used only as a fallback
    when the live OpenDota constants call is unavailable (e.g. a shared
    sandbox IP that has hit OpenDota's daily rate limit)."""
    path = _team_scout_root() / "cache" / "heroes_full.json"
    try:
        with path.open(encoding="utf-8") as handle:
            blob = json.load(handle)
    except (OSError, ValueError):
        return None
    data = blob.get("data") if isinstance(blob, dict) else None
    return data if isinstance(data, dict) else None


def fetch_opendota_heroes_constants(cache_dir):
    """GET OpenDota's /constants/heroes and cache the JSON at
    cache_dir/heroes.json. Falls back to a previously cached copy, then to
    LD2L Scout's own OpenDota-derived hero cache, if the live call fails.
    Returns (data, source) where source is "live", "cache", or
    "ld2l-scout-cache-fallback"."""
    cache_path = cache_dir / "heroes.json"
    try:
        data = _http_get_json(OPENDOTA_HEROES_URL)
        if isinstance(data, dict) and data:
            with cache_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle)
            return data, "live"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        log.warning("OpenDota constants/heroes fetch failed: %s", exc)

    if cache_path.exists():
        try:
            with cache_path.open(encoding="utf-8") as handle:
                return json.load(handle), "cache"
        except (OSError, ValueError):
            pass

    scout_cache = _team_scout_heroes_full_cache()
    if scout_cache:
        data = {}
        for hid, info in scout_cache.items():
            key = info.get("key") or ""
            data[str(hid)] = {
                "id": int(hid),
                "name": f"npc_dota_hero_{key}" if key else f"npc_dota_hero_{hid}",
                "localized_name": info.get("n") or f"Hero {hid}",
                "primary_attr": info.get("attr") or "all",
                "img": f"/apps/dota2/images/dota_react/heroes/{key}.png?" if key else "",
            }
        with cache_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return data, "ld2l-scout-cache-fallback"

    raise RuntimeError(
        "No hero constants available: OpenDota API unreachable and no cache/fallback found"
    )


def sanitize_emoji_name(hero_internal_name):
    """"npc_dota_hero_antimage" -> "h_antimage"; strips anything outside
    [A-Za-z0-9_] and caps at Discord's 32-char emoji name limit."""
    short = str(hero_internal_name or "")
    prefix = "npc_dota_hero_"
    if short.startswith(prefix):
        short = short[len(prefix):]
    short = re.sub(r"[^A-Za-z0-9_]", "", short)
    return f"h_{short}"[:32]


def face_emoji_name(hero_internal_name):
    """New namespace so old snapshots keep their existing emoji IDs."""
    return ("hf_" + sanitize_emoji_name(hero_internal_name)[2:])[:32]


def crop_hero_portrait(image_bytes, hero_id=None):
    """Crop around the hero's face, then resize to a 128x128 Discord emoji.

    Focal points use the 256x144 art as a reference and scale with source size.
    They replace the old fixed center crop, which clipped off-center faces.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size
    focal = HERO_FACE_CROPS.get(int(hero_id), (128, 70)) if hero_id is not None else (128, 70)
    scale = min(w / 256, h / 144)
    size = max(1, min(w, h, round((focal[2] if len(focal) == 3 else CROP_SIZE) * scale)))
    center_x, center_y = round(focal[0] * w / 256), round(focal[1] * h / 144)
    left = min(max(center_x - size // 2, 0), w - size)
    top = min(max(center_y - size // 2, 0), h - size)
    box = (left, top, left + size, top + size)
    cropped = img.crop(box)
    if cropped.size != (size, size):
        cropped = cropped.resize((size, size), Image.LANCZOS)
    final = cropped.resize((FINAL_SIZE, FINAL_SIZE), Image.LANCZOS)

    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    if len(data) > EMOJI_MAX_BYTES:
        palette = final.convert("P", palette=Image.ADAPTIVE, colors=256)
        buf = io.BytesIO()
        palette.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
    return data


def list_application_emojis(app_id, token):
    url = f"https://discord.com/api/v10/applications/{app_id}/emojis"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (local, 1)",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("items") or []


def create_application_emoji(app_id, token, name, image_bytes):
    """POST a new application emoji. Retries on 429 using the Discord-supplied
    retry_after. Never logs the token."""
    url = f"https://discord.com/api/v10/applications/{app_id}/emojis"
    payload = json.dumps({
        "name": name,
        "image": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii"),
    }).encode("utf-8")
    while True:
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (local, 1)",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code == 429:
                try:
                    retry_after = json.loads(body.decode("utf-8")).get("retry_after", 1)
                except ValueError:
                    retry_after = 1
                time.sleep(max(0.5, float(retry_after)))
                continue
            detail = body.decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord emoji upload failed for {name!r}: {exc.code} {detail}") from exc


def build_contact_sheet(crops, out_path):
    """crops: [(hero_id, emoji_name, png_bytes)] of 128x128 images -> one
    contact-sheet PNG, CONTACT_SHEET_COLS per row, for reviewing crops."""
    from PIL import Image

    if not crops:
        return
    cols = CONTACT_SHEET_COLS
    rows = (len(crops) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * FINAL_SIZE, rows * FINAL_SIZE), (24, 24, 27, 255))
    for i, (_hero_id, _name, data) in enumerate(crops):
        tile = Image.open(io.BytesIO(data)).convert("RGBA")
        x = (i % cols) * FINAL_SIZE
        y = (i // cols) * FINAL_SIZE
        sheet.paste(tile, (x, y), tile)
    sheet.save(out_path)


def sync_hero_emojis():
    """Download every OpenDota hero portrait, crop/resize it to a 128x128
    Discord emoji, and upload any that don't already exist as Scout Bot
    application emojis. Writes emoji_map.json ({hero_id: "<:hf_x:id>"}),
    portraits.json ({hero_id: portrait URL}), and a contact_sheet.png of
    every crop. Idempotent: re-running only uploads names that are missing.
    Returns (created, skipped, emoji_map)."""
    cache_dir = HERO_EMOJI_CACHE_DIR
    src_dir = cache_dir / "src"
    cache_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_scout_env()
    token = cfg["token"]
    app_id = cfg["application_id"]
    if not token or not app_id:
        log.error("SCOUT_BOT_TOKEN and SCOUT_BOT_APPLICATION_ID are required for --sync-hero-emojis")
        sys.exit(1)

    heroes, source = fetch_opendota_heroes_constants(cache_dir)
    log.info("hero constants source: %s (%d heroes)", source, len(heroes))

    existing_by_name = {e["name"]: e["id"] for e in list_application_emojis(app_id, token)}

    emoji_map = {}
    portraits = {}
    crops = []
    created = 0
    skipped = 0

    for hero_id_str, hero in sorted(heroes.items(), key=lambda kv: str(kv[1].get("id", kv[0]))):
        hero_id = hero.get("id")
        if hero_id is None:
            try:
                hero_id = int(hero_id_str)
            except (TypeError, ValueError):
                continue
        img_path = (hero.get("img") or "").split("?")[0]
        if not img_path:
            continue
        portrait_url = STEAM_CDN_BASE + img_path
        portraits[str(hero_id)] = portrait_url

        internal_name = hero.get("name") or f"npc_dota_hero_{hero_id}"
        emoji_name = face_emoji_name(internal_name)

        src_file = src_dir / f"{hero_id}.png"
        if not src_file.exists():
            image_bytes = _http_get_bytes(portrait_url, headers={"User-Agent": "Mozilla/5.0"})
            src_file.write_bytes(image_bytes)
        else:
            image_bytes = src_file.read_bytes()

        cropped_bytes = crop_hero_portrait(image_bytes, hero_id)
        crops.append((hero_id, emoji_name, cropped_bytes))

        if emoji_name in existing_by_name:
            emoji_map[str(hero_id)] = f"<:{emoji_name}:{existing_by_name[emoji_name]}>"
            skipped += 1
            continue

        result = create_application_emoji(app_id, token, emoji_name, cropped_bytes)
        emoji_id = result.get("id")
        existing_by_name[emoji_name] = emoji_id
        emoji_map[str(hero_id)] = f"<:{emoji_name}:{emoji_id}>"
        created += 1

    with (cache_dir / "emoji_map.json").open("w", encoding="utf-8") as handle:
        json.dump(emoji_map, handle)
    with (cache_dir / "portraits.json").open("w", encoding="utf-8") as handle:
        json.dump(portraits, handle)
    build_contact_sheet(crops, cache_dir / "contact_sheet.png")

    log.info("hero emoji sync: %d created, %d skipped (source: %s)", created, skipped, source)
    return created, skipped, emoji_map


def _rank_icon(name):
    """Read cached OpenDota medal art, fetching a missing image once."""
    path = RANK_ICON_CACHE_DIR / f"{name}.png"
    if path.exists():
        return path.read_bytes()
    data = _http_get_bytes(RANK_ICON_URL + name + ".png")
    RANK_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def render_medal_emoji(tier):
    """Combine Dota's medal shield and star overlay into one Discord PNG."""
    from PIL import Image

    base = Image.open(io.BytesIO(_rank_icon(f"rank_icon_{tier // 10}"))).convert("RGBA")
    base = base.resize((FINAL_SIZE, FINAL_SIZE), Image.LANCZOS)
    if tier < 80:
        star = Image.open(io.BytesIO(_rank_icon(f"rank_star_{tier % 10}"))).convert("RGBA")
        star = star.resize((FINAL_SIZE, FINAL_SIZE), Image.LANCZOS)
        base.alpha_composite(star)
    buf = io.BytesIO()
    base.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    if len(data) > EMOJI_MAX_BYTES:
        buf = io.BytesIO()
        base.convert("P", palette=Image.ADAPTIVE, colors=256).save(
            buf, format="PNG", optimize=True)
        data = buf.getvalue()
    return data


def sync_medal_emojis():
    """Upload missing Dota medal emojis and save a rank-tier token map."""
    cfg = load_scout_env()
    token = cfg["token"]
    app_id = cfg["application_id"]
    if not token or not app_id:
        raise RuntimeError("SCOUT_BOT_TOKEN and SCOUT_BOT_APPLICATION_ID are required")
    existing = {e["name"]: e["id"] for e in list_application_emojis(app_id, token)}
    emoji_map = {}
    created = skipped = 0
    for tier in [10 * rank + star for rank in range(1, 8)
                 for star in range(1, 6)] + [80]:
        name = f"medal_{tier}"
        if name in existing:
            skipped += 1
        else:
            emoji = create_application_emoji(app_id, token, name,
                                             render_medal_emoji(tier))
            existing[name] = emoji["id"]
            created += 1
        emoji_map[str(tier)] = f"<:{name}:{existing[name]}>"
    MEDAL_EMOJI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with (MEDAL_EMOJI_CACHE_DIR / "emoji_map.json").open("w", encoding="utf-8") as handle:
        json.dump(emoji_map, handle)
    return created, skipped, emoji_map


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Team Scout Discord bot")
    parser.add_argument(
        "--post-briefing", metavar="TEAM",
        help="Build a Scout Briefing embed for TEAM (one-shot, no gateway login)",
    )
    parser.add_argument(
        "--vs", metavar="TEAM", default=None,
        help="Opponent team; defaults to the team's current-week matchup",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the briefing instead of posting it to Discord",
    )
    parser.add_argument(
        "--sync-hero-emojis", action="store_true",
        help="Download OpenDota hero art and upload/sync Scout Bot application emojis",
    )
    parser.add_argument("--sync-medal-emojis", action="store_true",
                        help="Upload/sync Dota rank medals as Scout Bot application emojis")
    return parser


def main():
    os.makedirs(LOG_FILE.parent, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
    )
    args = build_arg_parser().parse_args()
    if args.sync_hero_emojis:
        created, skipped, _emoji_map = sync_hero_emojis()
        print(f"Hero emoji sync: {created} created, {skipped} skipped.")
        return
    if args.sync_medal_emojis:
        created, skipped, _emoji_map = sync_medal_emojis()
        print(f"Medal emoji sync: {created} created, {skipped} skipped.")
        return
    if args.post_briefing:
        post_briefing(args.post_briefing, vs=args.vs, dry_run=args.dry_run)
        return
    run()


if __name__ == "__main__":
    main()
