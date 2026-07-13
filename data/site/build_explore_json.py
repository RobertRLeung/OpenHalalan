"""
Build the compact JSON the Explore table on the website runs on.

    python data/site/build_explore_json.py            -> data/site/explore.json

The site is static, so the whole table has to ship to the browser. The published winners
file is 139,706 rows and ~12 MB of CSV, which is too much to hand a phone. This packs it
down by dictionary-encoding the four low-cardinality columns (7 positions, 18 regions, 88
provinces, 397 parties) and emitting rows as arrays rather than objects.

What goes in
------------
  Every winner, all 8 cycles, from data/output/NLE_Winners_2004-2025.csv.

  Vote totals, where they exist. The published winners file carries no votes, but the
  ballot-derived cycles do (data/processed/winners_{year}.csv). 2004-2013 have no ballots,
  so their votes are null - shown as an em dash, not a zero.

  National winners - PRESIDENT, VICE PRESIDENT, SENATOR - which the winners dataset does
  NOT contain (it covers the seven local and district offices only). These are derived
  here from the vote counts by summing each candidate nationwide.

What is deliberately held back
------------------------------
  2022's national races. The 2022 COMELEC scrape was truncated: it captured 7 of the 10
  presidential candidates and none of the party-list race. Robredo, who finished second
  with ~15M votes, is missing from it. A re-scrape against COMELEC's JSON API is in
  progress; until it lands, publishing 2022 national results would be publishing figures
  we already know are wrong.

  PARTY LIST. The "candidates" are organisations, not people, and they do not belong in a
  table of winning candidates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from config import PROCESSED, VOTE_COUNTS_CSV, WINNERS_CSV

OUT = Path(__file__).resolve().parent / "explore.json"

# Cycles whose national races are trustworthy. 2022 is excluded: see the module docstring.
NATIONAL_YEARS = [2016, 2019, 2025]
NATIONAL_OFFICES = {"PRESIDENT": 1, "VICE PRESIDENT": 1, "SENATOR": 12}


def local_winners():
    """Every winner in the published dataset, with votes where the ballots give them."""
    w = pd.read_csv(WINNERS_CSV, low_memory=False)

    # Votes live in the ballot-derived intermediates, not the published file.
    votes = []
    for path in sorted(PROCESSED.glob("winners_*.csv")):
        year = int(path.stem.split("_")[1])
        v = pd.read_csv(path)
        v["Year"] = year
        votes.append(v[["Year", "province", "position", "candidate_name", "votes"]])

    if votes:
        v = pd.concat(votes, ignore_index=True).rename(columns={
            "province": "Province", "position": "Position",
            "candidate_name": "Full Name", "votes": "Votes",
        })
        # A person can win two seats in different cities in one province (councilors), so
        # collapse to one vote figure per (year, province, position, name).
        v = v.groupby(["Year", "Province", "Position", "Full Name"], as_index=False)["Votes"].max()
        w = w.merge(v, on=["Year", "Province", "Position", "Full Name"], how="left")
    else:
        w["Votes"] = pd.NA

    return w[["Year", "Position", "Region", "Province", "Full Name", "Party", "Votes"]]


def national_winners():
    """PRESIDENT / VICE PRESIDENT / SENATOR, summed nationwide from the ballots."""
    ballots = pd.read_csv(VOTE_COUNTS_CSV, low_memory=False)
    ballots = ballots[ballots["year"].isin(NATIONAL_YEARS)]

    rows = []
    for office, seats in NATIONAL_OFFICES.items():
        race = ballots[ballots["position"] == office]
        if race.empty:
            continue

        # Sum every locality, then take the seats actually filled.
        tally = (race.groupby(["year", "candidate_name", "party"], as_index=False)["votes"]
                     .sum())
        for year, group in tally.groupby("year"):
            for _, r in group.nlargest(seats, "votes").iterrows():
                rows.append({
                    "Year": int(year),
                    "Position": office,
                    "Region": "Nationwide",
                    "Province": "Nationwide",
                    "Full Name": r["candidate_name"],
                    "Party": r["party"],
                    "Votes": int(r["votes"]),
                })
    return pd.DataFrame(rows)


def main():
    local = local_winners()
    national = national_winners()
    print(f"local winners   : {len(local):,}")
    print(f"national winners: {len(national):,} (cycles {NATIONAL_YEARS}; 2022 held back)")

    df = pd.concat([national, local], ignore_index=True)

    # One casing for display. The dataset stores "COUNCILOR"/"MEMBER, HOUSE OF
    # REPRESENTATIVES"; the table reads better in title case.
    def pretty(position):
        text = str(position).title().replace("Of", "of")
        return text.replace("Vice-", "Vice ")

    df["Position"] = df["Position"].map(pretty)

    # Dictionary-encode the low-cardinality columns; the names are the only bulky field.
    dicts = {}
    codes = {}
    for col in ("Position", "Region", "Province", "Party"):
        values = sorted(df[col].dropna().unique().tolist())
        dicts[col] = values
        index = {v: i for i, v in enumerate(values)}
        codes[col] = df[col].map(index).fillna(-1).astype(int).tolist()

    years = df["Year"].astype(int).tolist()
    names = df["Full Name"].fillna("").tolist()
    votes = [None if pd.isna(v) else int(v) for v in df["Votes"]]

    rows = [
        [years[i], codes["Position"][i], codes["Region"][i],
         codes["Province"][i], names[i], codes["Party"][i], votes[i]]
        for i in range(len(df))
    ]

    payload = {
        "fields": ["year", "position", "region", "province", "name", "party", "votes"],
        "positions": dicts["Position"],
        "regions": dicts["Region"],
        "provinces": dicts["Province"],
        "parties": dicts["Party"],
        "rows": rows,
    }

    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    mb = OUT.stat().st_size / 1e6
    print(f"\nwrote {OUT.name}: {len(rows):,} rows, {mb:.1f} MB "
          f"({mb / 4:.1f} MB or so over the wire once gzipped)")
    print(f"  with votes: {sum(v is not None for v in votes):,} rows")


if __name__ == "__main__":
    main()
