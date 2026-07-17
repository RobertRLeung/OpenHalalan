"""
Merge the 2004-2019 source winners with the freshly scraped 2022 and 2025 winners into
data/output/NLE_Winners_2004-2025.csv.

Replaces the old archive/combine_datasets.py -> archive/merge_to_nle.py chain, which
depended on an intermediate NLE_Winners_2004_2025.csv that was never committed (so the
chain could not run from a fresh clone).

Provenance of each cycle in the output:
  2004-2019  <- data/source/political_dynasty_v8.5.csv, rows carried over unchanged
  2022       <- data/processed/winners_2022.csv (COMELEC re-scrape). This SUPERSEDES the
                source file's own 2022 rows (17,627 there vs 17,444 in the re-scrape).
  2025       <- data/processed/winners_2025.csv (COMELEC scrape, new cycle)

The source file's `Community` and `Position Weight` columns are dropped here: they are
analysis artefacts from a prior paper rather than election results, and they are not
comparable across cycles. See config.yaml for the details.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from config import (
    DROPPED_COLUMNS,
    OUTPUT,
    PROCESSED,
    SCRAPED_YEARS,
    SOURCE_WINNERS,
    WINNERS_CSV,
    WINNERS_COLUMNS,
    winners_csv,
)
from normalize import (
    backfill_region,
    canonical_full_name,
    canonical_party,
    clean_reported_name,
    drop_duplicate_rows,
    normalize_places,
    standardize_name,
)


def to_winners_schema(df, year):
    """
    Convert ballot-derived rows into the published winners schema.

    The name fields were already parsed by the vote-counts build - do NOT re-parse them
    here. `candidate_name` is by now the CLEANED name, so re-parsing would find no title
    or nickname and quietly drop both.
    """
    return pd.DataFrame(
        {
            "Last Name": df["last_name"].values,
            "First Name": df["first_name"].values,
            "Middle Name": df["middle_name"].values,
            "Title": df["title"].values,
            "Full Name": [
                canonical_full_name(l, f, m)
                for l, f, m in zip(df["last_name"], df["first_name"], df["middle_name"])
            ],
            "Position": df["position"].values,
            "Party": df["party"].values,
            "Year": year,
            "Province": df["province"].values,
            # City exists for the ballot-derived cycles because it comes off the ballots.
            # It is legitimately blank for province/district offices (a governor has no
            # city), which is why the column is ~93% filled rather than 100%.
            "City": df["city"].values,
            "Region": df["region"].values,
        }
    )[WINNERS_COLUMNS]


def canonicalise_inherited(df):
    """
    Bring the inherited cycles onto the same name schema.

    The source writes "FIRST MIDDLE SURNAME" while every ballot feed writes
    "SURNAME, FIRST MIDDLE", so joining the two on a name was a trap. Re-parse from the
    reported name, lifting out titles and nicknames, and rewrite Full Name in the one
    canonical form.
    """
    names = [
        standardize_name(n, p) for n, p in zip(df["Full Name"], df.get("Party"))
    ]
    df = df.copy()
    df["Last Name"] = [n[0] for n in names]
    df["First Name"] = [n[1] for n in names]
    df["Middle Name"] = [n[2] for n in names]
    df["Title"] = [n[3] for n in names]
    df["Full Name"] = [canonical_full_name(n[0], n[1], n[2]) for n in names]
    # The inherited cycles (2004-2013) predate any ballot-level source, so they carry no
    # city at all - the finest place they record is the province. City stays blank for them.
    df["City"] = pd.NA
    return df[WINNERS_COLUMNS]


# Records scraped with only an initial for a first name, corrected to the real given name
# after web verification (news / COMELEC). Keyed by the exact (Last Name, Province, scraped
# First Name); several also reunite the record with the person's fuller entries in other years.
# Ambiguous cases (Sagum "J": Jayson or Jerry?) and wrong-merge risks (Asistio "L.A.": would
# fuse two different Luises) are deliberately left alone.
NAME_FIXES = [
    # (Last Name, Province, scraped First) -> (real First, real Middle)
    ("AGLIPAY", "CAGAYAN", "1",        "EDGAR",    None),            # Gov. Edgar "Egay" Aglipay
    ("LANETE",  "MASBATE", "S",        "SCOTT",    "DAVIES"),        # Rep. Scott Davies Lanete
    ("UY",      "BOHOL",   "A.",       "ALVIN",    "JAYAG"),         # Mayor Alvin Jayag Uy (Baclayon)
    ("TERUEL",  "ILOILO",  "V",        "VIRGILIO", "TORRES"),        # Mayor Virgilio "Nene" Teruel
    ("TERUEL",  "ILOILO",  "NENE",     "VIRGILIO", "TORRES"),        #   (same person, nickname entry)
    ("RUANTO",  "QUEZON",  "L.A.",     "LORD",     "ARNEL FUENTE"),  # Lord Arnel Ruanto (Infanta)
    ("RUANTO",  "QUEZON",  "L.",       "LORD",     "ARNEL FUENTE"),
    ("JAVIER",  "ANTIQUE", "J.TOBIAS", "TOBIAS",   None),            # PBM Tobias "Tobing" Javier
    ("JAVIER",  "ANTIQUE", "J.",       "TOBIAS",   None),
    ("CLAVER",  "KALINGA", "G.",       "GKACHAY",  None),            # PBM Gkachay Claver
]


def apply_name_fixes(df):
    fixed = 0
    for last, prov, old_first, new_first, new_mid in NAME_FIXES:
        m = ((df["Last Name"].astype(str).str.upper() == last)
             & (df["Province"].astype(str).str.upper() == prov)
             & (df["First Name"].astype(str) == old_first))
        if m.any():
            df.loc[m, "First Name"] = new_first
            df.loc[m, "Middle Name"] = new_mid
            df.loc[m, "Full Name"] = last + ", " + new_first + ((" " + new_mid) if new_mid else "")
            fixed += int(m.sum())
    print(f"  applied {fixed} verified initial-name fixes")
    return df


def main():
    source = pd.read_csv(SOURCE_WINNERS, low_memory=False)
    print(f"Source winners file: {len(source):,} rows")

    inherited = source[~source["Year"].isin(SCRAPED_YEARS)]
    superseded = len(source) - len(inherited)
    print(f"  inherited 2004-2019: {len(inherited):,} rows "
          f"({superseded:,} rows superseded by re-scrape)")

    dropped = [c for c in DROPPED_COLUMNS if c in inherited.columns]
    if dropped:
        inherited = inherited.drop(columns=dropped)
        print(f"  dropped artefact columns: {', '.join(dropped)}")

    frames = [canonicalise_inherited(inherited)]
    for year in SCRAPED_YEARS:
        scraped = pd.read_csv(winners_csv(year))
        print(f"  + {year} COMELEC scrape: {len(scraped):,} rows")
        frames.append(to_winners_schema(scraped, year))

    merged = pd.concat(frames, ignore_index=True)
    merged = apply_name_fixes(merged)

    # --- clean up -----------------------------------------------------------
    print("\nnormalising:")
    before_provinces = merged["Province"].nunique()
    merged = normalize_places(merged, city="City")
    print(f"  provinces: {before_provinces} distinct -> "
          f"{merged['Province'].nunique()} after canonical naming")

    merged, filled, still_null = backfill_region(merged)
    print(f"  region: backfilled {filled:,} null rows from province "
          f"({still_null:,} still null)")

    before = merged["Party"].nunique()
    merged["Party"] = merged["Party"].map(canonical_party)
    print(f"  parties: {before} distinct -> {merged['Party'].nunique()} after canonical naming")

    merged = drop_duplicate_rows(merged, "winners")

    merged = merged.sort_values(["Year", "Province", "Position", "Last Name"])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    merged.to_csv(WINNERS_CSV, index=False)

    print(f"\nWrote {WINNERS_CSV.name}: {len(merged):,} rows, "
          f"{len(merged.columns)} columns")
    print(merged["Year"].value_counts().sort_index().to_string())
    return merged


if __name__ == "__main__":
    main()
