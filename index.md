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

[Get the data on GitHub](https://github.com/RobertRLeung/OpenHalalan) — CSV, ready to analyse.

## Reproducible, and honest about its gaps

Everything rebuilds from the committed raw scrapes with one command:

```bash
pip install -r requirements.txt
python run_all.py
```

A completeness audit ships with the data and writes every known gap to
`data/audit/issues.csv`. Building it surfaced real defects that had been sitting in the
published data — winners selected alphabetically rather than by votes in 2022, the City of
Manila missing entirely from that cycle, Samar's 2025 results duplicated from Eastern
Samar, and 2019 governors filed under the wrong province. All are fixed and documented; the
gaps we *cannot* fix are written down rather than hidden.

Read the data dictionaries before using either dataset — the known gaps matter:
[winners](https://github.com/RobertRLeung/OpenHalalan/blob/main/data/output/DATA_DICTIONARY_WINNERS.md) ·
[vote counts](https://github.com/RobertRLeung/OpenHalalan/blob/main/data/output/DATA_DICTIONARY_VOTE_COUNTS.md)

## How to cite

> Leung, R., Alejandro, A., Acuna, R., Buot, J., Go, C., & Nable, J. (2025).
> *OpenHalalan: The Philippine National and Local Election Dataset* (Version 2.0)
> [Data set]. Zenodo. https://doi.org/10.5281/zenodo.XXXXXXX

If you are citing the analysis rather than the data:

> Acuna, R., Alejandro, A., & Leung, R. (2025). *The Families that Stay Together: A Network
> Analysis of Dynastic Power in Philippine Politics.* arXiv:2505.21280.

## License

[Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).

## Feedback

Spotted an error? [Open an issue](https://github.com/RobertRLeung/OpenHalalan/issues) or
send a pull request. Corrections are welcome — this session's biggest fixes came from
exactly that kind of scrutiny.
