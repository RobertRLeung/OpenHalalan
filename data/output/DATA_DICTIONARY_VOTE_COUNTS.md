# Data Dictionary — `NLE_Vote_Counts_2010-2025.csv.gz`

Every candidate's votes, **winners and losers alike**, per city and municipality.
**1,840,430 rows, 20 columns.** Gzipped (the uncompressed CSV is well above GitHub's 50 MB
file limit, hence the compression). `pandas.read_csv` opens it directly.

Built from the per-municipality scrapes in `data/raw_data/`, which remain in the repo as
the raw record. Rebuild with `python run_all.py`.

---

## Coverage

**Temporal. Six cycles: 2010, 2013, 2016, 2019, 2022 and 2025.** 2010 and 2013 are partial
cycles (see below); before 2010 there are no vote counts, so 2001–2007 winners still cannot
be checked against ballots.

| Cycle | Rows | Municipality files | Source |
|---|---|---|---|
| 10 May 2010 | 119,929 | ~1,519 | Ianmaps Election Bank † |
| 13 May 2013 | 38,878 | ~1,433 | Rappler (archived) |
| 9 May 2016 | 361,947 | 1,633 | GMA Eleksyon |
| 13 May 2019 | 389,092 | 1,634 | ABS-CBN Halalan |
| 9 May 2022 | 504,814 | 1,634 | COMELEC |
| 12 May 2025 | 425,770 | 1,638 | COMELEC |

> † The 2010 municipal results were shared from the **Ianmaps Election Bank**, compiled by
> **Ian ([@ian_maps](https://twitter.com/ian_maps))** and **Joseph Ricafort
> ([@josephricafort](https://twitter.com/josephricafort))**. With thanks.

The 2016–2025 cycles each land on **1,634 Philippine cities and municipalities** (2025 adds
the new BARMM Special Geographic Area municipalities), which is an independent check that
none is missing localities. 2010 and 2013 are exceptions, described next.

**2010 is a national-races-only cycle.** The source carries the presidential,
vice-presidential and senatorial vote per city/municipality — and **no local offices** (no
governor, mayor, House or council). Coverage is **~1,519 of 1,634 municipalities (93%)**.
The source lists no party, so 2010's `party` is blank; percentage and rank are computed
here (share of the locality's votes for that office; rank by votes within the locality).
The national totals check out against the known result — Aquino wins the presidency, Binay
edges Roxas for vice president, Revilla tops the Senate.

**2013 is a partial cycle, reconstructed from Rappler's archived results.** Rappler's 2013
live-results site is gone; the Internet Archive preserved ~88% of its municipality pages,
which is what this cycle is rebuilt from (`data/scraping/scrape_2013_rappler.py`). Read it
with these limits in mind:

- **Municipal races** (mayor, vice-mayor, councilor) cover **~1,433 of 1,634 municipalities
  (88%)** — every candidate, winners and losers, with votes. The rest were not archived.
- **Governor, vice-governor and House** are recorded only as a **province (or district)
  total**, not broken down per municipality — Rappler published them that way. On the map,
  2013 governor therefore colours the province directly rather than being summed from towns.
- **Senator** is a single **national total** (33 candidates), with no per-locality breakdown,
  so it is present in the data but does not appear on the map.
- **No president, vice president or party list**: 2013 was a midterm, so those seats were
  not contested.
- Rappler published no percentage or rank, so both are **computed here** (share of the race
  total; rank by votes within the race).

Because 2013's races are not all per-locality and its coverage is 88%, do not treat its
totals as complete the way the 2016–2025 cycles are.

**This dataset is multi-source.** 2010 comes from the Ianmaps Election Bank, 2013 from
Rappler, 2016 from GMA, 2019 from ABS-CBN, 2022 and 2025 from COMELEC. **No cycle is covered
by more than one source**, so there are no cross-source conflicts to reconcile — but that
changes the moment a second source is added for a cycle that already has one.

2016 also carries the **ARMM regional government** (`ARMM REGIONAL GOVERNOR`,
`ARMM REGIONAL VICE GOVERNOR`, `ARMM ASSEMBLYMAN`), abolished when BARMM replaced ARMM in
2019. These are kept distinct from BARMM's parliament rather than merged: they are
different institutions under different laws.

**Known gap: Maconacon, Isabela has no 2016 results.** GMA serves no file for it under any
spelling. 1,633 of the country's 1,634 localities are present.

2025 has roughly double the rows on the same number of localities because more candidates
contested the nationwide races.

**Geographic.** Every city and municipality COMELEC published: 1,634 in each of 2019 and
2022, 1,633 in 2016 (Maconacon has no file), 1,637 in 2025 (the new BARMM Special
Geographic Area municipalities).

**2022 also carries overseas votes** (`region = OAV`), which no other cycle does. They are
flagged `is_geographic = False`, exactly like `LAV`, and are excluded from any per-locality
aggregation. Do not add them to a national total unless you mean to.

**Offices.** Sixteen. Unlike the winners dataset, this **includes the nationwide races**
(`PRESIDENT`, `VICE PRESIDENT`, `SENATOR`, `PARTY LIST`), each repeated in every
municipality's file because national races are tallied locally.

---

## Columns

| Column | Type | Description |
|---|---|---|
| `year` | int | Election year: 2010, 2013, 2016, 2019, 2022 or 2025. |
| `region` | string | Canonical region. |
| `province` | string | Canonical province or NCR district. |
| `city` | string | Canonical city / municipality. The tally unit. |
| `position` | string | One of 16 canonical offices, using **the same vocabulary as the winners dataset's `Position`**, so the two are directly joinable. |
| `district` | string | The jurisdiction the seat is counted in: `LONE`, `FIRST`, `SECOND`, … and the named ones (`BABAK`, `KAPUTIAN`, `SAMAL`, `BACON`, `EAST`, `WEST`). Null for at-large seats. |
| `raw_position` | string | The source's raw position string, kept verbatim for traceability. |
| `candidate_name` | string | `SURNAME, FIRST MIDDLE` as reported. Middle names often absent. |
| `party` | string | Canonical party code, unified across cycles. `IND` = independent. Coalitions name each member, separated by `/`. Real mergers are not collapsed — see the winners dictionary. |
| `reported_party` | string | The source's raw party string, kept verbatim for traceability. |
| `votes` | int | **Votes for this candidate in this locality.** The unit of the dataset. |
| `percentage` | float | Share of the locality's votes for that office. Numeric (COMELEC's raw `"1.54 %"` string is parsed). |
| `rank` | int | **COMELEC's alphabetical index — NOT a vote standing.** See the warning below. |
| `is_national_race` | bool | True for President / Vice President / Senator / Party List. |
| `is_geographic` | bool | False for non-geographic tally categories (see LAV below). |

### ⚠ `rank` does not mean what it looks like

**`rank` is an alphabetical index, not a vote rank.** In Manila 2022 the mayoral candidates
are ranked 1–6 as ABAD, BAGATSING, JAMIAS, LACUNA, LIM, LOPEZ — alphabetical. The actual
winner, LACUNA (538,595 votes, 63.68%), is rank **4**; rank 1 took 2,618 votes.

An earlier build of the winners dataset sorted on this column and so selected the
alphabetically-first candidate in every 2022 race. **Never determine a winner from `rank`.
Sort by `votes`.**

Even sorted by votes, rank 1 identifies the winner only for **locally-decided** races. For
`SENATOR` and `PARTY LIST` (`is_national_race = True`), the top row is merely who led *that
municipality*.

### `position` vs `office`

COMELEC embeds the locality in the office string, and **the two cycles do it differently**:

```
2025:  "MAYOR of ILOCOS NORTE - ADAMS"          office, " of ", place
       "SENATOR of PHILIPPINES"
2022:  "MAYOR COTABATO - ALAMADA"               no separator
       "PROVINCIAL GOVERNOR COTABATO"
       "MEMBER, SANGGUNIANG BAYAN COTABATO - ALAMADA - LONE DIST"
```

2022 also uses the Filipino names for the local legislatures where 2025 uses English
(`MEMBER, SANGGUNIANG PANLALAWIGAN` = `PROVINCIAL BOARD MEMBER`; `SANGGUNIANG BAYAN` /
`PANLUNGSOD` = `COUNCILOR`; `PROVINCIAL VICE-GOVERNOR` = `VICE GOVERNOR`). Both are mapped
onto the same canonical `office` so the cycles are comparable. `position` is retained
verbatim: it is the only place a district is recorded, and it is the audit trail back to
the raw file.

**Units.** `votes` is a count of ballots in one locality for one candidate for one office.
To get a candidate's provincial or national total, sum across localities — nothing here is
pre-aggregated.

---

## LAV — Local Absentee Voting

`LAV` appears as a region, province *and* city. **It is real data, not junk.** LAV is
COMELEC's Local Absentee Voting tally: government employees, media, military and police who
vote away from their home precinct. It is a region-level entry in COMELEC's own dropdown.

It holds 221 rows and ~555,000 votes, and contains **only** `SENATOR` and `PARTY LIST` —
exactly as the law requires, since absentee voters may vote for national offices only.

It is flagged `is_geographic = False`. **Include it in national vote totals; exclude it from
any geographic aggregation**, or it becomes a phantom province.

---

## Provenance

Scraped from COMELEC's official results sites:

- 2022 — `https://2022electionresults.comelec.gov.ph`
- 2025 — `https://2025electionresults.comelec.gov.ph`

Scrapers: `data/scraping/`. Both drive a real browser (COMELEC blocks headless) and skip
municipalities already on disk, so runs are resumable and can be targeted at one place with
`--region` / `--province`. **The scraped output is committed, so replication does not
require re-scraping.**

**Single source.** These are COMELEC figures only — no GMA, Rappler or other media tallies.
There are therefore no cross-source disagreements to reconcile and no source-precedence rule.

---

## Corrections applied

Scraper defects found and fixed; the affected areas were re-scraped.

1. **2022 was silently truncated, and it was the worst defect in the project's history.**
   The old scraper drove a browser and read the rendered results table, so it captured only
   the rows the page had bothered to render. Every long candidate list lost its tail. The
   presidential race shipped with 7 of its 10 candidates — the first seven alphabetically,
   dropping MONTEMAYOR, PACQUIAO and **ROBREDO, who finished second with ~15M votes** — and
   the entire party-list race was absent. This was invisible to a coverage audit: all 1,634
   files existed, each simply missing the same people.

   It was not only a national problem. The same truncation hit long **councilor** lists, so
   57 councilor winners in the published dataset were flat wrong. 2022 has been re-scraped
   from COMELEC's JSON API, which returns every ballot option and cannot truncate. Rows went
   from 205,240 to 504,814.

2. **The City of Manila was missing from 2022.** COMELEC's API models Manila as a PROVINCE
   (`NCR - MANILA`) whose fourteen children (Tondo, Binondo, Ermita...) are its districts.
   None of the fourteen is a canvass unit; Manila's single board hangs off the province node
   itself. A walk that reads boards only off city nodes therefore returns fourteen empty
   districts and no Manila. Fixed by treating a province as a locality when it has a board
   and none of its children do — a rule that deliberately does NOT catch `TAGUIG - PATEROS`,
   which also has a province-level board but whose two cities have their own, and which
   would otherwise have been counted twice.
2. **Samar's 2025 data was Eastern Samar's, duplicated.** Dropdown options were matched by
   substring, so `SAMAR` selected `EASTERN SAMAR` (listed first) — the real Samar province
   was absent and Eastern Samar appeared twice. Matching is now exact-first; all 26 Samar
   municipalities re-scraped.
3. **Long dropdowns were truncated.** The 2025 scraper read only the rendered items of a
   lazy-loading list, losing the tail of long lists (Samar returned 20 of 26). It now
   scrolls until the list stops growing.

Also applied: canonical region / province / city names, so a locality keeps one key across
cycles (`CITY OF BAGUIO`, `BAGUIO CITY` → `BAGUIO`; diacritics folded, so
`ALFONSO CASTAÑEDA` → `ALFONSO CASTANEDA`).

---

## Known gaps

Regenerated by `python data/audit/make.py` into `data/audit/issues.csv`.

1. **Five municipalities have no 2025 results at all**: Balindong, Lumba Bayabao and Madamba
   (Lanao del Sur), Tongkil (Sulu), Datu Salibo (Maguindanao). COMELEC lists them in the
   dropdown but publishes an **empty results page** — consistent with the 2025 election
   failures and postponements in BARMM. The data does not exist upstream; this is not a
   scrape defect.

2. **Localities differ legitimately between cycles.** Renames (`BALIUAG` → `BALIWAG`,
   `BACUNGAN` → `LEON T POSTIGO`, `PIO V CORPUZ` → `PIO V CORPUS`), municipality-to-city
   conversions, and the **8 new municipalities** created in BARMM's Special Geographic Area
   in 2024 (Kadayangan, Kapalawan, Ligawasan, Malidegao, Nabalawag, Old Kaabakan,
   Pahamuddin, Tugunan). Join across cycles on a stable locality code (PSGC) rather than the
   name where you can.

3. **Boundary changes.** Maguindanao appears undivided in 2022 and split in 2025 (the
   plebiscite followed the May 2022 election). Sulu left BARMM in 2024 and appears under
   Region IX in 2025. The Negros Island Region was created in 2024.

4. **`ISLAND GARDEN CITY OF SAMAL` and `SCIENCE CITY OF MUNOZ`** keep "CITY" in their names —
   those are their genuine official names, and they are consistent across both cycles.

---

## License

**ODbL v1.0** (repository `LICENSE`), share-alike.

This dataset is already published on Zenodo under DOI
[10.5281/zenodo.17783100](https://doi.org/10.5281/zenodo.17783100). **That record predates
this audit** and therefore contains the Manila and Samar defects described above. A new
version should be minted from this build.

## Citation

See the repository `README.md`. A `CITATION.cff` will be added with the Zenodo release.
