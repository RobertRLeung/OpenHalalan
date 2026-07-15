# Data Dictionary — `NLE_Winners_2004-2025.csv`

One row per **winning** candidate per office per election cycle. **139,517 rows, 9 columns.**

Rebuild with `python run_all.py`. Audit with `python data/audit/make.py`.

---

## Coverage

**Temporal.** Eight cycles, every Philippine local election from 2004 to 2025.

| 2004 | 2007 | 2010 | 2013 | 2016 | 2019 | 2022 | 2025 |
|---|---|---|---|---|---|---|---|
| 17,368 | 16,608 | 17,502 | 17,161 | 17,577 | 17,796 | 17,732 | 17,773 |

**Geographic.** 88 `Province` values (82 provinces, 4 NCR districts, plus the provinces
created by the Maguindanao split) across 18 regions. No nulls.

**Offices.** Seven, and only these seven:

| Office | Level | Elected by |
|---|---|---|
| `GOVERNOR` | provincial | province |
| `VICE GOVERNOR` | provincial | province |
| `PROVINCIAL BOARD MEMBER` | provincial | provincial district |
| `MEMBER, HOUSE OF REPRESENTATIVES` | district | legislative district |
| `MAYOR` | municipal | city / municipality |
| `VICE MAYOR` | municipal | city / municipality |
| `COUNCILOR` | municipal | city / municipality (by council district where one exists) |

**No nationwide races.** No President, Vice President, Senator or Party List rows. Those
live in `NLE_Vote_Counts_2016-2025.csv.gz`.

---

## Columns

| Column | Type | Description |
|---|---|---|
| `Last Name` | string | Surname, upper case. |
| `First Name` | string | Given name, upper case. |
| `Middle Name` | string | Middle name. Often empty — the ballot feeds rarely report one. |
| `Title` | string | Honorific, where the source gave one: `ATTY.`, `DOC`, `DR.`, `ENGR.`, and the Moro honorifics `DATU`, `BAI`, `HADJI`. Usually empty. |
| `Full Name` | string | **Canonical `SURNAME, FIRST MIDDLE` in every cycle.** Joins directly against `candidate_name` in the vote-counts dataset. |
| `Position` | string | One of the seven offices above. |
| `Party` | string | Canonical party code. Spellings of the same party are unified across cycles; real mergers are **not** — see below. |
| `Year` | int | Election year. |
| `Province` | string | Canonical province or NCR district. Stable across cycles. |
| `City` | string | Canonical city / municipality, matching `city` in the vote-counts dataset. Present only for the **municipal** offices (mayor, vice mayor, councilor) and only from **2016** on: the office has to be municipal to have a city, and the city has to come off a ballot the project scraped. Blank for provincial and district offices (a governor has no city), and blank for every 2004–2013 row, which predates any ballot-level source. About 47% filled overall. |
| `Region` | string | Canonical region. Never null. |

No vote totals here — this records *who won*. For votes, use the vote-counts dataset.

### Columns deliberately removed

Earlier versions carried `Community` and `Position Weight`. Both were **analysis artefacts
from a prior paper, not election results**, and both were silently inconsistent across
cycles: `Community` held a numeric graph id for 2004–2019 but the *city name* for
2022/2025, and `Position Weight` used an inverted scale in the scraped years that made
mayors and councilors weigh the same. Dropping them merged no distinct people — the
duplicate rows are byte-identical with or without them.

Anything derived from network structure belongs in the analysis codebase, computed *from*
this data, not shipped inside it.

---

## Provenance

| Cycles | Source |
|---|---|
| **2016, 2019, 2022, 2025** | **Derived from the ballots** in `NLE_Vote_Counts_2016-2025.csv.gz`: votes are summed within the jurisdiction that elects each seat, and the top candidate(s) win. Fully reproducible and independently checkable. |
| 2004–2013 | `data/source/political_dynasty_v8.5.csv`, inherited from the dynasty paper. Its own upstream provenance is undocumented, and it **cannot be verified** — no vote counts exist for those cycles. |

**2019 was rebuilt from ballots because the inherited version was demonstrably wrong.**
See *Corrections* below.

**Verification.** Every ballot-derived cycle is checked by asking whether each winner's
surname appears on their province's ballots at all:

| Cycle | Winners absent from their province's ballots |
|---|---|
| 2019 | 0.0% |
| 2022 | 0.0% |
| 2025 | 0.0% |
| 2004–2016 | *unverifiable — no ballots* |

---

## Corrections applied

Several defects were found and fixed while building this release. Anyone comparing against
an earlier version of the winners file should read this section.

0. **2019 was rebuilt from ballots — the inherited version was wrong.** Real governors were
   filed under the **wrong province**: Arthur Yap (Bohol) appeared under Laguna, Reynaldo
   Tamayo Jr. (South Cotabato) under Cotabato, Edwin Ongchuan (Northern Samar) under Samar,
   Francisco "Pacoy" Ortega (La Union) under Southern Leyte. 8.3% of inherited 2019 winners
   had a surname appearing nowhere on their province's ballots, and only **11** House of
   Representatives rows survived against 221 real contests. All are now derived from the
   ballots, and the figure is 0.0%.

1. **Winners were being selected alphabetically, not by votes (2022).** COMELEC's `rank`
   column is an *alphabetical* index, not a vote standing. The 2022 builder sorted on it
   and took the top row, so it returned the alphabetically-first candidate in every race.
   The 2022 mayor of Manila came out as `ABAD, ONOFRE` (2,618 votes, rank 1) instead of
   `LACUNA, HONEY` (538,595 votes, rank 4). **Every 2022 winner was affected.** Winners are
   now chosen by highest votes.

2. **Names were a mess, and are now canonical.** Three separate defects:
   - The **party was glued into the name** — `CRUZ, RODEL (LP)` — across all 17,759 of
     2016's winners and 175,305 vote-count rows, and 15,342 rows had `Middle Name` set to
     the party (`(LP)`, `(NPC)`…) rather than a name.
   - **Honorifics were being read as given names**: `ATTY. BEL` was recorded with the first
     name `ATTY.`. 1,137 winners were affected. Titles now live in their own `Title` field.
   - The two eras used **opposite name orders** — `ANICETO MANZANO ABAOAG` in the inherited
     cycles versus `ABAOAG, ANICETO` in the ballot cycles — so joining the datasets on a
     name silently failed.

   `Full Name` is now canonical `SURNAME, FIRST MIDDLE` in **every** cycle, and **100% of
   ballot-cycle winners now join to the vote counts on it** (it was 13%). A parenthesised
   nickname that is not the party (`RUEL (TATA) YAP`) is stripped from the name.

   Along the way this recovered **13 parties that were null**: COMELEC truncates names at
   30 characters, which severs the closing bracket and drops the party
   (`SANTANDER-DELOS REYES,LOVE(PFP`). The party is taken from the fragment.

3. **Provincial board members were ranked province-wide, but they are elected BY DISTRICT.**
   The old builder summed each candidate's votes across the whole province and took the top
   N, which systematically favours candidates from populous districts over genuine winners
   in small ones. They are now ranked within their own provincial district.

2. **The City of Manila was missing from 2022 entirely.** COMELEC presents Manila as a
   district with no city dropdown (it *is* the 1st district), and the scraper treated the
   absent dropdown as a failure and skipped it. Manila has been re-scraped.

3. **Samar's 2025 results were Eastern Samar's, duplicated.** The scraper matched dropdown
   options by substring, so asking for `SAMAR` selected `EASTERN SAMAR` (listed first). All
   26 Samar municipalities have been re-scraped. Option matching is now exact-first.

4. **Long dropdowns were silently truncated.** The 2025 scraper read only the rendered
   items of a lazy-loading list, so provinces with many municipalities lost the tail
   (Samar returned 20 of 26). It now scrolls until the list stops growing.

Also cleaned: **canonical place names** (Metro Manila alone appeared under three spellings
split by era, which shattered NCR into three unrelated panels; `COMPOSTELA VALLEY` →
`DAVAO DE ORO`; ARMM → `BARMM`); **`Region` backfilled** for 2019, which arrived 100% null
and was recovered from each row's province; and **728 exact duplicate rows removed.**

---

## Known gaps

Regenerated by `python data/audit/make.py` into `data/audit/issues.csv`. **These are gaps
in the underlying data, not loading errors.**

### Open — inherited from the 2004–2019 source file

These cannot be diagnosed or fixed from anything in this repository. They all predate the
COMELEC scrapes.

1. **2019 has almost no House of Representatives rows** — 11, against a median of 240. The
   2019 rows are otherwise complete (it is the *largest* cycle); it is specifically the
   congressional results that are missing.

2. **Missing localities in several inherited cycles.** Some cycles return fewer officials
   than there are seats: 2010 has 70 governors and 2016 has 74, against 82 provinces; 2007
   is ~8% short on mayors and vice mayors.

### Open — real-world data absences

3. **Five municipalities have no 2025 COMELEC results at all**: Balindong, Lumba Bayabao and
   Madamba (Lanao del Sur), Tongkil (Sulu), and Datu Salibo (Maguindanao). COMELEC lists
   them but publishes an empty results page — consistent with the 2025 election
   failures and postponements in BARMM. Not a scraper defect; the data does not exist.

### Documented limitations

4. **Seat counts are the weakest assumption in the pipeline.** Five of the seven offices
   are unambiguous — mayor, vice mayor, governor, vice governor and House member are all a
   single seat, so the ballots decide them outright with no assumption at all. The other two
   need a seat count that **the ballots do not carry**:

   - **Councilor** — a flat default of 8 per council district. Correct for the ordinary
     municipal council (Sangguniang Bayan), but 26 of 1,631 LGUs elect their councils by
     district with varying sizes (the City of Manila returns 6 per district, not 8).
   - **Provincial board member** — the per-province total is taken from the inherited source
     file and split evenly across the province's districts. Seats are really apportioned by
     population and are *not* uniform across a province's districts.

   A seats-per-district reference table would remove both assumptions. Until then, these two
   offices are the only place a ballot-derived winner can still be wrong.

5. **`Middle Name` is mostly empty for 2022 and 2025** (85% and 83%): COMELEC reports names
   as `SURNAME, FIRST`. Earlier cycles carry it far more often. Any surname- or
   name-matching across the 2019→2022 boundary is therefore working with systematically
   *less* information in the recent cycles — a real bias risk for kinship inference. **Use
   `Full Name` as the key.**

6. **`Party` is canonicalised, but party lineages are deliberately NOT merged.**

   Spellings of the same party are unified (`PDP LABAN` → `PDPLBN`, `NACIONALISTA PARTY` →
   `NP`, `LAKAS CMD` → `LAKAS-CMD`), as are punctuation-only variants of coalition labels
   (`KAMPI-UNA` → `KAMPI/UNA`). That took the winners dataset from 445 labels to 397.

   **Mergers between parties are real institutional events, not spelling noise, and are
   left intact.** Four distinct entities exist in the Lakas family alone:

   | Code | What it is | Cycles |
   |---|---|---|
   | `LAKAS` | Lakas ng Tao, on its own | 2013, 2019–2025 |
   | `LAKAS-CMD` | Lakas–Christian Muslim Democrats — itself a merger of Lakas and the CMD, and **not** the same party as plain `LAKAS` | 2004–2010, 2016 |
   | `KAMPI` | a distinct party | 2004–2010 |
   | `LKS-KAM` | Lakas–Kampi–CMD: the 2009 merger of Lakas-CMD and KAMPI. Exists **only** in 2010, after which KAMPI never appears again | 2010 |

   Collapsing these would erase the mergers and make party-switching analysis wrong in both
   directions — inventing switches that never happened and hiding ones that did. If your
   analysis wants a single "Lakas lineage", build that mapping yourself, as a stated
   research choice.

7. **Coalition labels name several parties**, separated by `/` (`LAKAS-CMD/NPC`,
   `KAMPI/BALANE`). These are joint endorsements, not a party — 2,041 rows (1.5%), all in
   2004–2013. A candidate endorsed by two parties has not switched party.

8. **The long tail is real.** 90.5% of rows sit in the top 20 labels; the remaining ~380 are
   genuine local and regional parties, not noise, and are left as reported.

7. **Boundary changes** (correct, not errors): **Maguindanao** split into del Norte and del
   Sur *after* the May 2022 election, so 2004–2022 correctly show one undivided province and
   2025 two — deliberately **not** merged. **Sulu** left BARMM in 2024. The **Negros Island
   Region** was created in 2024, so some provinces legitimately change region between 2022
   and 2025. **Dinagat Islands** has no provincial officials in 2004 (not yet a province).
   The BARMM **Special Geographic Area** and its 8 new municipalities appear only in 2025.

---

## License

**ODbL v1.0** (repository `LICENSE`), share-alike. Do not relicense without confirming you
have the right to relicense COMELEC-derived data.

## Citation

See the repository `README.md`. A `CITATION.cff` will be added with the Zenodo release.
