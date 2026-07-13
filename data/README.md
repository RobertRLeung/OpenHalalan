# OpenHalalan — data

Two datasets, each independently usable and independently citable.

| Dataset | File | What | Coverage |
|---|---|---|---|
| **Election Winners** | `output/NLE_Winners_2004-2025.csv` | One row per winning candidate per office | 8 cycles, 2004–2025, local + district offices |
| **Vote Counts** | `output/NLE_Vote_Counts_2022-2025.csv.gz` | Every candidate's votes per municipality, winners and losers | 2 cycles, 2022 & 2025, incl. nationwide races |

Read the dictionary before using either — both document real gaps:

- [`output/DATA_DICTIONARY_WINNERS.md`](output/DATA_DICTIONARY_WINNERS.md)
- [`output/DATA_DICTIONARY_VOTE_COUNTS.md`](output/DATA_DICTIONARY_VOTE_COUNTS.md)

> ⚠ **`rank` in the vote counts is an ALPHABETICAL index, not a vote standing.** Never pick
> a winner with it — sort by `votes`. An earlier build made exactly this mistake and
> selected the alphabetically-first candidate in every 2022 race.

## Layout

```
data/
  raw_data/     COMELEC scrapes, one CSV per municipality (the raw record)
    2022/  2025/
    2025_position_cleaned/   orphaned; not read by the pipeline
  source/       upstream 2004-2022 winners inherited from the dynasty paper
  processed/    intermediates (per-cycle winners) - not the published artefacts
  output/       THE TWO PUBLISHED DATASETS + their dictionaries
  scraping/     COMELEC scrapers
  compiling/    raw -> published datasets
  audit/        completeness checks + outputs
  make.py       the single pipeline entry point
```

Data flows one way: `scraping -> raw_data -> compiling -> processed -> output -> audit`.

## Rebuilding

From the repository root:

```bash
pip install -r requirements.txt
python run_all.py
```

The raw scrapes are committed, so this rebuilds both datasets **without** re-scraping
COMELEC. See the root `README.md` for the full pipeline and the audit.

To add data, see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
