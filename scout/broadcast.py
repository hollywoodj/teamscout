"""The dashboard wire protocol, owned in one place.

Both the read-only --live follower and the local --mock auction drive the same
scouting dashboard, which polls ``/live/state`` and streams ``/live/events``.
That shared contract used to be hand-maintained in three spots at once — a
snapshot dict literal in ``live.LiveState``, a second one in
``mockdraft.MockState``, and near-duplicate SSE + HTTP-handler code in each. This
module is the single home for all three:

- :func:`draft_snapshot` builds the canonical ``/live/state`` payload, so the key
  set has one definition. Add a field here and both producers gain it.
- :class:`SSEHub` owns the open Server-Sent-Events writers and fans events out.
- :func:`make_handler` is the one HTTP handler that serves the dashboard file,
  the state snapshot and the SSE stream (plus optional POST routes for --mock).

Nothing here talks to ld2l.org — it only serves localhost.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler

# The keys every /live/state snapshot carries. Documented here so the dashboard
# JS (report_html.liveApply) has one shape to trust; `log` is live-only and
# `mode`/`mock` are mock-only, added when the producer supplies them.
SNAPSHOT_KEYS = (
    "season", "picks", "captains", "budgets", "nomination", "round",
    "events", "poll_ok", "poll_error", "socket_on", "updated",
)


def draft_snapshot(*, season, picks, captains, budgets, nomination, round,
                   events, poll_ok, poll_error, socket_on, updated,
                   log=None, mode=None, mock=None):
    """Assemble the canonical /live/state payload.

    The common core is always present; ``mode``/``mock`` (mock auction) and
    ``log`` (live socket feed) are included only when the caller passes them, so
    each producer emits exactly the shape it did before this collapse.
    """
    snap = {
        "season": season,
        "picks": picks,
        "captains": captains,
        "budgets": budgets,
        "nomination": nomination,
        "round": round,
        "events": events,
        "poll_ok": poll_ok,
        "poll_error": poll_error,
        "socket_on": socket_on,
        "updated": updated,
    }
    if mode is not None:
        snap["mode"] = mode
    if log is not None:
        snap["log"] = log
    if mock is not None:
        snap["mock"] = mock
    return snap


class SSEHub:
    """The open Server-Sent-Events writers, with a lock of their own.

    Registration happens on request threads and broadcasts on the poll/engine
    thread; the hub's lock keeps the writer list consistent between them. Dead
    writers are dropped on the next broadcast.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = []

    def add(self, writer):
        with self._lock:
            self._clients.append(writer)

    def remove(self, writer):
        with self._lock:
            try:
                self._clients.remove(writer)
            except ValueError:
                pass

    def broadcast(self, event):
        """Push one event dict to every live client; prune the broken ones."""
        payload = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        with self._lock:
            live = []
            for w in self._clients:
                try:
                    w.write(payload)
                    w.flush()
                    live.append(w)
                except (BrokenPipeError, OSError):
                    pass
            self._clients[:] = live


def make_handler(html_path, snapshot_fn, hub, post_handler=None):
    """Build the BaseHTTPRequestHandler both --live and --mock serve.

    ``snapshot_fn()`` returns the current /live/state dict. ``hub`` is the
    :class:`SSEHub` events fan out through. ``post_handler(path, body)`` (mock
    only) returns ``(code, obj)`` for a matched route or ``None`` for 404; when
    it's ``None`` the server rejects every POST, keeping live mode read-only.
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console clear for draft events
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json", json.dumps(obj).encode())

        def _read_json_body(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                return body if isinstance(body, dict) else {}
            except (ValueError, json.JSONDecodeError):
                return {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                try:
                    with open(html_path, "rb") as f:
                        self._send(200, "text/html; charset=utf-8", f.read())
                except OSError as e:
                    self._send(500, "text/plain", str(e).encode())
            elif path == "/live/state":
                self._json(200, snapshot_fn())
            elif path in ("/live/events", "/mock/events"):
                # Server-Sent Events: bid/nominate/sold events pushed in real
                # time, with a 15s heartbeat that also detects dead clients.
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                hub.add(self.wfile)
                try:
                    last_hb = time.time()
                    while True:
                        now = time.time()
                        if now - last_hb > 15:
                            try:
                                self.wfile.write(b": heartbeat\n\n")
                                self.wfile.flush()
                            except (BrokenPipeError, OSError):
                                break
                            last_hb = now
                        time.sleep(1)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    hub.remove(self.wfile)
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            if post_handler is None:
                self._send(404, "text/plain", b"not found")
                return
            path = self.path.split("?")[0]
            result = post_handler(path, self._read_json_body())
            if result is None:
                self._send(404, "text/plain", b"not found")
            else:
                code, obj = result
                self._json(code, obj)

    return Handler
