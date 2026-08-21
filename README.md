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

`CROSSREF_MAILTO` (repository secret, optional) — a contact address for
[Crossref's polite pool](https://api.crossref.org). Discovery works without it,
just on the slower shared pool.

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

## Known gap: subscription Nature abstracts

Springer Nature deposits abstracts to Crossref only for its open-access titles
(Nature Communications). For the subscription titles the abstract exists only on
nature.com, which answers CI IP ranges with a challenge page regardless of
User-Agent, and is unreachable from the writing sandbox. Europe PMC and OpenAlex
have not indexed papers that recent. Those candidates are reported with title,
journal, date and DOI only, and are listed in `enrich_failures`.

## Filtering

The keyword filter is deliberately recall-first — it over-includes, and the
writing agent discards false positives using each abstract. A battery/
electrochemistry domain gate keeps out cross-domain homographs; without it,
"dendritic cell" pulled a melanoma immunotherapy paper into the metal-anode
topic.
