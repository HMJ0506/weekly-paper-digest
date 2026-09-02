---
name: weekly-digest
description: Run the local Weekly Paper Digest — Crossref discovery + RSS supplement, precision filtering, summaries, and publish to the Notion page "Weekly Paper Digest (Local)". Usage: /weekly-digest [YYYY-MM-DD]
disable-model-invocation: true
---

# /weekly-digest — local weekly paper digest

Argument: optional run date `YYYY-MM-DD` (KST). Default = today (KST). Coverage window = run_date−8 … run_date−1 (inclusive), plus a 2-day overlap run to recover late-indexed papers.

**Working directory:** every command below runs from the repo root, `C:\dev\weekly-paper-digest` (same path on every PC). If this skill was invoked from somewhere else (it is also exposed globally via a junction in `~/.claude/skills/`), `cd` there first and run `git pull --ff-only` so `seen_dois.json` and the scripts are current.

## Settings (shared across PCs - this repo is the single source of truth)

- **Notion parent page for local digests:** `Weekly Paper Digest (Local)` - page id `3cfe998e-0380-81bf-82ad-d53f6c6bdb5d`. Create weekly pages under it with `notion-create-pages` (parent type `page_id`).
- **Never write to** the cloud routine's page `Weekly Paper Digest` (id `342e998e-0380-802d-9c8b-ecaae70db509`).
- **Environment variables (set per PC at User scope, never stored in files):** `CROSSREF_MAILTO` (Crossref polite pool), `SPRINGER_API_KEY` (Springer Nature metadata API for subscription-Nature abstracts; nature.com serves a bot challenge even to residential IPs). PowerShell: `[Environment]::SetEnvironmentVariable("SPRINGER_API_KEY","<key>","User")`, then restart the terminal/Claude Code.
- **Python:** 3.10+, `pip install feedparser requests` (discover.py itself is stdlib-only).
- **Files:** `discover.py` (discovery stage, shared with the GitHub Actions job) / `run_discover.py` (shim) / `rss_supplement.py` / `build_digest_input.py` / `record_published.py` / `digests/seen_dois.json` (tracked - commit and push after every publish so other PCs dedupe correctly) / `local_data/` and `digests/*.md` (git-ignored run outputs).
- **Optional:** `feedly.opml` (export from https://feedly.com/i/opml, git-ignored) adds the user's own feeds to the built-in RSS list.
- After publishing: `git add digests/seen_dois.json && git commit -m "digest <D>" && git push`.

## Step A — discovery + RSS + dedupe (deterministic, scripted)

```
python build_digest_input.py --run-date <D>
```
- Runs `discover.py` twice (D and D−2, through the `run_discover.py` dash-normalization shim), the RSS supplement, abstract fallbacks (OpenAlex; Cell Press summary for Joule), and dedupe against `digests/seen_dois.json`.
- Before running, check `CROSSREF_MAILTO` / `SPRINGER_API_KEY` are set in the environment (`echo $env:SPRINGER_API_KEY` in PowerShell). If `SPRINGER_API_KEY` is missing, say so in Search Notes — subscription-Nature abstracts then depend on OpenAlex.
- Output: `local_data/digest_input-<D>.json`. Read it in full before writing anything.
- Exit code 1 = a journal was unreachable or a journal count is wrong. Report the console output and **stop** — do not publish a digest from a partial scan.
- Warnings (zero-scan for EES/ChemSocRev/Joule/Science, truncation, enrichment failures) do not stop the run but must be reported verbatim in Search Notes.
- If `already_covered` is non-empty those DOIs are excluded automatically; list them in the Deduplication section.

## Step B — precision filtering and summaries (model)

> **Placeholder rules, reverse-engineered from the cloud digest of 2026-08-24.** When the user supplies the cloud routine's prompt, replace this section with it verbatim.

Input candidates are recall-first keyword matches. For every candidate decide **retain / discard** using the abstract (or the title alone when no abstract exists), then assign exactly one primary topic; note secondary topics as cross-references.

Topics (fixed order and headings):
1. `## 1. Metal Batteries` — metal anodes (Li/Na/K/Zn/Mg/Ca/Al), dendrites, plating/stripping, CE, metal-air/flow cells where the anode reversibility is the contribution.
2. `## 2. Anode-Free Batteries` — anode-free / anodeless / zero-excess cells.
3. `## 3. SEI & Electrode–Electrolyte Interface` — SEI/CEI composition, artificial interphases, electrolyte design targeting the interface (Li-ion, Na-ion, Si, hard-carbon cathode CEI studies are retained here when the interphase is the core subject).
4. `## 4. Current Collector Engineering` — current collectors, lithiophilic/sodiophilic/zincophilic hosts, 3D hosts, nucleation seeds.
5. `## 5. MOF for Energy Storage` — MOF/ZIF/coordination polymer applied to batteries or interfaces with the framework retained. COF and Prussian-blue analogues are excluded by policy (report under Search Notes if flagged).

Discard as false positive (list each under Search Notes with a one-line reason): electrocatalysis (ORR/OER/HER/CO₂RR/NRR), fuel cells, electrochemical capture/extraction, non-battery devices, cathode-only or separator-only work with no interphase/anode contribution, MOF used outside energy storage, papers whose only match is a homograph.

**Ordering and focus marker.** The user's research focus is Li metal and anode-free Li cells. Within every topic section, order entries: (a) Li-metal / anode-free-Li / Li interphase papers first, each title prefixed with `⭐ `; (b) then Na; (c) then other chemistries (Zn, K, Mg, Ca, Al, Sn, Li-ion, general reviews), each group by online date. Do not change retain/discard decisions because of the marker — it only orders and flags. State in the Summary how many ⭐ papers the week has, e.g. `⭐ Li focus: 7 of 22`.

Entry format (one per retained paper, no bullets):
```
**<Title>**
<First author> et al. · <Journal> · Online <YYYY-MM-DD>[ (Crossref registration date ≈ online)][ (RSS feed date)] · DOI [<doi>](https://doi.org/<doi>)
<3–6 sentence summary: problem → approach → key quantitative results (CE, cycle life, current density, capacity, retention, voltage, energy density) → significance.>[ *(Also relevant to Topic n — <name>.)*][ *Relevance: <why retained despite scope edge>.*]
```
- Date label: `published-online (Crossref)` → plain `Online`; `Crossref registration date (~online)` → append `(Crossref registration date ≈ online)`; RSS-only items → append `(RSS feed date)` and prefix the entry with `[RSS-only — not indexed by Crossref discovery]`.
- No abstract (`abstract` empty): write `⚠️ Access-restricted — DOI only.` + one line `*Focus (from title): …*`. Never invent findings.
- Abstract source notes: `abstract_source == "cellpress rss summary"` → append `*(Summary from Cell Press RSS.)*`; RSC abstracts that are truncated → say so and give no numbers beyond the deposited text.
- Numbers only from the abstract. No hype adjectives.

Topic section with nothing retained: `No new papers found this week in the target journals.` If retained papers cross-reference into the topic, list them as `- *(See Topic n)* **Title** ([doi](https://doi.org/doi)) — one-line reason.`

## Step C — page layout

Title: `Weekly Paper Digest (Local) — <D>`. Parent: page id from `CLAUDE.local.md` (**Weekly Paper Digest (Local)**, never the cloud page). Icon 📄.

Body, in order:
```
Auto-generated weekly paper digest (target high-IF journals only) — LOCAL RUN. Topics: Metal Batteries · Anode-Free · SEI/Interface · Current Collector Engineering · MOF for Energy Storage.
**Target journals:** Nature · Nature Energy · Nature Materials · Nature Chemistry · Nature Communications · Nature Reviews Materials · Nature Nanotechnology · Nature Synthesis · Science · Joule · Energy & Environmental Science · JACS · Chemical Society Reviews · Advanced Materials · Advanced Energy Materials · ACS Energy Letters
**Coverage period:** <window_start> – <window_end> (overlap run from <overlap_window_start>)
**Generated:** <D> (local run: Crossref ×2 + RSS supplement, <feeds_total> feeds, <unreachable_feeds> unreachable)
---
## Summary
<records scanned, candidates, retained, discarded, already covered; per-topic counts; ⭐ Li-focus count; journals with zero candidates; RSS supplement result (in-window, keyword-pass, overlap with Crossref, RSS-only count); Joule summaries attached; recovered-from-overlap count.>
---
## 1. … ## 5. (as above)
---
## Search Notes
- Candidates discarded as false positives (n of m), with reasons
- Journals with 0 in-window candidates
- Per-journal scan counts (scanned → candidates → retained)
- Unreachable / truncated / enrichment failures (verbatim from digest_input)
- RSS supplement: feeds unreachable (ACS, RSC expected), RSS-only items and how they were enriched
- Access-restricted (DOI-only) items
- Date-precision caveat (online vs registration date; RSS feed date for RSS-only items)
- COF / PBA note
- Indexing caveat (mitigated by the overlap run; state what the overlap run recovered)
- Discovery mode: local Crossref REST ×2 + RSS supplement; discover.py commit from `git rev-parse --short HEAD`
---
## Deduplication
<Which sources were checked: digests/seen_dois.json and the two most recent sub-pages of "Weekly Paper Digest (Local)" (fetch them). List excluded DOIs with the digest they appeared in. The cloud page "Weekly Paper Digest" is NOT consulted — the two pipelines are kept independent for cross-validation.>
---
*Generated by the local /weekly-digest skill.*
> ⚠️ **Disclaimer:** Online dates come from Crossref (`published-online` where day-precision, else registration date ≈ online) or, for RSS-only items, from the feed. Verify against primary sources. Entries without a retrievable abstract are listed DOI-only. No dates, DOIs, authors, or findings were fabricated.
```

## Step D — review, publish, record

1. Show the user the Summary block and the retain/discard decisions (title · journal · decision · reason) and wait for confirmation. Apply any changes.
2. Create the Notion page with `notion-create-pages` under the parent page id. Fetch it back once to confirm it rendered.
3. Save the same markdown to `digests/weekly_digest_<D>.md` (UTF-8).
4. `python record_published.py --input local_data/digest_input-<D>.json` — records every candidate (retained and discarded) in `seen_dois.json`; then commit and push `digests/seen_dois.json`.
5. Report: Notion URL, counts, warnings, and anything left unresolved (e.g. RSS-only items the user should double-check).
