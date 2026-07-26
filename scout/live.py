"""Live draft following — READ-ONLY.

Polls the public draft page (/seasons/{id}/draft) every few seconds and serves
the picked-up state to the dashboard over localhost. Nothing is ever posted to
ld2l.org: this pulls exactly what any spectator's browser sees.

Two sources, merged into one state dict:

- **HTML polling** (always on, no extra deps): the draft page carries one
  <tr name="draft-signup"> per player with data-team / data-cost /
  data-drafted, parsed by auction.DraftParser. Completed picks show up here
  within one poll interval.
- **Spectator socket** (optional): the draft page itself is driven by
  socket.io broadcasts (nominate / bid / drafted). If `python-socketio` 4.x
  is installed (`pip install "python-socketio<5" "python-engineio<4"
  websocket-client`), we join the same read-only broadcast room every
  spectator browser joins and learn *who is on the block right now* — that's
  what powers the dashboard's nomination banner. Listening only; no events
  are ever emitted beyond the connect handshake.

The dashboard (served at http://localhost:{port}/) polls /live/state and
auto-marks drafted players with price + winning team.
"""

import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

import requests

from . import config
from .auction import DraftParser
from .broadcast import SSEHub, draft_snapshot, make_handler
from .captains import budget_map, captain_map
from .ld2l import scrape_budgets

POLL_SECONDS = 3          # draft-page poll cadence (bid windows floor at 8s)
TEAMS_REFRESH_SECONDS = 300
SOCKET_RETRY_SECONDS = 30  # the /draft-{id} namespace only exists once an
                           # admin starts the draft, so keep retrying quietly


class LiveState:
    """Thread-safe snapshot of everything the follower currently knows."""

    def __init__(self, season_id):
        self._lock = threading.Lock()
        self.hub = SSEHub()    # open SSE writers, fanned out by broadcast.py
        self.season = season_id
        self.picks = {}        # steam32 -> {cost, team_id, captain, is_captain}
        self.captains = {}     # team_id -> captain name
        self.budgets = {}      # captain name -> budget
        self.nomination = None  # {steam32, name, by, amount, ts} | None
        self.round = None
        self.log = []          # last few site log lines (socket only)
        self.events = []       # feed for the dashboard: [{kind, ts, ...}]
        self.poll_ok = False
        self.poll_error = None
        self.socket_on = False
        self.updated = 0

    def snapshot(self):
        with self._lock:
            return draft_snapshot(
                season=self.season,
                picks=list(self.picks.values()),
                captains=dict(self.captains),
                budgets=dict(self.budgets),
                nomination=dict(self.nomination) if self.nomination else None,
                round=self.round,
                log=list(self.log[-12:]),
                events=list(self.events[-60:]),
                poll_ok=self.poll_ok,
                poll_error=self.poll_error,
                socket_on=self.socket_on,
                updated=self.updated,
            )

    def update(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)
            self.updated = time.time()

    def add_event(self, kind, **fields):
        with self._lock:
            ts = time.time()
            fields.update({
                "kind": kind,
                "ts": ts,
                "measured_at_ms": int(ts * 1000),  # follower's timestamp (ms) for latency beacon
            })
            self.events.append(fields)
            del self.events[:-80]
            self.updated = ts
        # push to all connected SSE clients immediately (outside the state lock)
        self.hub.broadcast(fields)


def _fetch_draft_rows(season_id):
    r = requests.get(f"{config.LD2L_BASE}/seasons/{season_id}/draft",
                     timeout=15, headers={"User-Agent": "ld2l-scout/2.0 (live)"})
    r.raise_for_status()
    parser = DraftParser()
    parser.feed(r.text)
    return parser.rows


def _poll_loop(state, stop):
    """Poll the draft page; diff against known picks; refresh team map."""
    last_teams = 0
    while not stop.is_set():
        now = time.time()
        if now - last_teams > TEAMS_REFRESH_SECONDS:
            teams = scrape_budgets(state.season)
            if teams:
                state.update(captains=captain_map(teams),
                             budgets=budget_map(teams))
            last_teams = now
        try:
            rows = _fetch_draft_rows(state.season)
        except Exception as e:
            state.update(poll_ok=False, poll_error=str(e))
        else:
            picks = {}
            for r in rows:
                if r["team"] is None and not r["drafted"]:
                    continue  # still on the board
                picks[r["steam32"]] = {
                    "steam32": r["steam32"],
                    "cost": r["cost"],
                    "team_id": r["team"],
                    "captain": state.captains.get(str(r["team"] or "")),
                    "is_captain": r["captain"],
                }
            with state._lock:
                new = [p for s, p in picks.items() if s not in state.picks]
                gone = state.nomination and state.nomination["steam32"] in picks
            for p in new:
                who = p["captain"] or f"team {p['team_id']}"
                tag = "captain of" if p["is_captain"] else \
                      f"${p['cost']} to" if p["cost"] else "picked by"
                print(f"  🔨 {p['steam32']} {tag} {who}")
                state.add_event("pick", steam32=p["steam32"], cost=p["cost"],
                                captain=p["captain"], team_id=p["team_id"],
                                is_captain=p["is_captain"])
            kw = {"picks": picks, "poll_ok": True, "poll_error": None}
            if gone:  # the nominee got awarded — poll saw it before the socket
                kw["nomination"] = None
            state.update(**kw)
        stop.wait(POLL_SECONDS)


def _socket_loop(state, stop):
    """Optional: join the draft's read-only socket.io broadcast room.

    The LD2L server runs socket.io v2, which needs python-socketio 4.x /
    python-engineio 3.x. Missing or incompatible installs degrade silently to
    polling-only (the banner just won't know about nominations).
    """
    try:
        import socketio
        if not socketio.__version__.startswith("4"):
            print("  ⚠ python-socketio v" + socketio.__version__ + " can't speak to "
                  "the site's socket.io v2 — nomination banner off. For it, run: "
                  'pip install "python-socketio<5" "python-engineio<4" websocket-client')
            return
    except ImportError:
        print('  ℹ No python-socketio — completed picks only (polling). For the live '
              '"on the block" banner: pip install "python-socketio<5" '
              '"python-engineio<4" websocket-client')
        return

    ns = f"/draft-{state.season}"

    def s32(player):
        try:
            return int(player.get("steamid", 0)) - config.STEAM64_OFFSET
        except (TypeError, ValueError, AttributeError):
            return None

    def pname(player):
        if isinstance(player, dict):
            return player.get("display_name") or player.get("name") or "?"
        return str(player or "?")

    while not stop.is_set():
        sio = socketio.Client(logger=False, engineio_logger=False,
                              reconnection=False)

        @sio.on("nominate", namespace=ns)
        def on_nominate(data):
            nom = data.get("nominee") or {}
            by = pname(data.get("by"))
            state.update(nomination={
                "steam32": s32(nom), "name": pname(nom),
                "by": by, "amount": data.get("amount", 0),
                "bid_ms": 15000,  # site opens every nomination at 15s
                "ts": time.time(),
            })
            state.add_event("nominate", steam32=s32(nom), name=pname(nom), by=by)
            print(f"  🔔 ON THE BLOCK: {pname(nom)} (by {by})")

        @sio.on("bid", namespace=ns)
        def on_bid(data):
            by = pname(data.get("by"))
            amount = data.get("amount")
            state.add_event("bid", by=by, amount=amount,
                            bid_ms=data.get("bidTime"))
            with state._lock:
                nom = state.nomination
            if nom:
                nom = dict(nom, by=by, amount=amount if amount is not None
                           else nom["amount"],
                           bid_ms=data.get("bidTime"), ts=time.time())
                state.update(nomination=nom)

        @sio.on("drafted", namespace=ns)
        def on_drafted(data):
            player = (data or {}).get("player") if isinstance(data, dict) else None
            player = player or data or {}
            state.add_event("sold", steam32=s32(player), name=pname(player))
            state.update(nomination=None)  # poll fills in price + team shortly

        @sio.on("round", namespace=ns)
        def on_round(data):
            rnd = (data or {}).get("round")
            if rnd is not None and rnd != state.round:
                state.add_event("round", round=rnd)
            state.update(round=rnd)

        @sio.on("log", namespace=ns)
        def on_log(data):
            lines = data if isinstance(data, list) else [data]
            with state._lock:
                state.log = (state.log + [str(x) for x in lines])[-40:]

        try:
            sio.connect(config.LD2L_BASE, namespaces=[ns], transports=["websocket"])
            state.update(socket_on=True)
            state.add_event("status", text="draft room connected — live feed on")
            print(f"  📡 Spectator socket connected ({ns}) — nomination banner live")
            while not stop.is_set() and sio.connected:
                stop.wait(1)
            if not stop.is_set():
                state.add_event("status", text="draft room disconnected — retrying…")
            sio.disconnect()
        except Exception:
            # namespace won't exist until an admin starts the draft — retry
            state.update(socket_on=False)
            stop.wait(SOCKET_RETRY_SECONDS)
        finally:
            state.update(socket_on=False)


def run_live(html_path, season_id, port=8322, open_browser=True):
    """Serve the dashboard + live draft state until Ctrl+C. Read-only.

    No ``post_handler`` is passed, so the shared server rejects every POST —
    live mode stays strictly read-only.
    """
    state = LiveState(season_id)
    stop = threading.Event()
    threads = [
        threading.Thread(target=_poll_loop, args=(state, stop), daemon=True),
        threading.Thread(target=_socket_loop, args=(state, stop), daemon=True),
    ]
    for t in threads:
        t.start()

    handler = make_handler(html_path, state.snapshot, state.hub)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://localhost:{port}/"
    print("\n" + "=" * 60)
    print("  🔴 LIVE DRAFT MODE (read-only — nothing is sent to ld2l.org)")
    print(f"  Dashboard: {url}")
    print(f"  Following: {config.LD2L_BASE}/seasons/{season_id}/draft "
          f"every {POLL_SECONDS}s")
    print("  Ctrl+C to stop")
    print("=" * 60 + "\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Live mode stopped.")
    finally:
        stop.set()
        server.server_close()
