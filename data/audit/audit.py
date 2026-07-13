"""
Completeness audit for both OpenHalalan datasets.

Writes to data/audit/:
  coverage_winners.csv      province x year x office-level coverage of the winners dataset
  coverage_votecounts.csv   province x year municipality coverage of the raw COMELEC scrapes
  issues.csv                every gap and inconsistency found, machine-readable

Run: python data/audit/audit.py   (or via data/audit/make.py)

This script only reports. It never modifies the datasets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import re
import unicodedata

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compiling"))

from config import (
    AUDIT,
    POSITIONS,
    SCRAPED_YEARS,
    VOTE_COUNTS_CSV,
    VOTE_COUNT_YEARS,
    WINNERS_CSV,
    YEARS,
    raw_dir,
)
from normalize import NON_GEOGRAPHIC

LEVEL = {
    "GOVERNOR": "provincial",
    "VICE GOVERNOR": "provincial",
    "PROVINCIAL BOARD MEMBER": "provincial",
    "MEMBER, HOUSE OF REPRESENTATIVES": "district",
    "MAYOR": "municipal",
    "VICE MAYOR": "municipal",
    "COUNCILOR": "municipal",
}

# Every office a province should return in a normal cycle. A province with no rows at a
# level in a given year is a genuine gap, except where the province did not yet exist.
EXPECTED_LEVELS = ["provincial", "district", "municipal"]

# Ground truth for the Philippines. One office is returned per LGU per cycle, so a count
# far from these means either missing localities or duplicated rows.
EXPECTED_COUNTS = {
    "GOVERNOR": 82,  # 82 provinces
    "VICE GOVERNOR": 82,
    "MAYOR": 1634,  # 1,634 cities + municipalities
    "VICE MAYOR": 1634,
}
COUNT_TOLERANCE = 0.05  # counts within +/-5% of truth are not flagged

issues = []


def flag(dataset, severity, kind, scope, detail):
    issues.append(
        {
            "dataset": dataset,
            "severity": severity,
            "issue": kind,
            "scope": scope,
            "detail": detail,
        }
    )


def audit_winners():
    df = pd.read_csv(WINNERS_CSV, low_memory=False)
    df["level"] = df["Position"].map(LEVEL)

    print("=" * 78)
    print("ELECTION WINNERS")
    print("=" * 78)
    print(f"rows: {len(df):,}   columns: {list(df.columns)}")
    print(f"\nrows per cycle:\n{df['Year'].value_counts().sort_index().to_string()}")

    # --- unmapped positions -------------------------------------------------
    unknown = sorted(set(df.loc[df["level"].isna(), "Position"].dropna()))
    for pos in unknown:
        flag("winners", "high", "unrecognised position", pos,
             "position is not one of the 7 expected offices")

    # --- coverage matrix: province x year x level ---------------------------
    counts = (
        df.groupby(["Province", "Year", "level"]).size().unstack("level", fill_value=0)
    )
    for lvl in EXPECTED_LEVELS:
        if lvl not in counts.columns:
            counts[lvl] = 0
    coverage = counts[EXPECTED_LEVELS].reset_index()
    coverage.to_csv(AUDIT / "coverage_winners.csv", index=False)

    # --- null columns -------------------------------------------------------
    print("\nnull values by cycle:")
    for col in df.columns:
        nulls = df[df[col].isna()]["Year"].value_counts().sort_index()
        if nulls.empty:
            continue
        print(f"  {col:14} {nulls.to_dict()}")
        for year, n in nulls.items():
            total = (df["Year"] == year).sum()
            if n == total:
                flag("winners", "high", f"{col} entirely missing", str(year),
                     f"all {n:,} rows in {year} have no {col}")
            elif n / total > 0.5:
                flag("winners", "medium", f"{col} mostly missing", str(year),
                     f"{n:,} of {total:,} rows ({100 * n / total:.0f}%) have no {col}")

    # --- offices per cycle: spot a level that collapses ----------------------
    by_level = pd.crosstab(df["Year"], df["level"])
    print(f"\nrows by office level:\n{by_level.to_string()}")
    for lvl in by_level.columns:
        median = by_level[lvl].median()
        for year, n in by_level[lvl].items():
            if median and n < 0.5 * median:
                flag("winners", "high", f"{lvl} offices largely missing", str(year),
                     f"{year} has {n} {lvl} rows vs a median of {median:.0f} across cycles")

    # --- one office per locality per cycle -----------------------------------
    # A province returns exactly one governor; an LGU returns exactly one mayor. Counts
    # that miss the mark mean absent localities (under) or duplicated rows (over).
    print("\nofficeholders per cycle vs the true number of localities:")
    for pos, expected in EXPECTED_COUNTS.items():
        per_year = df[df["Position"] == pos]["Year"].value_counts().sort_index()
        print(f"  {pos:16} expected ~{expected:5,}  {per_year.to_dict()}")
        for year, n in per_year.items():
            drift = (n - expected) / expected
            if abs(drift) <= COUNT_TOLERANCE:
                continue
            direction = "more" if drift > 0 else "fewer"
            flag("winners", "high", f"implausible {pos} count", str(year),
                 f"{year} has {n:,} {pos} rows, {abs(drift) * 100:.0f}% {direction} than "
                 f"the ~{expected:,} localities that elect one "
                 f"({'duplicate rows' if drift > 0 else 'missing localities'})")

    # --- duplicate rows ------------------------------------------------------
    key = ["Year", "Province", "Position", "Full Name"]
    exact = df[df.duplicated()]
    same_seat = df[df.duplicated(subset=key, keep=False)]
    if not exact.empty:
        print(f"\nfully duplicated rows: {len(exact):,}")
        for year, n in exact["Year"].value_counts().sort_index().items():
            flag("winners", "high", "duplicate rows", str(year),
                 f"{n:,} rows in {year} are exact duplicates of another row")
    if not same_seat.empty:
        for year, n in same_seat["Year"].value_counts().sort_index().items():
            flag("winners", "medium", "same person listed twice for one seat", str(year),
                 f"{n:,} rows in {year} share a (Province, Position, Full Name) with "
                 f"another row")

    # --- province naming consistency ----------------------------------------
    # The same real place must not change key between cycles, or longitudinal grouping
    # silently splits it into unrelated panels.
    provinces = sorted(df["Province"].dropna().unique())
    print(f"\ndistinct Province values: {len(provinces)} "
          f"(the Philippines has 82 provinces + NCR districts)")

    def norm(p):
        p = p.upper().replace(",", " ").replace("-", " ")
        p = p.replace("NATIONAL CAPITAL REGION", "NCR")
        return " ".join(p.split())

    groups = {}
    for p in provinces:
        groups.setdefault(norm(p), []).append(p)

    for key, variants in sorted(groups.items()):
        if len(variants) > 1:
            spans = {v: sorted(df.loc[df["Province"] == v, "Year"].unique()) for v in variants}
            detail = "; ".join(f"{v!r} in {spans[v]}" for v in variants)
            flag("winners", "high", "province spelled differently across cycles", key,
                 f"{len(variants)} spellings of the same place: {detail}")

    return df, coverage


def audit_votecounts():
    print("\n" + "=" * 78)
    print("VOTE COUNTS (raw COMELEC scrapes)")
    print("=" * 78)

    rows = []
    for year in VOTE_COUNT_YEARS:
        root = raw_dir(year)
        files = sorted(root.rglob("*.csv"))
        print(f"\n{year}: {len(files):,} municipality files under {root.name}/")
        if not files:
            flag("votecounts", "high", "no raw files", str(year), f"{root} is empty")
            continue

        for f in files:
            rel = f.relative_to(root).parts
            region = rel[0] if len(rel) > 0 else ""
            province = rel[1] if len(rel) > 1 else ""
            try:
                d = pd.read_csv(f)
            except Exception as exc:  # unreadable file is itself a finding
                flag("votecounts", "high", "unreadable file", str(f), str(exc))
                continue

            if d.empty:
                flag("votecounts", "medium", "empty file", str(f.relative_to(root)),
                     "scraped file contains no rows")
                continue

            # Compare on the city name inside the file, NOT the filename: filenames embed
            # a region/province prefix that changed between cycles, which would report
            # hundreds of phantom "missing" municipalities.
            city = str(d["city"].dropna().iloc[0]).strip().upper() if "city" in d and not d["city"].dropna().empty else f.stem

            # LAV (Local Absentee Voting) is a real nationwide tally, not a place, and is
            # flagged as non-geographic in the published dataset rather than dropped.
            # Anything ELSE shaped like it is a scraper artefact and should be reported.
            if region == province == city and city not in NON_GEOGRAPHIC:
                flag("votecounts", "high", "junk locality scraped", f"{year}/{city}",
                     f"region, province and city are all {city!r} in "
                     f"{f.relative_to(root)} ({len(d):,} rows) - not a real place and not "
                     f"a known tally category; investigate")

            if city in NON_GEOGRAPHIC:
                continue  # counted separately; not a locality

            rows.append(
                {
                    "year": year,
                    "region": region,
                    "province": province,
                    "municipality": city,
                    "file": str(f.relative_to(root)),
                    "rows": len(d),
                    "positions": d["position"].nunique() if "position" in d else 0,
                    "total_votes": d["votes"].sum() if "votes" in d else 0,
                }
            )

    counts = pd.DataFrame(rows)
    counts.to_csv(AUDIT / "coverage_votecounts.csv", index=False)

    # Report the non-geographic tallies that were set aside above.
    published = pd.read_csv(VOTE_COUNTS_CSV, low_memory=False)
    special = published[~published["is_geographic"]]
    if not special.empty:
        for prov, grp in special.groupby("province"):
            offices = ", ".join(sorted(grp["position"].dropna().unique()))
            flag("votecounts", "info", "non-geographic tally category", str(prov),
                 f"{len(grp):,} rows ({grp['votes'].sum():,.0f} votes) under {prov!r} - a "
                 f"nationwide tally, not a place. Offices: {offices}. Excluded from "
                 f"geographic aggregation via is_geographic=False")

    if counts.empty:
        return counts

    per_year = counts.groupby("year").agg(
        municipalities=("municipality", "nunique"),
        provinces=("province", "nunique"),
        rows=("rows", "sum"),
    )
    print(f"\n{per_year.to_string()}")

    # Municipalities present in one cycle but not the other. Real causes include
    # municipality-to-city conversions (BALIUAG -> CITY OF BALIWAG) and diacritic
    # differences (ALFONSO CASTANEDA); genuine scrape gaps hide among them.
    by_year = {y: set(g["municipality"]) for y, g in counts.groupby("year")}
    if len(by_year) == 2:
        a, b = sorted(by_year)
        for missing_from, present_in in ((b, a), (a, b)):
            gap = sorted(by_year[present_in] - by_year[missing_from])
            if gap:
                flag("votecounts", "medium", "locality missing from a cycle",
                     str(missing_from),
                     f"{len(gap)} localities scraped in {present_in} but absent in "
                     f"{missing_from} (includes city conversions and spelling changes): "
                     f"{', '.join(gap[:8])}{' ...' if len(gap) > 8 else ''}")

    # The capital must be present in every cycle.
    for year in SCRAPED_YEARS:
        cities = set(counts.loc[counts["year"] == year, "municipality"])
        if not any("MANILA" in c for c in cities):
            flag("votecounts", "high", "City of Manila absent", str(year),
                 f"no municipality file for the City of Manila in the {year} scrape - "
                 f"the capital's mayor, vice mayor and councilors are missing entirely")

    return counts


def audit_alignment(winners):
    """The winners dataset must be derivable from the vote counts for the scraped years."""
    print("\n" + "=" * 78)
    print("ALIGNMENT: winners vs raw vote counts")
    print("=" * 78)

    ballots = pd.read_csv(VOTE_COUNTS_CSV, low_memory=False)

    def fold(value):
        text = unicodedata.normalize("NFKD", str(value))
        text = "".join(c for c in text if not unicodedata.combining(c))
        return re.sub(r"[^A-Z ]", "", text.upper()).strip()

    for year in VOTE_COUNT_YEARS:
        cast = ballots[ballots["year"] == year]
        won = winners[winners["Year"] == year]
        if cast.empty or won.empty:
            continue

        # Match on (province, surname), NOT the full name: the inherited cycles write
        # "CARMELO MANUBE ACNAM" where the feeds write "ACNAM, CARMELO", and ballots use
        # nicknames. Surname-within-province survives both.
        on_ballot = {
            (fold(p), fold(str(n).split(",")[0]))
            for p, n in zip(cast["province"], cast["candidate_name"].fillna(""))
        }
        elected = {
            (fold(p), fold(l))
            for p, l in zip(won["Province"], won["Last Name"].fillna(""))
        }

        orphans = elected - on_ballot
        pct = 100 * len(orphans) / max(len(elected), 1)
        print(f"\n{year}: {len(elected):,} (province, surname) winner keys, "
              f"{len(orphans):,} ({pct:.1f}%) absent from that province's ballots")

        if pct > 1:
            flag("alignment", "high", "winners disagree with the ballots", str(year),
                 f"{len(orphans):,} of {len(elected):,} winners ({pct:.1f}%) have a "
                 f"surname that appears nowhere on their province's {year} ballots. The "
                 f"cycles built FROM ballots score 0.0%, so this points at the inherited "
                 f"source file, not the scrape")

    # Cycles in the winners set with no vote counts at all.
    for year in YEARS:
        if year not in VOTE_COUNT_YEARS:
            flag("alignment", "info", "no vote counts for this cycle", str(year),
                 f"{year} winners are inherited from the source file; the vote-count "
                 f"dataset covers {VOTE_COUNT_YEARS}, so this cycle cannot be verified "
                 f"against ballots")


def main():
    AUDIT.mkdir(parents=True, exist_ok=True)

    winners, _ = audit_winners()
    audit_votecounts()
    audit_alignment(winners)

    df = pd.DataFrame(issues)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    df = df.sort_values(by="severity", key=lambda s: s.map(order))
    df.to_csv(AUDIT / "issues.csv", index=False)

    print("\n" + "=" * 78)
    print(f"ISSUES: {len(df)}")
    print("=" * 78)
    for sev in ["high", "medium", "low", "info"]:
        sub = df[df["severity"] == sev]
        if sub.empty:
            continue
        print(f"\n[{sev.upper()}] {len(sub)}")
        for _, r in sub.iterrows():
            print(f"  - ({r['scope']}) {r['issue']}: {r['detail']}")

    print(f"\nwrote coverage_winners.csv, coverage_votecounts.csv, issues.csv "
          f"to {AUDIT.name}/")


if __name__ == "__main__":
    main()
