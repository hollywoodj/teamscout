#!/usr/bin/env python3
"""
LD2L Scouting Tool - entry point.

Scrapes LD2L signups (ld2l.org), enriches players via the OpenDota API, and
generates a scouting spreadsheet + interactive HTML dashboard.

Requirements: pip install -r requirements.txt

Usage:
  python ld2l_scout.py                 # single run (Season 22)
  python ld2l_scout.py --loop          # auto-update every 2 hours
  python ld2l_scout.py --season 53     # explicit LD2L season id
  python ld2l_scout.py --force-refresh # ignore cache

Optional: set OPENDOTA_API_KEY env var for faster, uncapped API access.
"""

from scout.cli import main

if __name__ == "__main__":
    main()
