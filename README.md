# OpenHalalan: The Philippine National and Local Election Dataset Project

**OpenHalalan** is an open data initiative to make national and local election results in the Philippines freely accessible for researchers, journalists, policymakers, and the public.

## About the Project
This repository contains a curated, reproducible dataset of Philippine election results from national and local races. Our goal is to foster transparency, reproducibility, and wider participation in election research.

Everything rebuilds from the committed raw scrapes with one command, and a completeness audit ships alongside the data — including an honest account of what is missing. See [How to Cite](#how-to-cite).

## Dataset Contents

Two datasets, each independently usable and independently citable.

**1. Election Winners** — `data/output/NLE_Winners_2004-2025.csv`
One row per *winning* candidate per office, across eight cycles (2004, 2007, 2010, 2013,
2016, 2019, 2022, 2025). Covers the seven local and district offices: Governor, Vice
Governor, Provincial Board Member, Member of the House of Representatives, Mayor, Vice
Mayor, Councilor. **It contains no nationwide races** — no President, Vice President,
Senator or Party List.

**2. Vote Counts** — `data/output/NLE_Vote_Counts_2016-2025.csv.gz`
Every candidate's votes, winners and losers alike, as reported by COMELEC per city and
municipality. Two cycles only: **2022 and 2025**. These *do* include the nationwide races.

Full column definitions, coverage and known gaps:
[winners](data/output/DATA_DICTIONARY_WINNERS.md) · [vote counts](data/output/DATA_DICTIONARY_VOTE_COUNTS.md)

> **Status.** A completeness audit runs with `python data/audit/make.py` and writes
> `data/audit/issues.csv`. Four serious defects have been fixed in this build — winners
> were being selected alphabetically rather than by votes in 2022; the City of Manila was
> missing from 2022; Samar's 2025 results were Eastern Samar's, duplicated; and place names
> changed spelling between cycles. The remaining flagged issues are gaps inherited from the
> 2004–2019 source file. **The published Zenodo record predates these fixes.**

## How to Use
- Read the data dictionary for the dataset you need (linked above) — the known gaps matter.
- Download the CSVs from `data/processed/` (winners) or `data/raw_data/` (vote counts).
- Researchers and developers are welcome to use, analyze, or build upon the dataset.

## Reproducing the datasets

Everything is rebuilt from the committed raw COMELEC scrapes with one command:

```bash
pip install -r requirements.txt
python run_all.py
```

| | |
|---|---|
| `python run_all.py` | Rebuild both datasets from the raw scrapes, then audit. |
| `python run_all.py --audit-only` | Just re-run the completeness audit. |
| `python run_all.py --scrape` | Re-scrape COMELEC first. **Slow** (hours, drives a real browser). Not needed — the raw scrapes are committed. |

The pipeline lives in `data/make.py` (one entry point, three stages):

```
data/scraping   COMELEC websites -> data/raw_data/{2022,2025}/    [skipped by default]
data/compiling  raw scrapes + data/source/ -> data/output/
data/audit      both datasets -> data/audit/{issues,coverage_*}.csv
```

Run a single stage with `python data/make.py --stage compiling`.

All paths and settings live in [`config.yaml`](config.yaml); no script hardcodes a path.
Superseded and one-off scripts are kept in `archive/` and are not part of the pipeline.

## License
This project is licensed under the [Open Database License (ODbL) v1.0](LICENSE).

## How to Cite

Both datasets are released as **one citable bundle under a single DOI**. They are not
independent: the 2016, 2019, 2022 and 2025 winners are *derived* from the vote counts, so citing
the winners without the ballots that justify them would obscure their provenance.

> Leung, R., Alejandro, A., Acuna, R., Buot, J., Go, C., & Nable, J. (2026).
> *OpenHalalan: The Philippine National and Local Election Dataset* (Version 2.0)
> [Data set]. Zenodo. https://doi.org/10.5281/zenodo.21330133

```bibtex
@dataset{openhalalan2025,
  author    = {Leung, Robert and Alejandro, Aldie and Acuna, Rafael and
               Buot, Jude and Go, Clark and Nable, Job},
  title     = {OpenHalalan: The Philippine National and Local Election Dataset},
  year      = {2026},
  version   = {2.0},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.21330133},
  url       = {https://github.com/RobertRLeung/OpenHalalan}
}
```

Machine-readable metadata lives in [`CITATION.cff`](CITATION.cff). The DOI is a placeholder
until the Zenodo release is minted.

> **Superseding the old record.** The existing Zenodo DOI
> [10.5281/zenodo.17783100](https://doi.org/10.5281/zenodo.17783100) predates the audit and
> contains known defects — winners selected alphabetically rather than by votes in 2022, a
> missing City of Manila, and Samar's 2025 results duplicated from Eastern Samar. It should
> be superseded, not cited.

### Citing the research

If you are citing the *analysis* rather than the data, cite the paper:

> Acuna, R., Alejandro, A., & Leung, R. (2025). *The Families that Stay Together: A Network
> Analysis of Dynastic Power in Philippine Politics.* arXiv:2505.21280.
> https://arxiv.org/abs/2505.21280

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Contact
For questions, suggestions, or corrections, open an issue or contact the maintainer via GitHub.
