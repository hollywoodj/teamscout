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

    def match(self, match_id):
        return self.get(f"/matches/{int(match_id)}")

    def request_parse(self, match_id):
        """Ask OpenDota to parse a finished match. Ward coordinates live in that parse."""
        url = f"{config.API_BASE}/request/{int(match_id)}"
        params = {"api_key": config.API_KEY} if config.API_KEY else None
        wait = config.API_DELAY - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        self.calls += 1
        try:
            response = self.session.post(url, params=params, timeout=20)
        except Exception as exc:
            print(f"  ✗ Parse request failed for {match_id}: {exc}")
            return None
        if response.status_code in (200, 400):
            try:
                return response.json()
            except ValueError:
                return {}
        print(f"  ⚠ HTTP {response.status_code} requesting parse for {match_id}")
        return None

    def wordcloud(self, sid):
        return self.get(f"/players/{sid}/wordcloud")

    def explorer(self, sql):
        payload = self.get("/explorer", params={"sql": sql})
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            return None
        return payload["rows"]

    def constants_heroes(self):
        return self.get("/constants/heroes")

    def constants_patch(self):
        """Major-patch ids, names, and release timestamps."""
        return self.get("/constants/patch")

    def hero_stats(self):
        """Current-patch pub pick/win counts per hero, split by rank bracket."""
        return self.get("/heroStats")

    def hero_matchups(self, hero_id):
        """Per-opponent games/wins for one hero (organized-match sample)."""
        return self.get(f"/heroes/{hero_id}/matchups")

    def search(self, query):
        """Steam persona-name search (Team Scout's "pull player" lookup)."""
        return self.get("/search", params={"q": query})

    def league(self, league_id):
        """League metadata: name, tier, ticket, banner."""
        return self.get(f"/leagues/{int(league_id)}")

    def league_match_ids(self, league_id):
        """Every match id OpenDota has recorded for one league (any tier)."""
        return self.get(f"/leagues/{int(league_id)}/matchIds")
