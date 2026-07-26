"""JSON file cache with per-section freshness timestamps."""

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager

from . import config


def _completed_match_payload(data):
    return (
        isinstance(data, dict)
        and bool(data.get("version"))
        and isinstance(data.get("players"), list)
    )


class Cache:
    _locks_guard = threading.Lock()
    _locks = {}

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

    @classmethod
    def _thread_lock(cls, path):
        key = os.path.abspath(path)
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @contextmanager
    def _file_lock(self, path):
        """Serialize read/modify/write cycles across threads and processes."""
        thread_lock = self._thread_lock(path)
        with thread_lock:
            lock_path = path + ".lock"
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(lock_path, "a+b") as lock_file:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                try:
                    import msvcrt
                except ImportError:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                else:
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            lock_file.seek(0)
                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(0.05)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    @staticmethod
    def _replace_with_retry(src, dst):
        for attempt in range(6):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _write_json_unlocked(self, path, data):
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(tmp, path)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _write_json(self, path, data):
        with self._file_lock(path):
            self._write_json_unlocked(path, data)

    # ---- per-player sections ----
    def _player_path(self, steam32):
        return self._path("players", f"{steam32}.json")

    def get_section(self, steam32, section, max_age_hours, force=False):
        """Return cached section data if fresh enough (None = any age), else None."""
        if force:
            return None
        doc = self._read_json(self._player_path(steam32))
        if not doc:
            return None
        entry = doc.get("sections", {}).get(section)
        if not entry:
            return None
        if max_age_hours is not None:
            age_h = (time.time() - entry.get("fetched_at", 0)) / 3600
            if age_h > max_age_hours:
                return None
        return entry.get("data")

    def set_section(self, steam32, section, data):
        path = self._player_path(steam32)
        with self._file_lock(path):
            doc = self._read_json(path) or {}
            doc.setdefault("sections", {})[section] = {
                "fetched_at": time.time(),
                "data": data,
            }
            self._write_json_unlocked(path, doc)

    # ---- immutable parsed match details ----
    def _match_path(self, match_id):
        return self._path("matches", f"{int(match_id)}.json")

    def get_match(self, match_id):
        """Return a cached normalized/raw match payload.

        Completed Dota matches are immutable, so these entries intentionally
        have no TTL. Missing or corrupt entries return None.
        """
        doc = self._read_json(self._match_path(match_id))
        if not isinstance(doc, dict):
            return None
        return doc.get("data")

    def set_match(self, match_id, data):
        path = self._match_path(match_id)
        with self._file_lock(path):
            existing = self._read_json(path)
            if (
                isinstance(existing, dict)
                and _completed_match_payload(existing.get("data"))
            ):
                return False
            self._write_json_unlocked(
                path,
                {"fetched_at": time.time(), "data": data},
            )
        return True

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
