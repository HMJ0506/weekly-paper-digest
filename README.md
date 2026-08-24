# Weekly Paper Digest — discovery stage

Weekly scan of 16 high-impact journals for newly published papers on metal
batteries, anode-free cells, SEI / electrode–electrolyte interface engineering,
current-collector engineering, and MOF materials applied to those problems.

This repository holds only the **discovery** half: a scheduled job that queries
Crossref and commits `candidates.json`. A separate scheduled agent reads that
file and writes the report; its instructions live in that agent's own
configuration, not here.

## Why it is split

The agent that writes the report runs in a sandbox whose egress proxy blocks
`api.crossref.org` and `www.nature.com` outright — for curl, Python urllib and
tool-level fetches alike. It can reach GitHub. So discovery runs here, where
egress is open, and the writing agent reads the result over HTTPS.

| Stage | Where | When |
|---|---|---|
| Discovery | GitHub Actions (this repo) | Sun 23:10 UTC = Mon 08:10 KST |
| Writing + publishing | scheduled cloud agent | Mon 00:07 UTC = Mon 09:07 KST |

## Files

- `discover.py` — the discovery stage. Standard library only.
  `python discover.py --run-date 2026-08-19 --out candidates.json`
- `.github/workflows/weekly-discovery.yml` — the scheduled job
- `candidates.json` — latest output
- `data/candidates-YYYY-MM-DD.json` — dated snapshots

## Configuration

Both are repository secrets, both optional; discovery runs without either.

- `CROSSREF_MAILTO` — a contact address for [Crossref's polite pool](https://api.crossref.org).
  Without it, requests go to the slower shared pool.
- `SPRINGER_API_KEY` — free key from [dev.springernature.com](https://dev.springernature.com/)
  (5000 requests/day; this job uses a handful per week). Without it, abstracts
  for subscription Nature titles cannot be retrieved from CI at all — see below.

## The date-field trap

Crossref's `published-online` precision differs by publisher:

| Publisher | `published-online` | Filter used |
|---|---|---|
| Springer Nature, Wiley, ACS | day precision | `from-online-pub-date` |
| RSC (EES, Chem Soc Rev) | **year only** — `[[2026]]` | `from-created-date` |
| Elsevier (Joule), AAAS (Science) | **absent** | `from-created-date` |

Filtering the bottom four by online date returns **zero results, not an error**,
which reads as "no papers this week". `discover.py` therefore queries them by
Crossref registration date (day precision, tracks first publication within about
a day) and labels each candidate with which field it used, so the report never
presents a registration date as a verified online date.

The workflow asserts all 16 journals were reachable and warns if any of those
four scan zero records.

## Subscription Nature abstracts

Springer Nature deposits abstracts to Crossref only for its open-access titles
(Nature Communications). For the subscription titles — Nature, Nature Energy,
Nature Materials, Nature Chemistry, Nature Nanotechnology, Nature Synthesis,
Nature Reviews Materials — the abstract is not in Crossref, and Europe PMC and
OpenAlex have not indexed papers that recent.

`discover.py` resolves them in this order:

1. **Springer Nature metadata API**, if `SPRINGER_API_KEY` is set. Authenticated
   and allowed from CI. This is the route that actually works here.
2. **Scraping `dc.description` from nature.com.** Works from a residential IP,
   but CI IP ranges get a ~3 KB challenge page — HTTP 200, no exception, no meta
   tags. That silent failure once cost every subscription-Nature abstract in a
   run, so a response without the tag is now recorded as an explicit
   `enrich_error` and surfaced as a job warning.

Anything still without an abstract is reported with title, journal, date and DOI
only, and listed in `enrich_failures`.

## Filtering

The keyword filter is deliberately recall-first — it over-includes, and the
writing agent discards false positives using each abstract. A battery/
electrochemistry domain gate keeps out cross-domain homographs; without it,
"dendritic cell" pulled a melanoma immunotherapy paper into the metal-anode
topic.
