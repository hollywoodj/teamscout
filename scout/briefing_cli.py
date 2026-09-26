"""CLI snapshot generator for the Scout Bot: builds a Team Scout payload
offline and writes the Briefing + Wards Components V2 pages (plus any PNG
files) to disk, so the bot can post/refresh them without importing LD2L
Scout in-process.

Usage (run with cwd = the LD2L Scout checkout, since Team Scout's on-disk
cache is resolved relative to the working directory):

    python -m scout.briefing_cli --team "Team Name" [--vs "Other Team"] \\
        --out DIR [--season 53] [--emoji-map PATH] [--portraits PATH]

Writes DIR/briefing.json, DIR/wards.json (each
{"components": [...], "attachments": [filenames]}), any referenced PNG
files, and DIR/meta.json. The last line printed to stdout is the meta JSON
object (all other output, including Team Scout's own progress prints, is
suppressed / redirected).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
import time
from pathlib import Path

from .bbc_source import team_key as _team_key
from .briefing import _find_team, build_briefing_page, build_wards_page
from .team_scout import build_payload
from .ward_render import render_mid_ward


def _load_json_map(path):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _snapshot_id(team_key_value, vs_key_value, generated_at):
    digest = hashlib.sha1(f"{team_key_value}|{vs_key_value}|{generated_at}".encode("utf-8")).hexdigest()
    return digest[:12]


def _write_page(out_dir, name, page):
    filenames = []
    for filename, data in page.get("files") or []:
        with (out_dir / filename).open("wb") as handle:
            handle.write(data)
        filenames.append(filename)
    doc = {"components": page["components"], "attachments": filenames}
    with (out_dir / f"{name}.json").open("w", encoding="utf-8") as handle:
        json.dump(doc, handle)
    return filenames


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Team Scout Discord bot snapshot generator")
    parser.add_argument("--team", required=True, help="Team name/short/key to scout")
    parser.add_argument("--vs", default=None, help="Opponent team; defaults to the current matchup")
    parser.add_argument("--out", required=True, help="Output directory for the snapshot")
    parser.add_argument("--season", type=int, default=53, help="Team Scout season id (default 53)")
    parser.add_argument("--emoji-map", default=None, help="Path to a hero_id -> Discord emoji token JSON map")
    parser.add_argument("--portraits", default=None, help="Path to a hero_id -> portrait URL JSON map")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    hero_emoji = _load_json_map(args.emoji_map)
    portraits = _load_json_map(args.portraits)

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            payload = build_payload(args.season, offline=True)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Team Scout payload build failed: {exc}", file=sys.stderr)
        return 1

    if not payload:
        print(f"Team Scout returned no payload for season {args.season}", file=sys.stderr)
        return 1

    try:
        briefing_page = build_briefing_page(payload, args.team, vs=args.vs,
                                             hero_emoji=hero_emoji, portraits=portraits)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        team_row = _find_team(payload, args.team)
        midward_bytes, mid_ward_summary = render_mid_ward(payload, team_row)
        wards_page = build_wards_page(
            payload, args.team, vs=args.vs, hero_emoji=hero_emoji,
            extra_images=[("midward.png", midward_bytes, "Mid ward before 1:00, rune to rune")],
            mid_ward_summary=mid_ward_summary,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _write_page(out_dir, "briefing", briefing_page)
    _write_page(out_dir, "wards", wards_page)

    team_key_value = _team_key(args.team)
    vs_key_value = _team_key(args.vs) if args.vs else ""
    generated_at = int(time.time())

    meta = {
        "team": args.team,
        "teamKey": team_key_value,
        "vs": args.vs,
        "vsKey": vs_key_value,
        "generatedAt": generated_at,
        "id": _snapshot_id(team_key_value, vs_key_value, generated_at),
    }
    with (out_dir / "meta.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle)

    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
