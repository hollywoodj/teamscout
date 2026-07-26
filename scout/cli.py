"""CLI entry point: orchestrates scrape -> fetch -> analyze -> reports."""

import argparse
import glob
import os
import signal
import sys
import time
from datetime import datetime

from . import config
from .analysis import build_metrics, pool_analysis, select_value_picks
from .auction import annotate_players, load_history, measure_predictions
from .cache import Cache
from .captains import budget_map, load_official_teams
from .esports import load_ticketed_histories
from .fetch import (apply_mmr_baseline, fetch_player_sections,
                    players_from_snapshot, signup_delta)
from .heroes import load_hero_map
from .ld2l import scrape_signups
from .opendota import OpenDota
from .report_html import generate_dashboard
from .report_player_html import generate_player_reports, report_filenames
from .report_xlsx import generate_spreadsheet


def run_scout(args):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print("  LD2L Scouting Tool")
    print(f"  Run started at: {now}")
    print("=" * 60)

    cache = Cache()
    od = OpenDota()

    if args.offline:
        snap_label, players = players_from_snapshot(cache, args.season)
        season_label = snap_label or f"Season {args.season}"
        print(f"\n📴 OFFLINE: {len(players)} players from last signup snapshot "
              f"(cache used regardless of age, no network)")
        if not players:
            print("  ✗ No snapshot yet — run online once first.")
            return False
        new_players, mmr_changes = [], []
    else:
        season_label, players = scrape_signups(args.season)
        if not players:
            print("  ✗ No players found! Check if the signup page is accessible.")
            return False
        new_players, mmr_changes = signup_delta(cache, args.season, players, season_label)

    apply_mmr_baseline(cache, args.season, players)
    if new_players:
        print(f"\n  🆕 New signups since last run ({len(new_players)}):")
        for p in new_players:
            print(f"     + {p['name']} ({p['mmr']} MMR, captain={p['captain']})")
    if mmr_changes:
        print(f"\n  Δ MMR changes since last run:")
        for p in mmr_changes:
            print(f"     ~ {p['name']}: {p['mmr'] - p['mmr_change']} -> {p['mmr']}")

    hero_map = load_hero_map(od, cache, offline=args.offline)
    ticketed = load_ticketed_histories(
        od,
        cache,
        args.season,
        [player["steam32"] for player in players],
        hero_map,
        offline=args.offline,
        force=args.force_refresh,
    )

    print(f"\n  Fetching OpenDota data for {len(players)} players "
          f"({'API key set' if config.API_KEY else 'free tier'}, cached data reused)...")
    all_data = []
    for i, player in enumerate(players, 1):
        sections, calls = fetch_player_sections(od, cache, player,
                                                force=args.force_refresh,
                                                offline=args.offline)
        sections["esports"] = ticketed[player["steam32"]]
        data = build_metrics(player, sections, hero_map)
        all_data.append({"player": player, "data": data})
        cached_note = "cache" if calls == 0 else f"{calls} calls"
        print(f"  [{i}/{len(players)}] {player['name']} ({player['mmr']} MMR) [{cached_note}]")

    if args.offline:
        history = cache.get_blob("auction_history_v2") or {}
        history = history.get("seasons", []) if isinstance(history, dict) else []
    else:
        history = load_history(cache, args.season)
    estimator = annotate_players(all_data, history)
    pool_analysis(all_data, price_estimator=estimator)

    xlsx_out = args.output or f"LD2L_{season_label}_Scouting.xlsx"
    html_out = args.html or f"LD2L_{season_label}_Scouting.html"

    print("\n" + "=" * 60)
    print("  Generating reports...")
    print("=" * 60)
    # Dashboard and mock mode share the same validated, season-scoped official
    # roster loader. Online runs refresh it; offline regeneration retains the
    # last valid website budgets. budgets.json remains the final override.
    teams, roster_from, budgets_err = load_official_teams(
        args.season, cache, offline=args.offline
    )
    if teams:
        print(f"  💵 Team budgets from {roster_from} "
              f"({len(budget_map(teams))} teams): "
              + ", ".join(f"{t['captain']} ${t['budget']}" for t in teams[:10]))
    if budgets_err:
        print(f"  ⚠ {budgets_err}")
    budgets = budget_map(teams)

    generate_spreadsheet(all_data, xlsx_out)
    report_map = None
    if not args.no_reports:
        reports_dir = generate_player_reports(
            all_data, season_label, offline=args.offline
        )
        report_map = report_filenames(all_data)  # same map → dashboard links match
    generate_dashboard(
        all_data, html_out, season_label, args.season, budgets, report_map,
        offline=args.offline,
    )
    if not args.no_reports:
        print(f"  📝 Per-player scout reports: {reports_dir}\\index.html "
              f"({len(all_data)} pages) — 🔍 on each dashboard row opens them")

    active = sum(1 for d in all_data
                 if d["data"]["last_match_days"] is not None and d["data"]["last_match_days"] < 30)
    esports_exp = sum(
        1 for d in all_data if d["data"]["esports_6mo_games"] > 0
    )
    punchers = sum(1 for d in all_data if d["data"]["punches_above"])
    private = [pd for pd in all_data if pd["data"]["private_profile"]]
    print("\n📊 QUICK STATS:")
    print(f"  Total players: {len(players)}")
    print(f"  Active in last 30 days: {active}/{len(all_data)}")
    print(f"  With ticketed esports games (6mo): {esports_exp}")
    print(f"  Queueing above their medal: {punchers}")
    if private:
        print(f"  🔒 Private profiles (no exposed match data): {len(private)} — "
              + ", ".join(pd["player"]["name"] for pd in private[:12]))

    picks, unrated = select_value_picks(all_data)
    if picks:
        print("\n💎 TOP VALUE (skill vs listed MMR, priced by past auctions):")
        for pd, reasons, _ in picks[:8]:
            p, d = pd["player"], pd["data"]
            edge = f"edge ~{d['edge_cost']:+d}$" if d["edge_cost"] is not None else ""
            gap = f"gap {d['value_gap']:+d}" if d["value_gap"] is not None else ""
            print(f"  {p['name'][:24]:24s} listed {p['mmr']:4d}  plays ~{d['adj_skill'] or '?':4}  "
                  f"{gap:9s} {edge:12s} | {reasons[0][:60]}")

    # Model accuracy: compare predictions vs actual prices (if draft data exists)
    metrics = measure_predictions(estimator, all_data, history)
    if metrics and metrics["count"] > 0:
        print(f"\n📊 MODEL ACCURACY (last {len(history)} seasons, leave-one-out):")
        print(f"  Base price vs actual, predicted from draft-day MMR with the player's own")
        print(f"  sales held out: MAE ≈ ${metrics['mae']} (RMSE ${metrics['rmse']}), n={metrics['count']}")
        if metrics["errors"]:
            print(f"  Biggest misses (top 5):")
            for err in metrics["errors"][:5]:
                print(f"    {err['name'][:20]:20s} pred ${err['predicted']:3d}, actual ${err['actual']:3d} (${err['error']:+3d})")
    if unrated:
        print("\n❓ UNRATED SIGNUPS (placeholder listed MMR — expect a re-rate before draft):")
        for pd in unrated:
            p, d = pd["player"], pd["data"]
            print(f"  {p['name'][:24]:24s} listed {p['mmr']:4d} but plays ~{d['adj_skill']} "
                  f"({d['skill_srcs']})")
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


def run_live_mode(args):
    """Draft-day mode: serve the dashboard + follow the live draft (read-only)."""
    from .live import run_live

    html = args.html
    if not html:
        candidates = glob.glob("LD2L_*_Scouting.html")
        if not candidates:
            print("  ✗ No dashboard found. Run the scout once first "
                  "(python ld2l_scout.py), then start --live.")
            return
        html = max(candidates, key=os.path.getmtime)
    if not os.path.exists(html):
        print(f"  ✗ Dashboard not found: {html}")
        return
    run_live(html, args.season, port=args.port)


def run_mock_mode(args):
    """Practice mode: run a local mock auction against AI captains (offline-safe).

    Serves your real scouting dashboard (same file as --live) and drives its
    ticker / feed / budgets from the local auction, adding interactive controls.
    """
    from .mockdraft import run_mock

    html = args.html
    if not html:
        candidates = glob.glob("LD2L_*_Scouting.html")
        if not candidates:
            print("  ✗ No dashboard found. Run the scout once first "
                  "(python ld2l_scout.py), then start --mock.")
            return
        html = max(candidates, key=os.path.getmtime)
    if not os.path.exists(html):
        print(f"  ✗ Dashboard not found: {html}")
        return
    run_mock(
        html,
        args.season,
        me=args.me,
        port=args.port,
        offline=args.offline,
        roster_source=args.roster,
    )


def run_herodraft_mode(args):
    """Hero-draft practice: Captains Mode pick/ban vs a bot built from the
    opposing roster's real hero data (self-contained page, no dashboard needed)."""
    from .herodraft import run_herodraft

    # --port defaults to the live/mock port; give --herodraft its own default
    # so both practice servers can run side by side.
    port = args.port if args.port != 8322 else config.HERODRAFT_PORT
    run_herodraft(args.season, port=port, offline=args.offline)


def build_parser():
    parser = argparse.ArgumentParser(description="LD2L Scouting Tool")
    parser.add_argument("--season", type=int, default=config.DEFAULT_SEASON_ID,
                        help=f"LD2L season id (default: {config.DEFAULT_SEASON_ID} = S22)")
    parser.add_argument("--output", type=str, default=None, help="xlsx output path")
    parser.add_argument("--html", type=str, default=None, help="HTML dashboard output path")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Ignore cache TTLs and refetch everything")
    parser.add_argument("--offline", action="store_true",
                        help="No network: rebuild reports from cached data only "
                             "(draft-day safe mode)")
    parser.add_argument("--no-reports", action="store_true",
                        help="Skip generating the per-player HTML scout reports "
                             "(scout_reports/)")
    parser.add_argument("--loop", action="store_true", help="Run repeatedly")
    parser.add_argument("--interval", type=int, default=7200,
                        help="Loop interval in seconds (default: 7200 = 2hrs)")
    parser.add_argument("--live", action="store_true",
                        help="Draft-day live mode: serve the dashboard on "
                             "localhost and follow the ld2l.org draft page "
                             "(read-only) — picks mark themselves")
    parser.add_argument("--port", type=int, default=8322,
                        help="Port for --live / --mock mode (default: 8322)")
    parser.add_argument("--mock", action="store_true",
                        help="Local MOCK draft: practice a full auction against "
                             "AI captains in the browser (offline-safe, nothing "
                             "sent to ld2l.org)")
    parser.add_argument(
        "--roster",
        choices=("curated", "official"),
        help="Captain/budget source for --mock (default: curated)",
    )
    parser.add_argument(
        "--official-roster",
        dest="roster",
        action="store_const",
        const="official",
        help="Use finalized captains and budgets from the LD2L teams page",
    )
    parser.add_argument("--herodraft", action="store_true",
                        help="Hero draft practice: Captains Mode pick/ban "
                             "(patch 7.40 order) against a bot that drafts "
                             "from the enemy roster's real hero data")
    parser.add_argument("--me", type=str, default=config.MOCK_DEFAULT_ME,
                        help=f"Your captain seat for --mock (default: "
                             f"{config.MOCK_DEFAULT_ME}; changeable in the UI)")
    parser.set_defaults(roster="curated")
    return parser


def main():
    args = build_parser().parse_args()

    def handle_sigint(sig, frame):
        print("\n\n👋 Scout shutting down. See you at the draft!")
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sigint)

    if args.herodraft:
        run_herodraft_mode(args)
    elif args.mock:
        run_mock_mode(args)
    elif args.live:
        run_live_mode(args)
    elif args.loop:
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
