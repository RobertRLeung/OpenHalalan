# Data Dictionary — `NLE_Vote_Counts_2019-2025.csv.gz`

Every candidate's votes, **winners and losers alike**, per city and municipality.
**1,019,758 rows, 14 columns.** Gzipped (7.8 MB; 82 MB uncompressed — above
GitHub's 50 MB file limit, hence the compression). `pandas.read_csv` opens it directly.

Built from the per-municipality scrapes in `data/raw_data/`, which remain in the repo as
the raw record. Rebuild with `python run_all.py`.

---

## Coverage

**Temporal. Three cycles: 2019, 2022 and 2025.** There are no vote counts for 2004–2016, so
those winners cannot be checked against ballots. Extending coverage back to 2010 is tracked
in issue #3.

| Cycle | Rows | Municipality files | Source |
|---|---|---|---|
| 13 May 2019 | 389,092 | 1,634 | ABS-CBN Halalan |
| 9 May 2022 | 205,240 | 1,634 | COMELEC |
| 12 May 2025 | 425,426 | 1,638 | COMELEC |

All three land on **1,634 Philippine cities and municipalities** (2025 adds the new BARMM
Special Geographic Area municipalities), which is an independent check that none is missing
localities.

**This dataset is now multi-source.** 2019 comes from ABS-CBN, 2022 and 2025 from COMELEC.
No cycle is covered by more than one source, so there are no cross-source conflicts to
reconcile — but that changes the moment a second source is added for the same cycle.

2025 has roughly double the rows on the same number of localities because more candidates
contested the nationwide races.

**Geographic.** 1,407 distinct localities — every city and municipality COMELEC published.

**Offices.** Thirteen. Unlike the winners dataset, this **includes the nationwide races**
(`PRESIDENT`, `VICE PRESIDENT`, `SENATOR`, `PARTY LIST`), each repeated in every
municipality's file because national races are tallied locally.

---

## Columns

| Column | Type | Description |
|---|---|---|
| `year` | int | 2022 or 2025. |
| `region` | string | Canonical region. |
| `province` | string | Canonical province or NCR district. |
| `city` | string | Canonical city / municipality. The tally unit. |
| `position` | string | One of 13 canonical offices, using **the same vocabulary as the winners dataset's `Position`**, so the two are directly joinable. |
| `district` | string | The jurisdiction the seat is counted in: `LONE`, `FIRST`, `SECOND`, … and the named ones (`BABAK`, `KAPUTIAN`, `SAMAL`, `BACON`, `EAST`, `WEST`). Null for at-large seats. |
| `raw_position` | string | The source's raw position string, kept verbatim for traceability. |
| `candidate_name` | string | `SURNAME, FIRST MIDDLE` as reported. Middle names often absent. |
| `party` | string | Party as reported. `IND` = independent. |
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

Three scraper defects were found and fixed; the affected areas were re-scraped.

1. **The City of Manila was missing from 2022.** COMELEC presents Manila as a district with
   no city dropdown (it *is* the NCR 1st district) and the scraper treated that as a
   failure. Re-scraped.
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
