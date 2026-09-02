#!/usr/bin/env python3
"""
Weekly Paper Digest - RSS supplement (secondary source).

Reads publisher RSS feeds (a built-in verified list, optionally unioned with a
Feedly OPML export), extracts DOIs published inside the coverage window, applies
the SAME topic keyword filter as discover.py (imported, not copied), and reports
which keyword-passing DOIs Crossref discovery did NOT return ("rss_only").
Those are enriched from Crossref works/{doi} and OpenAlex.

It also collects Cell Press (Joule) in-press summaries so the merge step can
attach an abstract to Joule candidates, which Elsevier never deposits to Crossref.

Usage:
  python rss_supplement.py --run-date 2026-09-07 --candidates local_data/candidates-2026-09-07.json
                           [--opml feedly.opml] [--out local_data/rss-2026-09-07.json]
"""
import argparse, json, os, re, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import feedparser
import requests

import discover  # same directory: reuse clean(), JUNK_TITLE, BROWSER_UA, UA, MAILTO, authors_of()
import run_discover  # classify() with the same dash-normalization fix as the discovery run

# Verified 2026-09-03 from a residential IP with a browser User-Agent.
# ACS (JACS, ACS Energy Letters) -> HTTP 403; RSC (EES, Chem Soc Rev) -> 403 via
# login redirect. Both are deliberately absent: Crossref covers them fully.
DEFAULT_FEEDS = [
    ("Nature",                         "https://www.nature.com/nature.rss"),
    ("Nature Energy",                  "https://www.nature.com/nenergy.rss"),
    ("Nature Materials",               "https://www.nature.com/nmat.rss"),
    ("Nature Chemistry",               "https://www.nature.com/nchem.rss"),
    ("Nature Communications",          "https://www.nature.com/ncomms.rss"),
    ("Nature Reviews Materials",       "https://www.nature.com/natrevmats.rss"),
    ("Nature Nanotechnology",          "https://www.nature.com/nnano.rss"),
    ("Nature Synthesis",               "https://www.nature.com/natsynth.rss"),
    ("Science",                        "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"),
    ("Joule",                          "https://www.cell.com/joule/inpress.rss"),
    ("Advanced Materials",             "https://onlinelibrary.wiley.com/feed/15214095/most-recent"),
    ("Advanced Energy Materials",      "https://onlinelibrary.wiley.com/feed/16146840/most-recent"),
]
CELLPRESS_HOST = "cell.com"

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#&]+", re.I)
DOI_KEYS = ("prism_doi", "id", "link", "dc_identifier", "guid")


def _norm_doi(s):
    return s.lower().rstrip(".,;:)]}")


def extract_doi(entry):
    """prism:doi -> dc:identifier/id -> link/guid; then any string field."""
    for k in DOI_KEYS:
        v = entry.get(k)
        if isinstance(v, str):
            m = DOI_RE.search(v)
            if m:
                return _norm_doi(m.group(0))
    for v in entry.values():
        if isinstance(v, str):
            m = DOI_RE.search(v)
            if m:
                return _norm_doi(m.group(0))
    return None


def entry_date(entry):
    for k in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(k)
        if t:
            return "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
    return None


def entry_text(entry):
    parts = [entry.get("summary", "")]
    for c in entry.get("content", []) or []:
        parts.append(c.get("value", ""))
    return discover.clean(" ".join(p for p in parts if p))


def load_opml(path):
    """Return [(journal, xmlUrl)] from a Feedly OPML export."""
    feeds = []
    root = ET.parse(path).getroot()
    for o in root.iter("outline"):
        url = o.get("xmlUrl")
        if url:
            feeds.append((o.get("text") or o.get("title") or url, url.strip()))
    return feeds


def fetch_feed(url, timeout=20):
    r = requests.get(url, headers={"User-Agent": discover.BROWSER_UA,
                                   "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8"},
                     timeout=timeout, allow_redirects=True)
    return r.status_code, r.content, r.url


def crossref_work(doi):
    url = "https://api.crossref.org/works/%s" % requests.utils.quote(doi, safe="")
    if discover.MAILTO:
        url += "?mailto=%s" % discover.MAILTO
    try:
        return json.loads(discover.get(url, timeout=30, retries=2))["message"]
    except Exception as exc:              # noqa: BLE001
        return {"_error": "%s: %s" % (type(exc).__name__, exc)}


def openalex_abstract(doi):
    url = ("https://api.openalex.org/works/https://doi.org/%s"
           "?select=abstract_inverted_index" % doi)
    if discover.MAILTO:
        url += "&mailto=%s" % discover.MAILTO
    try:
        inv = json.loads(discover.get(url, timeout=30, retries=2)).get("abstract_inverted_index")
    except Exception:                     # noqa: BLE001
        return ""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return discover.clean(" ".join(pos[i] for i in sorted(pos)))


def s2_abstract(doi):
    """Semantic Scholar Graph API (no key). Often carries RSC abstracts that
    Crossref only has in truncated form."""
    url = ("https://api.semanticscholar.org/graph/v1/paper/DOI:%s?fields=abstract"
           % requests.utils.quote(doi, safe=""))
    try:
        j = json.loads(discover.get(url, timeout=30, retries=2))
    except Exception:                     # noqa: BLE001
        return ""
    return discover.clean(j.get("abstract") or "")


def enrich_rss_only(item):
    """Fill journal/authors/date/abstract for a DOI Crossref discovery missed."""
    msg = crossref_work(item["doi"])
    if "_error" in msg:
        item["enrich_error"] = "crossref works: " + msg["_error"]
    else:
        ct = msg.get("container-title") or []
        if ct:
            item["journal_crossref"] = ct[0]
        item["authors"] = discover.authors_of(msg) or item.get("authors", "")
        title = discover.clean((msg.get("title") or [""])[0])
        if title:
            item["title"] = title
        for key, kind in (("published-online", "published-online (Crossref)"),
                          ("created", "Crossref registration date (~online)")):
            parts = discover.date_parts(msg, key)
            if len(parts) >= 3:
                item["date_crossref"] = discover.fmt_date(parts)
                item["date_kind"] = kind
                break
        abstract = discover.clean(msg.get("abstract", ""))
        if abstract:
            item["abstract"], item["abstract_source"] = abstract, "crossref"
    if not item.get("abstract"):
        abstract = openalex_abstract(item["doi"])
        if abstract:
            item["abstract"], item["abstract_source"] = abstract, "openalex"
    if not item.get("abstract"):
        abstract = s2_abstract(item["doi"])
        if abstract:
            item["abstract"], item["abstract_source"] = abstract, "semantic scholar"
    if not item.get("abstract") and item.get("rss_summary"):
        item["abstract"], item["abstract_source"] = item["rss_summary"], "rss summary"
    return item


def run(run_date, window_start, window_end, opml=None, known_dois=(), verbose=True):
    feeds = list(DEFAULT_FEEDS)
    opml_feeds = []
    if opml and os.path.exists(opml):
        opml_feeds = load_opml(opml)
        seen = {u for _, u in feeds}
        for j, u in opml_feeds:
            if u not in seen:
                feeds.append((j, u))
                seen.add(u)
    known = {d.lower() for d in known_dois}

    feed_reports, rss_only, overlap, cellpress = [], [], [], {}
    n_total = n_window = n_pass = 0
    for journal, url in feeds:
        rep = {"journal": journal, "url": url, "http": None, "entries": 0,
               "in_window": 0, "keyword_pass": 0, "error": None}
        try:
            code, content, final = fetch_feed(url)
            rep["http"] = code
            if code != 200:
                rep["error"] = "HTTP %d (final url: %s)" % (code, final)
                feed_reports.append(rep)
                if verbose:
                    print("%-30s HTTP %s  UNREACHABLE" % (journal[:30], code))
                continue
            parsed = feedparser.parse(content)
        except Exception as exc:          # noqa: BLE001
            rep["error"] = "%s: %s" % (type(exc).__name__, exc)
            feed_reports.append(rep)
            if verbose:
                print("%-30s ERROR %s" % (journal[:30], rep["error"]))
            continue

        entries = parsed.entries or []
        rep["entries"] = len(entries)
        n_total += len(entries)
        for e in entries:
            doi = extract_doi(e)
            if not doi:
                continue
            title = discover.clean(e.get("title", ""))
            text = entry_text(e)
            if CELLPRESS_HOST in url and text:
                cellpress[doi] = text
            date = entry_date(e)
            in_window = (date is None) or (window_start <= date <= window_end)
            if not in_window:
                continue
            rep["in_window"] += 1
            n_window += 1
            if not title or discover.JUNK_TITLE.match(title):
                continue
            topics = run_discover.classify(title, text)
            if not topics:
                continue
            rep["keyword_pass"] += 1
            n_pass += 1
            if doi in known:
                overlap.append(doi)
                continue
            rss_only.append({
                "doi": doi, "title": title, "journal": journal,
                "authors": "", "date": date or "", "feed_date": date or "",
                "date_unknown": date is None,
                "date_kind": "RSS feed date", "url": "https://doi.org/" + doi,
                "abstract": "", "abstract_source": "", "rss_summary": text,
                "topics": topics, "source": "rss", "feed_url": url,
            })
        feed_reports.append(rep)
        if verbose:
            print("%-30s HTTP 200  entries=%3d  in_window=%3d  keyword_pass=%2d"
                  % (journal[:30], rep["entries"], rep["in_window"], rep["keyword_pass"]))
        time.sleep(0.3)

    if rss_only and verbose:
        print("-" * 78)
        print("Enriching %d RSS-only DOIs from Crossref/OpenAlex ..." % len(rss_only))
    # Feed dates are unreliable (Wiley "most-recent" stamps items with the feed
    # build date, Cell Press re-lists in-press items). The Crossref date is the
    # authority on in-window membership, exactly as in discover.py; an item is a
    # genuine miss only if Crossref itself places it inside the window.
    genuine, out_of_window, unverified = [], [], []
    for item in rss_only:
        enrich_rss_only(item)
        time.sleep(0.3)
        cd = item.get("date_crossref")
        if cd is None:
            item["date_verified"] = False
            unverified.append(item)
        elif window_start <= cd <= window_end:
            item["date"], item["date_verified"] = cd, True
            genuine.append(item)
        else:
            item["date"], item["date_verified"] = cd, True
            out_of_window.append(item)
    rss_only = genuine + unverified

    return {
        "run_date": run_date, "window_start": window_start, "window_end": window_end,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "opml_used": bool(opml_feeds), "opml_feeds": len(opml_feeds),
        "feeds_total": len(feeds),
        "feeds": feed_reports,
        "unreachable_feeds": [r for r in feed_reports if r["error"]],
        "items_total": n_total, "items_in_window": n_window,
        "items_keyword_pass": n_pass,
        "overlap_with_crossref": sorted(set(overlap)),
        "rss_only": rss_only,
        "rss_only_unverified_date": [i["doi"] for i in unverified],
        "rss_out_of_window": [{"doi": i["doi"], "title": i["title"], "journal": i["journal"],
                               "feed_date": entry_date_str(i), "crossref_date": i["date"]}
                              for i in out_of_window],
        "cellpress_summaries": cellpress,
    }


def entry_date_str(item):
    return item.get("feed_date") or ""


def window_for(run_date_str):
    run = datetime.strptime(run_date_str, "%Y-%m-%d").date()
    return (run - timedelta(days=8)).isoformat(), (run - timedelta(days=1)).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", help="YYYY-MM-DD (KST). Default: today in KST.")
    ap.add_argument("--window-start")
    ap.add_argument("--window-end")
    ap.add_argument("--opml", default="feedly.opml")
    ap.add_argument("--candidates", nargs="*", default=[],
                    help="candidates*.json files whose DOIs count as already found")
    ap.add_argument("--out")
    args = ap.parse_args()

    run_date = args.run_date or (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()
    ws, we = window_for(run_date)
    ws, we = args.window_start or ws, args.window_end or we

    known = set()
    for p in args.candidates:
        with open(p, encoding="utf-8") as fh:
            known.update(c["doi"].lower() for c in json.load(fh).get("candidates", []))

    print("RUN_DATE : %s   WINDOW: %s .. %s   known Crossref DOIs: %d" % (run_date, ws, we, len(known)))
    print("=" * 78)
    out = run(run_date, ws, we, opml=args.opml, known_dois=known)
    print("=" * 78)
    print("feeds=%d unreachable=%d  entries=%d in_window(feed date)=%d keyword_pass=%d  "
          "overlap=%d rss_only=%d (date unverified %d)  out_of_window_per_crossref=%d  "
          "cellpress_summaries=%d"
          % (out["feeds_total"], len(out["unreachable_feeds"]), out["items_total"],
             out["items_in_window"], out["items_keyword_pass"],
             len(out["overlap_with_crossref"]), len(out["rss_only"]),
             len(out["rss_only_unverified_date"]), len(out["rss_out_of_window"]),
             len(out["cellpress_summaries"])))
    for it in out["rss_only"]:
        print("  RSS-ONLY [%s%s] %-28s %s  abstract=%s" % (
            it["date"] or "????-??-??", "" if it.get("date_verified") else " unverified",
            it["journal"][:28], it["doi"], it["abstract_source"] or "NO"))
        print("      %s" % it["title"][:110])
    for it in out["rss_out_of_window"]:
        print("  out-of-window (feed %s, Crossref %s) %-26s %s" % (
            it["feed_date"], it["crossref_date"], it["journal"][:26], it["doi"]))

    path = args.out or "local_data/rss-%s.json" % run_date
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("written -> %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
