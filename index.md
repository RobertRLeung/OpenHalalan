# OpenHalalan: The Philippine Election Project

Open-access, reproducible Philippine national and local election data.

## The data

Two datasets, released together as **one citable bundle**.

**Election Winners, 2004–2025** — every winning candidate for the seven local and district
offices (governor, vice governor, provincial board member, member of the House of
Representatives, mayor, vice mayor, councilor), across eight election cycles.

**Vote Counts, 2016–2025** — every candidate's votes, winners *and losers*, for each city
and municipality. Includes the nationwide races (president, vice president, senator, party
list) and the BARMM parliament.

They are one bundle because they are not independent: the 2019, 2022 and 2025 winners are
**derived from the vote counts**. The 2004–2013 winners are inherited from an earlier
source and cannot be verified against ballots.

[Get the data on GitHub](https://github.com/RobertRLeung/OpenHalalan) — CSV, ready to
analyse — or [download the archived release](https://doi.org/10.5281/zenodo.17783099).
Explore it, and the map, at [openhalalan](https://robertrleung.github.io/OpenHalalan/).

## Reproducible, and honest about its gaps

Everything rebuilds from the committed raw scrapes with one command:

```bash
pip install -r requirements.txt
python run_all.py
```

A completeness audit ships with the data and writes every known gap to
`data/audit/issues.csv`. Building it surfaced real defects that had been sitting in the
published data, and the largest of them was invisible to a coverage check:

- **2022 was silently truncated.** The scraper read a rendered results table, so every long
  candidate list lost its tail. The presidential race carried 7 of its 10 candidates,
  omitting Leni Robredo, who finished second; the entire party-list race was missing; and
  because the same truncation hit long councilor lists, 57 councilor winners were wrong.
  Every one of the 1,634 files existed, each merely missing the same people. 2022 is now
  re-scraped from COMELEC's JSON API, which returns every ballot option.
- **The City of Manila was missing from 2022 altogether.** COMELEC models Manila as a
  province whose children are its districts, none of which is a canvass unit.
- 2019 governors were filed under the wrong province; Samar's 2025 results were duplicated
  from Eastern Samar.

All are fixed and documented. The gaps we *cannot* fix — there are no vote counts before
2016, and overseas votes are absent from every cycle but 2022 — are written down rather
than hidden.

Read the data dictionaries before using either dataset — the known gaps matter:
[winners](https://github.com/RobertRLeung/OpenHalalan/blob/main/data/output/DATA_DICTIONARY_WINNERS.md) ·
[vote counts](https://github.com/RobertRLeung/OpenHalalan/blob/main/data/output/DATA_DICTIONARY_VOTE_COUNTS.md)

## How to cite

Cite the **concept DOI**. It always resolves to the newest version, so a citation cannot go
stale — which matters here, because the previously cited record turned out to contain the
broken 2022 data for months.

> Leung, R., Alejandro, A., Acuna, R., Buot, J., Go, C., & Nable, J. (2026).
> *OpenHalalan: The Philippine National and Local Election Dataset*
> [Data set]. Zenodo. https://doi.org/10.5281/zenodo.17783099

If you need a fixed snapshot for exact reproducibility, take the version-specific DOI from
the record page and say which version you used.

If you are citing the analysis rather than the data:

> Acuna, R., Alejandro, A., & Leung, R. (2025). *The Families that Stay Together: A Network
> Analysis of Dynastic Power in Philippine Politics.* arXiv:2505.21280.

## License

[Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).

## Feedback

Spotted an error? [Open an issue](https://github.com/RobertRLeung/OpenHalalan/issues) or
send a pull request. Corrections are welcome — the biggest fixes in this dataset came from
exactly that kind of scrutiny.
