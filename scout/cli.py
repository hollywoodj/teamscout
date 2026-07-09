"""CLI entry point: orchestrates scrape -> fetch -> analyze -> reports."""

import argparse
import signal
import sys
import time
from datetime import datetime

from . import config
from .analysis import build_metrics
from .auction import annotate_players, load_history
from .cache import Cache
from .fetch import fetch_player_sections, signup_delta
from .heroes import load_hero_map
from .ld2l import scrape_signups
from .opendota import OpenDota
from .report_html import generate_dashboard
from .report_xlsx import generate_spreadsheet


def run_scout(args):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print("  LD2L Scouting Tool")
    print(f"  Run started at: {now}")
    print("=" * 60)

    cache = Cache()
    od = OpenDota()

    season_label, players = scrape_signups(args.season)
    if not players:
        print("  ✗ No players found! Check if the signup page is accessible.")
        return False

    new_players, mmr_changes = signup_delta(cache, args.season, players)
    if new_players:
        print(f"\n  🆕 New signups since last run ({len(new_players)}):")
        for p in new_players:
            print(f"     + {p['name']} ({p['mmr']} MMR, captain={p['captain']})")
    if mmr_changes:
        print(f"\n  Δ MMR changes since last run:")
        for p in mmr_changes:
            print(f"     ~ {p['name']}: {p['mmr'] - p['mmr_change']} -> {p['mmr']}")

    hero_map = load_hero_map(od, cache)

    print(f"\n  Fetching OpenDota data for {len(players)} players "
          f"({'API key set' if config.API_KEY else 'free tier'}, cached data reused)...")
    all_data = []
    for i, player in enumerate(players, 1):
        sections, calls = fetch_player_sections(od, cache, player, force=args.force_refresh)
        data = build_metrics(player, sections, hero_map)
        all_data.append({"player": player, "data": data})
        cached_note = "cache" if calls == 0 else f"{calls} calls"
        print(f"  [{i}/{len(players)}] {player['name']} ({player['mmr']} MMR) [{cached_note}]")

    history = load_history(cache, args.season)
    annotate_players(all_data, history)

    xlsx_out = args.output or f"LD2L_{season_label}_Scouting.xlsx"
    html_out = args.html or f"LD2L_{season_label}_Scouting.html"

    print("\n" + "=" * 60)
    print("  Generating reports...")
    print("=" * 60)
    generate_spreadsheet(all_data, xlsx_out)
    generate_dashboard(all_data, html_out, season_label, args.season)

    active = sum(1 for d in all_data
                 if d["data"]["last_match_days"] is not None and d["data"]["last_match_days"] < 30)
    league_exp = sum(1 for d in all_data if d["data"]["has_league_exp"])
    punchers = sum(1 for d in all_data if d["data"]["punches_above"])
    print("\n📊 QUICK STATS:")
    print(f"  Total players: {len(players)}")
    print(f"  Active in last 30 days: {active}/{len(all_data)}")
    print(f"  With league games (6mo): {league_exp}")
    print(f"  Queueing above their medal: {punchers}")
    returning = sum(1 for d in all_data if d["data"]["last_cost_season"])
    print(f"  With past auction data: {returning} "
          f"(from {len(history)} seasons of draft history)")
    print(f"  OpenDota API calls this run: {od.calls}")
    if od.calls >= config.DAILY_CALL_WARNING:
        print(f"  ⚠ Heavy API usage — free tier has a daily cap; consider OPENDOTA_API_KEY")
    print(f"\n  📁 {xlsx_out}")
    print(f"  🌐 {html_out}")
    print(f"  ⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return True


def main():
    parser = argparse.ArgumentParser(description="LD2L Scouting Tool")
    parser.add_argument("--season", type=int, default=config.DEFAULT_SEASON_ID,
                        help=f"LD2L season id (default: {config.DEFAULT_SEASON_ID} = S22)")
    parser.add_argument("--output", type=str, default=None, help="xlsx output path")
    parser.add_argument("--html", type=str, default=None, help="HTML dashboard output path")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Ignore cache TTLs and refetch everything")
    parser.add_argument("--loop", action="store_true", help="Run repeatedly")
    parser.add_argument("--interval", type=int, default=7200,
                        help="Loop interval in seconds (default: 7200 = 2hrs)")
    args = parser.parse_args()

    def handle_sigint(sig, frame):
        print("\n\n👋 Scout shutting down. See you at the draft!")
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sigint)

    if args.loop:
        interval_min = args.interval // 60
        print("=" * 60)
        print(f"  🔄 LOOP MODE: Running every {interval_min} minutes (Ctrl+C to stop)")
        print("=" * 60)
        while True:
            try:
                ok = run_scout(args)
            except Exception as e:
                print(f"\n  ✗ Run crashed: {e}")
                ok = False
            print(f"\n  ⏳ Next update in {interval_min} minutes..." if ok
                  else f"\n  ⚠ Run failed. Retrying in {interval_min} minutes...")
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n\n👋 Scout shutting down. See you at the draft!")
                break
    else:
        run_scout(args)
        print(f"\n  💡 TIP: Run with --loop to auto-update every 2 hours")
