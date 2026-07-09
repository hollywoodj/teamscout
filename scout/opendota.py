"""OpenDota API client: rate limiting, retries, API key support, call counting."""

import time

import requests

from . import config


class OpenDota:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ld2l-scout/2.0"
        self.calls = 0
        self._last_call = 0.0

    def get(self, path, params=None):
        """Rate-limited GET. Returns parsed JSON or None on failure."""
        url = f"{config.API_BASE}{path}"
        params = dict(params or {})
        if config.API_KEY:
            params["api_key"] = config.API_KEY

        for attempt in range(config.API_MAX_RETRIES):
            wait = config.API_DELAY - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            try:
                r = self.session.get(url, params=params, timeout=20)
            except Exception as e:
                print(f"  ✗ Error for {path}: {e}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    print(f"  ⚠ Bad JSON for {path}")
                    return None
            if r.status_code == 429 or r.status_code >= 500:
                backoff = 5 * (attempt + 1)
                print(f"  ⚠ HTTP {r.status_code} for {path}, retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            print(f"  ⚠ HTTP {r.status_code} for {path}")
            return None
        return None

    # ---- endpoint helpers ----
    def player(self, sid):
        return self.get(f"/players/{sid}")

    def wl(self, sid, **params):
        return self.get(f"/players/{sid}/wl", params=params)

    def recent_matches(self, sid):
        return self.get(f"/players/{sid}/recentMatches")

    def player_heroes(self, sid):
        return self.get(f"/players/{sid}/heroes")

    def matches(self, sid, **params):
        return self.get(f"/players/{sid}/matches", params=params)

    def constants_heroes(self):
        return self.get("/constants/heroes")
