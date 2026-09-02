#!/usr/bin/env python3
"""
Runs discover.py in-process with dash normalization applied at runtime.
discover.py itself has carried the same fix since commit 0da45c6, so this is
now a harmless no-op kept as a safety net (and as the classify() entry point
for rss_supplement.py).

Fix: Unicode dashes -> ASCII hyphen before keyword matching.
  Wiley deposits titles/abstracts with U+2010 (HYPHEN), e.g. "Anode‐Less",
  "Anode‐Free". NFKC normalization in discover.clean() keeps U+2010, and the
  Topic-2 pattern "anode-?free|anode-?less" only knows the ASCII hyphen, so
  those papers are missed or mis-topic'd. Verified 2026-09-03 on
  10.1002/aenm.71042 (classified 3,4 but not 2) and 10.1002/aenm.71327 (missed).
  Metal-anode patterns already use a dash class that includes "-", so mapping
  every dash to "-" is safe for them.

Same CLI as discover.py:  python run_discover.py --run-date YYYY-MM-DD --out FILE
"""
import re, sys
import discover

_DASHES = re.compile(r"[‐‑‒–—―−]")
_orig_clean = discover.clean


def clean(text):
    return _DASHES.sub("-", _orig_clean(text))


def classify(title, abstract):
    """discover.classify with dash normalization (for callers outside discover)."""
    return discover.classify(clean(title), clean(abstract))


discover.clean = clean

if __name__ == "__main__":
    sys.exit(discover.main())
