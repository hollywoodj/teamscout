"""Persisted Team Scout overrides: pulled players, edited rosters, and
replaced (former) player ids. Lives at the repo root as
teamscout_overrides.json (gitignored)."""

import json
import os
import tempfile
import threading

from . import config

_LOCK = threading.RLock()


def overrides_path(path=None):
    return path or config.TEAMSCOUT_OVERRIDES_FILE


def load_overrides(path=None):
    path = overrides_path(path)
    with _LOCK:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    players = data.get("players")
    rosters = data.get("rosters")
    replaced = data.get("replaced")
    accounts = {}
    raw_accounts = data.get("accounts")
    if isinstance(raw_accounts, dict):
        for user, bucket in raw_accounts.items():
            if not isinstance(bucket, dict):
                continue
            accounts[str(user)] = {
                "players": dict(bucket["players"]) if isinstance(bucket.get("players"), dict) else {},
                "rosters": dict(bucket["rosters"]) if isinstance(bucket.get("rosters"), dict) else {},
                "replaced": dict(bucket["replaced"]) if isinstance(bucket.get("replaced"), dict) else {},
            }
    return {
        "players": dict(players) if isinstance(players, dict) else {},
        "rosters": dict(rosters) if isinstance(rosters, dict) else {},
        "replaced": dict(replaced) if isinstance(replaced, dict) else {},
        "accounts": accounts,
    }


def save_overrides(data, path=None):
    path = overrides_path(path)
    with _LOCK:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
