"""
Consolidate the per-municipality COMELEC scrapes into one published vote-counts dataset.

  data/raw_data/{2022,2025}/**/*.csv  ->  data/output/NLE_Vote_Counts_2022-2025.csv.gz

One row per candidate per office per locality: every candidate, winners and losers alike.
Place names are canonicalised so a locality keeps one key across cycles, and the office is
split out of COMELEC's location-laden `position` string.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import re

import pandas as pd

from config import OUTPUT, SCRAPED_YEARS, VOTE_COUNTS_CSV, raw_dir
from normalize import (
    NON_GEOGRAPHIC,
    canonical_city,
    canonical_province,
    canonical_region,
    drop_duplicate_rows,
)

# COMELEC embeds the locality in the office string, and the two cycles do it DIFFERENTLY:
#
#   2025: "MAYOR of ILOCOS NORTE - ADAMS"          <- office, then " of ", then the place
#         "SENATOR of PHILIPPINES"
#   2022: "MAYOR COTABATO - ALAMADA"               <- no separator at all
#         "PROVINCIAL GOVERNOR COTABATO"
#         "MEMBER, SANGGUNIANG BAYAN COTABATO - ALAMADA - LONE DIST"
#
# 2022 also uses the Filipino names for the local legislatures where 2025 uses the English
# ones. Both are mapped onto the same canonical office so the cycles are comparable.
#
# Ordered longest-prefix-first: "VICE-MAYOR" must be tested before "MAYOR", and
# "PROVINCIAL VICE-GOVERNOR" before "PROVINCIAL GOVERNOR".
OFFICE_PATTERNS = [
    ("MEMBER, HOUSE OF REPRESENTATIVES", "MEMBER, HOUSE OF REPRESENTATIVES"),
    ("MEMBER, SANGGUNIANG PANLALAWIGAN", "PROVINCIAL BOARD MEMBER"),
    ("PROVINCIAL BOARD MEMBER", "PROVINCIAL BOARD MEMBER"),
    ("MEMBER, SANGGUNIANG PANLUNGSOD", "COUNCILOR"),  # city council
    ("MEMBER, SANGGUNIANG BAYAN", "COUNCILOR"),  # municipal council
    ("COUNCILOR", "COUNCILOR"),
    ("PROVINCIAL VICE-GOVERNOR", "VICE GOVERNOR"),
    ("PROVINCIAL VICE GOVERNOR", "VICE GOVERNOR"),
    ("VICE-GOVERNOR", "VICE GOVERNOR"),
    ("VICE GOVERNOR", "VICE GOVERNOR"),
    ("PROVINCIAL GOVERNOR", "GOVERNOR"),
    ("GOVERNOR", "GOVERNOR"),
    ("VICE-MAYOR", "VICE MAYOR"),
    ("VICE MAYOR", "VICE MAYOR"),
    ("MAYOR", "MAYOR"),
    ("VICE-PRESIDENT", "VICE PRESIDENT"),
    ("VICE PRESIDENT", "VICE PRESIDENT"),
    ("PRESIDENT", "PRESIDENT"),
    ("SENATOR", "SENATOR"),
    ("PARTY LIST", "PARTY LIST"),
]

DISTRICT_RE = re.compile(r"([A-Z]+(?:\s+[A-Z]+)*\s+(?:LEGDIST|PROVDIST|DIST))\s*$")

# Races decided nationwide rather than by the locality reporting them. For these, `rank`
# is only the candidate's standing WITHIN that locality, not who won the seat.
NATIONAL_OFFICES = {"PRESIDENT", "VICE PRESIDENT", "SENATOR", "PARTY LIST"}


def split_position(position):
    """
    Return (canonical_office, district) from COMELEC's location-laden position string.

    Handles both cycles' formats. Unrecognised offices return (None, None) rather than
    leaking the raw string, so the audit can count them.
    """
    if pd.isna(position):
        return None, None

    text = re.sub(r"\s+", " ", str(position).strip().upper())

    office = None
    for prefix, canonical in OFFICE_PATTERNS:
        if text.startswith(prefix):
            office = canonical
            text = text[len(prefix):]
            break

    if office is None:
        return None, None

    # Whatever follows the office is the locality; the district, if any, trails it.
    remainder = re.sub(r"^\s*(OF\s+)?", "", text).strip()
    match = DISTRICT_RE.search(remainder)

    return office, match.group(1).strip() if match else None


def load_year(year):
    files = sorted(raw_dir(year).rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no raw scrapes under {raw_dir(year)}")

    frames = []
    for f in files:
        d = pd.read_csv(f)
        if not d.empty:
            frames.append(d)

    df = pd.concat(frames, ignore_index=True)
    df["year"] = year
    print(f"  {year}: {len(files):,} municipality files -> {len(df):,} rows")
    return df


def main():
    print("Loading raw COMELEC scrapes:")
    df = pd.concat([load_year(y) for y in SCRAPED_YEARS], ignore_index=True)

    print("\nnormalising:")
    offices = [split_position(p) for p in df["position"]]
    df["office"] = [o[0] for o in offices]
    df["district"] = [o[1] for o in offices]
    print(f"  offices parsed out of `position`: {df['office'].nunique()} distinct")

    df["region"] = df["region"].map(canonical_region)
    df["province"] = df["province"].map(canonical_province)
    df["city"] = df["city"].map(canonical_city)

    # LAV (Local Absentee Voting) is a real nationwide tally, not a place. Mark it so it
    # can be included in national totals and excluded from geographic aggregation.
    df["is_geographic"] = ~df["province"].isin(NON_GEOGRAPHIC)
    non_geo = (~df["is_geographic"]).sum()
    if non_geo:
        print(f"  flagged {non_geo:,} rows as non-geographic tallies "
              f"({', '.join(sorted(NON_GEOGRAPHIC & set(df['province'].dropna())))})")

    df["is_national_race"] = df["office"].isin(NATIONAL_OFFICES)

    # "1.54 %" -> 1.54
    df["percentage"] = pd.to_numeric(
        df["percentage"].astype(str).str.replace("%", "", regex=False).str.strip(),
        errors="coerce",
    )
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce")

    df = drop_duplicate_rows(df, "vote counts")

    columns = [
        "year", "region", "province", "city",
        "office", "district", "position",
        "candidate_name", "party",
        "votes", "percentage", "rank",
        "is_national_race", "is_geographic",
    ]
    df = df[columns].sort_values(["year", "region", "province", "city", "office", "rank"])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(VOTE_COUNTS_CSV, index=False)

    size_mb = VOTE_COUNTS_CSV.stat().st_size / 1e6
    print(f"\nWrote {VOTE_COUNTS_CSV.name}: {len(df):,} rows, {size_mb:.1f} MB")
    print(df.groupby("year").size().to_string())
    if size_mb > 50:
        print(f"\n  WARNING: {size_mb:.0f} MB exceeds GitHub's 50 MB file limit. "
              f"Host via Zenodo, or split by year / compress.")
    return df


if __name__ == "__main__":
    main()
