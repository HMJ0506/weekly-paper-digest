#!/usr/bin/env python3
"""
Record every DOI handled by a published local digest in digests/seen_dois.json,
so build_digest_input.py excludes them next week. Mirrors the cloud routine's
rule: retained entries AND documented false-positive discards both count as
covered.

Usage:  python record_published.py --input local_data/digest_input-2026-09-07.json
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "digests", "seen_dois.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="digest_input-*.json that was published")
    ap.add_argument("--digest-date", help="defaults to run_date in the input file")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        d = json.load(fh)
    date = args.digest_date or d["run_date"]
    seen = {}
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as fh:
            seen = json.load(fh)
    added = 0
    for c in d["candidates"]:
        k = c["doi"].lower()
        if k not in seen:
            seen[k] = {"digest_date": date, "title": c["title"], "journal": c["journal"]}
            added += 1
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("seen_dois.json: +%d (total %d) for digest %s" % (added, len(seen), date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
