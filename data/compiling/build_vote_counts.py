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

from config import OUTPUT, VOTE_COUNT_YEARS, VOTE_COUNTS_CSV, raw_dir
from normalize import (
    NON_GEOGRAPHIC,
    canonical_city,
    canonical_full_name,
    canonical_party,
    canonical_region,
    clean_reported_name,
    drop_duplicate_rows,
    resolve_province,
    standardize_name,
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
    # BARMM's regional parliament, elected for the first time in 2025. A real office, and
    # one the winners dataset does not carry (that covers the 7 national/local offices
    # only). Its districts use a REGDIST suffix.
    ("BARMM MEMBERS OF THE PARLIAMENT", "BARMM MEMBER OF PARLIAMENT"),
    # ARMM's regional government, elected until 2016. BARMM replaced ARMM in 2019, and its
    # parliament (above) is the successor to the Regional Legislative Assembly. Kept
    # distinct rather than merged: they are different institutions under different laws.
    ("REGIONAL VICE-GOVERNOR", "ARMM REGIONAL VICE GOVERNOR"),
    ("REGIONAL VICE GOVERNOR", "ARMM REGIONAL VICE GOVERNOR"),
    ("REGIONAL GOVERNOR", "ARMM REGIONAL GOVERNOR"),
    ("ASSEMBLYMAN", "ARMM ASSEMBLYMAN"),
    ("BARMM PARTY REPRESENTATIVES", "BARMM PARTY REPRESENTATIVE"),
    ("MEMBER, HOUSE OF REPRESENTATIVES", "MEMBER, HOUSE OF REPRESENTATIVES"),
    # ABS-CBN 2019 calls the office "Congressman". A handful of its contests omit the
    # detailed string entirely, so the scraper falls back to this bare position name -
    # those rows carry no district.
    ("CONGRESSMAN", "MEMBER, HOUSE OF REPRESENTATIVES"),
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

# The district identifier, with the redundant suffix stripped.
#
# COMELEC writes "FIRST LEGDIST" / "THIRD PROVDIST" / "LONE DIST", but the suffix only
# restates the office (LEGDIST <-> house member, PROVDIST <-> provincial board, DIST <->
# councilor), so it carries no information. What matters is the identifier itself: it names
# the jurisdiction the votes are counted in.
#
# Usually an ordinal (LONE, FIRST, SECOND, ...) but NOT always: some councils have named
# districts (BABAK, KAPUTIAN and SAMAL in the Island Garden City of Samal; BACON in
# Sorsogon; EAST and WEST). Keep whatever the identifier is.
DISTRICT_RE = re.compile(r"([A-Z]+(?:\s+[A-Z]+)*?)\s+(?:LEGDIST|PROVDIST|REGDIST|DIST)\s*$")

# Races decided nationwide rather than by the locality reporting them. For these, `rank`
# is only the candidate's standing WITHIN that locality, not who won the seat.
NATIONAL_OFFICES = {"PRESIDENT", "VICE PRESIDENT", "SENATOR", "PARTY LIST"}


def split_position(position):
    """
    Return (canonical position, district) from a source's location-laden position string.

    The canonical position uses the SAME vocabulary as the winners dataset's `Position`
    column, so the two datasets are directly joinable.

    Handles every source's format. Unrecognised offices return (None, None) rather than
    leaking the raw string, so the audit can count them.
    """
    if pd.isna(position):
        return None, None

    text = re.sub(r"\s+", " ", str(position).strip().upper())

    position_name = None
    for prefix, canonical in OFFICE_PATTERNS:
        if text.startswith(prefix):
            position_name = canonical
            text = text[len(prefix):]
            break

    if position_name is None:
        return None, None

    # Whatever follows the office is the locality; the district, if any, trails it.
    remainder = re.sub(r"^\s*(OF\s+)?", "", text).strip()
    match = DISTRICT_RE.search(remainder)

    return position_name, match.group(1).strip() if match else None


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
    print("Loading raw scrapes:")
    df = pd.concat([load_year(y) for y in VOTE_COUNT_YEARS], ignore_index=True)

    print("\nnormalising:")
    # Keep the source's raw string for traceability, but `position` becomes the canonical
    # office - the same vocabulary the winners dataset uses.
    df["raw_position"] = df["position"]
    parsed = [split_position(p) for p in df["position"]]
    df["position"] = [p[0] for p in parsed]
    df["district"] = [p[1] for p in parsed]

    # An unrecognised office must never ship as a null: that is how BARMM's parliament
    # (a real, 1,155-row office) sat silently discarded in an earlier build.
    unparsed = df[df["position"].isna()]
    if not unparsed.empty:
        names = sorted(unparsed["raw_position"].dropna().unique())
        raise SystemExit(
            f"\n{len(unparsed):,} rows have an office this script does not recognise:\n"
            + "\n".join(f"  {n!r}" for n in names[:20])
            + "\n\nAdd it to OFFICE_PATTERNS rather than letting it through as null."
        )
    print(f"  positions canonicalised: {df['position'].nunique()} distinct, none unparsed")
    print(f"  districts: {df['district'].nunique()} distinct "
          f"({df['district'].notna().sum():,} rows carry one)")

    df["region"] = df["region"].map(canonical_region)
    # resolve_province, not canonical_province: the 2019 feed says only "METRO MANILA",
    # so the NCR district has to be recovered from the city.
    df["province"] = [resolve_province(p, c) for p, c in zip(df["province"], df["city"])]
    df["city"] = df["city"].map(canonical_city)

    # LAV (Local Absentee Voting) is a real nationwide tally, not a place. Mark it so it
    # can be included in national totals and excluded from geographic aggregation.
    df["is_geographic"] = ~df["province"].isin(NON_GEOGRAPHIC)
    non_geo = (~df["is_geographic"]).sum()
    if non_geo:
        print(f"  flagged {non_geo:,} rows as non-geographic tallies "
              f"({', '.join(sorted(NON_GEOGRAPHIC & set(df['province'].dropna())))})")

    df["is_national_race"] = df["position"].isin(NATIONAL_OFFICES)

    # --- names -------------------------------------------------------------
    # Sources glue the party onto the name ("CRUZ, RODEL (LP)"), and COMELEC truncates at
    # 30 characters, which severs the closing bracket and leaves the party column empty
    # ("SANTANDER-DELOS REYES,LOVE(PFP"). Recover the party from the fragment, strip it
    # from the name, and lift out titles and nicknames - the same canonical name fields
    # the winners dataset carries, so the two are joinable.
    parsed = [standardize_name(n, p)
              for n, p in zip(df["candidate_name"], df["party"])]
    recovered = [clean_reported_name(n, p)[1]
                 for n, p in zip(df["candidate_name"], df["party"])]

    df["reported_name"] = df["candidate_name"]
    df["last_name"] = [x[0] for x in parsed]
    df["first_name"] = [x[1] for x in parsed]
    df["middle_name"] = [x[2] for x in parsed]
    df["title"] = [x[3] for x in parsed]
    df["candidate_name"] = [canonical_full_name(x[0], x[1], x[2]) for x in parsed]

    n_recovered = sum(1 for r in recovered if r)
    df["party"] = [r or p for r, p in zip(recovered, df["party"])]
    if n_recovered:
        print(f"  recovered {n_recovered:,} parties from truncated names")

    # --- parties -----------------------------------------------------------
    # The same party is spelled several ways across cycles, which makes it look like it
    # vanished and a candidate look like they switched. Real MERGERS are left alone -
    # see PARTY_ALIASES.
    df["reported_party"] = df["party"]
    before = df["party"].nunique()
    df["party"] = df["party"].map(canonical_party)
    print(f"  parties canonicalised: {before} -> {df['party'].nunique()} distinct")
    print(f"  names canonicalised; {df['title'].astype(bool).sum():,} titles lifted out")

    # "1.54 %" -> 1.54
    df["percentage"] = pd.to_numeric(
        df["percentage"].astype(str).str.replace("%", "", regex=False).str.strip(),
        errors="coerce",
    )
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce")

    df = drop_duplicate_rows(df, "vote counts")

    columns = [
        "year", "region", "province", "city", "district",
        "position",
        "candidate_name", "last_name", "first_name", "middle_name",
        "title", "party",
        "votes", "percentage", "rank",
        "is_national_race", "is_geographic",
        "raw_position", "reported_name", "reported_party",
    ]
    df = df[columns].sort_values(
        ["year", "region", "province", "city", "position", "votes"],
        ascending=[True, True, True, True, True, False],
    )

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
