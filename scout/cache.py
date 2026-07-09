"""JSON file cache with per-section freshness timestamps."""

import json
import os
import time

from . import config


class Cache:
    def __init__(self, root=None):
        self.root = root or config.CACHE_DIR
        os.makedirs(os.path.join(self.root, "players"), exist_ok=True)

    def _path(self, *parts):
        return os.path.join(self.root, *parts)

    def _read_json(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_json(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    # ---- per-player sections ----
    def _player_path(self, steam32):
        return self._path("players", f"{steam32}.json")

    def get_section(self, steam32, section, max_age_hours, force=False):
        """Return cached section data if fresh enough, else None."""
        if force:
            return None
        doc = self._read_json(self._player_path(steam32))
        if not doc:
            return None
        entry = doc.get("sections", {}).get(section)
        if not entry:
            return None
        age_h = (time.time() - entry.get("fetched_at", 0)) / 3600
        if age_h > max_age_hours:
            return None
        return entry.get("data")

    def set_section(self, steam32, section, data):
        path = self._player_path(steam32)
        doc = self._read_json(path) or {}
        doc.setdefault("sections", {})[section] = {
            "fetched_at": time.time(),
            "data": data,
        }
        self._write_json(path, doc)

    # ---- generic named blobs (hero constants, signup snapshots) ----
    def get_blob(self, name, max_age_hours=None):
        doc = self._read_json(self._path(f"{name}.json"))
        if not doc:
            return None
        if max_age_hours is not None:
            age_h = (time.time() - doc.get("fetched_at", 0)) / 3600
            if age_h > max_age_hours:
                return None
        return doc.get("data")

    def set_blob(self, name, data):
        self._write_json(self._path(f"{name}.json"), {"fetched_at": time.time(), "data": data})
