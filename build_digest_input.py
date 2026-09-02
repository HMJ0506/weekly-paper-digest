#!/usr/bin/env python3
"""
Weekly Paper Digest - local orchestrator.

1. Runs discover.py (this repo's discovery stage, via the run_discover.py
   shim) twice: for
   --run-date D and for D minus --overlap-days, so papers Crossref indexed
   late at the end of last week's window are recovered this week.
2. Ports the GitHub Actions sanity checks (every journal reachable, 16 journals,
   zero-scan warning for the four created-date journals, truncation, enrichment).
3. Runs the RSS supplement, attaches Cell Press summaries to Joule candidates.
4. Removes DOIs already published in a previous LOCAL digest (digests/seen_dois.json).
5. Writes local_data/digest_input-D.json for the writing step (/weekly-digest skill).
   local_data/ is git-ignored; data/ belongs to the GitHub Actions discovery job.

Usage:
  python build_digest_input.py [--run-date 2026-09-07] [--overlap-days 2]
                               [--opml feedly.opml] [--skip-discovery] [--no-rss]
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "local_data")   # data/ is owned by the GitHub Actions job
DIGESTS = os.path.join(HERE, "digests")
SEEN = os.path.join(DIGESTS, "seen_dois.json")
CREATED_DATE_JOURNALS = ("Energy & Environmental Science", "Chemical Society Reviews",
                         "Joule", "Science")
RSC_JOURNALS = ("Energy & Environmental Science", "Chemical Society Reviews")


def run_discovery(run_date, out_path, log_path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # run_discover.py = discover.py + runtime dash-normalization fix (see file).
    cmd = [sys.executable, os.path.join(HERE, "run_discover.py"),
           "--run-date", run_date, "--out", out_path]
    print(">> %s" % " ".join(cmd[1:]))
    with open(log_path, "w", encoding="utf-8") as log:
        rc = subprocess.call(cmd, cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    if rc != 0:
        print("!! discover.py exited %d - see %s" % (rc, log_path))
    return rc


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sanity(d, label):
    """Same assertions as .github/workflows/weekly-discovery.yml. Returns error count."""
    errors = 0
    if d.get("unreachable"):
        print("ERROR [%s] unreachable journals: %s" % (label, d["unreachable"]))
        errors += 1
    stats = {s["journal"]: s["scanned"] for s in d["journal_stats"]}
    if len(stats) != 16:
        print("ERROR [%s] expected 16 journals, got %d" % (label, len(stats)))
        errors += 1
    for j in CREATED_DATE_JOURNALS:
        if stats.get(j, 0) == 0:
            print("WARN  [%s] %s scanned 0 records - check the date-field strategy" % (label, j))
    if d.get("truncated_journals"):
        print("WARN  [%s] truncated (cursor paging ended early): %s" % (label, d["truncated_journals"]))
    for f in d.get("enrich_failures") or []:
        print("WARN  [%s] abstract enrichment failed for %s (%s): %s"
              % (label, f["doi"], f["journal"], f["error"]))
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", help="YYYY-MM-DD (KST). Default: today in KST.")
    ap.add_argument("--overlap-days", type=int, default=2,
                    help="second discovery run at run_date - N days (0 disables)")
    ap.add_argument("--opml", default=os.path.join(HERE, "feedly.opml"))
    ap.add_argument("--skip-discovery", action="store_true",
                    help="reuse existing data/candidates-*.json instead of re-running discover.py")
    ap.add_argument("--no-rss", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    run = (datetime.strptime(args.run_date, "%Y-%m-%d").date() if args.run_date
           else (datetime.now(timezone.utc) + timedelta(hours=9)).date())
    D = run.isoformat()
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(DIGESTS, exist_ok=True)

    # ---- 1. discovery (primary + overlap) ------------------------------------
    primary = os.path.join(DATA, "candidates-%s.json" % D)
    runs = [(D, primary, os.path.join(DATA, "discovery-%s.log" % D))]
    if args.overlap_days > 0:
        D2 = (run - timedelta(days=args.overlap_days)).isoformat()
        runs.append((D2, os.path.join(DATA, "candidates-%s.overlap.json" % D),
                     os.path.join(DATA, "discovery-%s.overlap.log" % D)))
    if not args.skip_discovery:
        for rd, out, log in runs:
            if run_discovery(rd, out, log) != 0:
                return 1
    for _, out, _ in runs:
        if not os.path.exists(out):
            print("ERROR missing %s (run without --skip-discovery)" % out)
            return 1

    prim = load(primary)
    errors = sanity(prim, "primary")
    merged, origin = {}, {}
    for c in prim["candidates"]:
        c = dict(c, source="crossref")
        merged[c["doi"].lower()] = c
        origin[c["doi"].lower()] = "primary"
    overlap_doc, overlap_new = None, []
    if len(runs) > 1:
        overlap_doc = load(runs[1][1])
        errors += sanity(overlap_doc, "overlap")
        for c in overlap_doc["candidates"]:
            k = c["doi"].lower()
            if k not in merged:
                merged[k] = dict(c, source="crossref", from_overlap_run=True)
                origin[k] = "overlap"
                overlap_new.append(k)

    # ---- 2. RSS supplement ---------------------------------------------------
    rss = None
    if not args.no_rss:
        sys.path.insert(0, HERE)
        import rss_supplement
        print("-" * 78)
        ws, we = prim["window_start"], prim["window_end"]
        if overlap_doc:
            ws = min(ws, overlap_doc["window_start"])
        rss = rss_supplement.run(D, ws, we, opml=args.opml, known_dois=merged.keys())
        with open(os.path.join(DATA, "rss-%s.json" % D), "w", encoding="utf-8") as fh:
            json.dump(rss, fh, ensure_ascii=False, indent=1)
        for it in rss["rss_only"]:
            merged[it["doi"]] = it
            origin[it["doi"]] = "rss"
        # Abstract fallbacks for what discover.py could not get (subscription
        # Nature titles behind the bot challenge, Joule). discover.py is not
        # modified; this runs on its output.
        for c in merged.values():
            abstract = c.get("abstract") or ""
            # RSC deposits one-sentence or mid-sentence-truncated abstracts to
            # Crossref; treat those as missing and look for the full text.
            rsc_truncated = (c["journal"] in RSC_JOURNALS and
                             (len(abstract) < 400 or abstract.endswith("...")))
            if abstract and not rsc_truncated:
                continue
            if c["journal"] == "Joule":
                s = rss["cellpress_summaries"].get(c["doi"].lower())
                if s:
                    c["abstract"], c["abstract_source"] = s, "cellpress rss summary"
                    continue
            for fn, label in ((rss_supplement.openalex_abstract, "openalex"),
                              (rss_supplement.s2_abstract, "semantic scholar")):
                s = fn(c["doi"])
                if s and len(s) > 1.2 * len(abstract):   # only a materially fuller text
                    c["abstract"] = s
                    c["abstract_source"] = label + (" (RSC deposit truncated)" if rsc_truncated else "")
                    c.pop("enrich_error", None)
                    break

    # ---- 3. dedupe against previous local digests ----------------------------
    seen = load(SEEN) if os.path.exists(SEEN) else {}
    new, covered = [], []
    for k, c in merged.items():
        (covered if k in seen else new).append(dict(c, seen_in=seen.get(k)))
    new.sort(key=lambda c: (c["journal"], c.get("date", "")))

    # ---- 4. write --------------------------------------------------------------
    out = {
        "run_date": D,
        "window_start": prim["window_start"], "window_end": prim["window_end"],
        "overlap_window_start": overlap_doc["window_start"] if overlap_doc else None,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "discovery_mode": "local: Crossref REST API x%d (overlap %d d) + RSS supplement"
                          % (len(runs), args.overlap_days if len(runs) > 1 else 0),
        "journal_stats": prim["journal_stats"],
        "unreachable": prim["unreachable"],
        "truncated_journals": prim["truncated_journals"],
        "enrich_failures": prim.get("enrich_failures", []),
        "cof_pba_flagged": sorted(set(prim.get("cof_pba_flagged", []) +
                                      (overlap_doc.get("cof_pba_flagged", []) if overlap_doc else []))),
        "no_abstract_dois": [c["doi"] for c in new if not c.get("abstract")],
        "recovered_from_overlap_run": overlap_new,
        "rss": None if rss is None else {
            "feeds_total": rss["feeds_total"],
            "unreachable_feeds": [(r["journal"], r["error"]) for r in rss["unreachable_feeds"]],
            "items_in_window": rss["items_in_window"],
            "items_keyword_pass": rss["items_keyword_pass"],
            "overlap_with_crossref": len(rss["overlap_with_crossref"]),
            "rss_only": len(rss["rss_only"]),
            "rss_only_unverified_date": rss["rss_only_unverified_date"],
            "rss_out_of_window": rss["rss_out_of_window"],
            "opml_used": rss["opml_used"],
        },
        "candidates": new,
        "already_covered": covered,
    }
    path = args.out or os.path.join(DATA, "digest_input-%s.json" % D)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    # ---- 5. console summary ----------------------------------------------------
    print("=" * 78)
    print("RUN_DATE %s   window %s..%s   overlap-run window start %s"
          % (D, out["window_start"], out["window_end"], out["overlap_window_start"]))
    print("%-32s %-8s %7s %10s" % ("journal", "field", "scanned", "candidates"))
    for s in prim["journal_stats"]:
        print("%-32s %-8s %7d %10d" % (s["journal"], s["date_field"], s["scanned"], s["candidates"]))
    print("crossref candidates: %d (+%d recovered from overlap run)"
          % (len(prim["candidates"]), len(overlap_new)))
    if rss:
        print("rss: feeds=%d unreachable=%d in_window=%d keyword_pass=%d overlap=%d rss_only=%d"
              % (rss["feeds_total"], len(rss["unreachable_feeds"]), rss["items_in_window"],
                 rss["items_keyword_pass"], len(rss["overlap_with_crossref"]), len(rss["rss_only"])))
    print("new for digest: %d   already covered by earlier local digest: %d   without abstract: %d"
          % (len(new), len(covered), len(out["no_abstract_dois"])))
    print("written -> %s" % path)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
