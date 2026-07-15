"""
Derive election winners from the ballots, for every cycle we have vote counts for.

  data/output/NLE_Vote_Counts_*.csv.gz  ->  data/processed/winners_{year}.csv

One builder for every cycle, replacing the per-year scripts. The vote-counts dataset is
already canonical (position, district, province, city), so this only has to answer one
question per contest: who won, and how many seats were there?

Winners are ALWAYS decided by summing votes within the jurisdiction that elects the seat.
Never by a source's `rank` column - COMELEC's is an alphabetical index, not a standing.

Seats and jurisdictions
-----------------------
  MAYOR, VICE MAYOR          1 seat, elected by the city/municipality
  GOVERNOR, VICE GOVERNOR    1 seat, elected by the province
  HOUSE OF REPRESENTATIVES   1 seat, elected by the legislative district
      -> all five are unambiguous: no reference table needed. Votes are summed across
         every municipality that reports the race, then the top candidate wins.

  COUNCILOR                  N seats, elected by the city/municipality (by COUNCIL
                             DISTRICT where the city has them, e.g. Manila's six)
  PROVINCIAL BOARD MEMBER    N seats, elected by the PROVINCIAL DISTRICT

      -> these need a seat count, which the ballots do not carry. See SEATS below.

Provincial board members are elected BY DISTRICT. An earlier build ranked them across the
whole province and took the top N, which systematically favours candidates from populous
districts over genuine winners in small ones. They are now ranked within their district.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse

import pandas as pd

from config import (
    DEFAULT_COUNCILORS,
    PROCESSED,
    SOURCE_WINNERS,
    VOTE_COUNTS_CSV,
    VOTE_COUNT_YEARS,
    winners_csv,
)

# The seven local and district offices. The nationwide winners (president, vice president,
# senator) are added separately by build_national(); party list and the BARMM parliament
# stay in the vote counts only.
LOCAL_OFFICES = [
    "GOVERNOR",
    "VICE GOVERNOR",
    "PROVINCIAL BOARD MEMBER",
    "MEMBER, HOUSE OF REPRESENTATIVES",
    "MAYOR",
    "VICE MAYOR",
    "COUNCILOR",
]

# The jurisdiction that elects each office: the columns whose votes must be summed, and
# within which the winners are ranked.
JURISDICTION = {
    "GOVERNOR": ["province"],
    "VICE GOVERNOR": ["province"],
    "MEMBER, HOUSE OF REPRESENTATIVES": ["province", "district"],
    "PROVINCIAL BOARD MEMBER": ["province", "district"],
    "MAYOR": ["province", "city"],
    "VICE MAYOR": ["province", "city"],
    "COUNCILOR": ["province", "city", "district"],
}

SINGLE_SEAT = {
    "GOVERNOR",
    "VICE GOVERNOR",
    "MEMBER, HOUSE OF REPRESENTATIVES",
    "MAYOR",
    "VICE MAYOR",
}

# Nationwide races: one contest for the whole country, so the winner is the top-N by votes
# summed across every locality (overseas and local-absentee rows included). Party list is
# left out - its "candidates" are organisations and its seats need the BANAT allocation.
NATIONAL_SEATS = {"PRESIDENT": 1, "VICE PRESIDENT": 1, "SENATOR": 12}


def board_seats_per_district(ballots):
    """
    Seats per provincial district for the Sangguniang Panlalawigan.

    THE BALLOTS DO NOT CARRY THIS. Seats are apportioned by population and are not
    uniform - a province's districts can elect different numbers. We only have a
    per-province total (from the inherited source file), so it is split evenly across
    the province's districts.

    This is the weakest assumption in the pipeline and the one place a winner can still
    be wrong. A proper seats-per-district reference table would remove it.
    """
    source = pd.read_csv(SOURCE_WINNERS, low_memory=False)
    totals = (
        source[(source["Year"] == 2019)
               & (source["Position"] == "PROVINCIAL BOARD MEMBER")]
        .groupby("Province")
        .size()
        .to_dict()
    )

    districts = (
        ballots[ballots["position"] == "PROVINCIAL BOARD MEMBER"]
        .groupby("province")["district"]
        .nunique()
    )

    seats = {}
    for province, n_districts in districts.items():
        total = totals.get(province, 8)
        seats[province] = max(1, round(total / max(n_districts, 1)))
    return seats


def seats_for(position, province, board_seats):
    if position in SINGLE_SEAT:
        return 1
    if position == "COUNCILOR":
        return DEFAULT_COUNCILORS
    return board_seats.get(province, 4)  # PROVINCIAL BOARD MEMBER


def build_national(ballots, year):
    """PRESIDENT / VICE PRESIDENT / SENATOR: sum every locality nationwide, take the seats
    filled. No is_geographic filter - overseas and local-absentee votes are real ballots and
    are what make the totals match COMELEC's canvass. National offices have no geography, so
    region / province / city / district are left blank."""
    year_rows = ballots[ballots["year"] == year]
    rows = []
    for position, seats in NATIONAL_SEATS.items():
        race = year_rows[year_rows["position"] == position]
        if race.empty:
            continue
        tally = (
            race.groupby(["candidate_name", "party"], dropna=False, as_index=False)
            .agg(
                votes=("votes", "sum"),
                last_name=("last_name", "first"),
                first_name=("first_name", "first"),
                middle_name=("middle_name", "first"),
                title=("title", "first"),
            )
        )
        for _, r in tally.nlargest(seats, "votes").iterrows():
            rows.append({
                "region": None, "province": None, "city": None, "district": None,
                "position": position, "candidate_name": r["candidate_name"],
                "last_name": r["last_name"], "first_name": r["first_name"],
                "middle_name": r["middle_name"], "title": r["title"],
                "party": r["party"], "votes": r["votes"],
            })
    return rows


def build_year(ballots, year, board_seats):
    cast = ballots[(ballots["year"] == year) & ballots["is_geographic"]]
    cast = cast[cast["position"].isin(LOCAL_OFFICES)]

    rows = []
    for position in LOCAL_OFFICES:
        races = cast[cast["position"] == position]
        if races.empty:
            continue

        keys = JURISDICTION[position]

        # Sum each candidate's votes across every municipality reporting the race, THEN
        # rank within the jurisdiction that actually elects the seat.
        #
        # Carry the name fields the vote-counts build already parsed. Re-parsing here
        # would silently lose them: by this point `candidate_name` is the CLEANED name,
        # with the title and nickname already lifted out into their own columns.
        tally = (
            races.groupby(keys + ["candidate_name", "party"], dropna=False, as_index=False)
            .agg(
                votes=("votes", "sum"),
                region=("region", "first"),
                last_name=("last_name", "first"),
                first_name=("first_name", "first"),
                middle_name=("middle_name", "first"),
                title=("title", "first"),
            )
        )

        for _, group in tally.groupby(keys, dropna=False):
            province = group["province"].iloc[0]
            n = seats_for(position, province, board_seats)
            top = group.sort_values("votes", ascending=False).head(n)

            for _, r in top.iterrows():
                rows.append({
                    "region": r["region"],
                    "province": r["province"],
                    "city": r["city"] if "city" in group.columns else None,
                    "district": r["district"] if "district" in group.columns else None,
                    "position": position,
                    "candidate_name": r["candidate_name"],
                    "last_name": r["last_name"],
                    "first_name": r["first_name"],
                    "middle_name": r["middle_name"],
                    "title": r["title"],
                    "party": r["party"],
                    "votes": r["votes"],
                })

    rows.extend(build_national(ballots, year))

    out = pd.DataFrame(rows)
    print(f"\n{year}: {len(out):,} winners")
    print(out["position"].value_counts().to_string())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append", default=[],
                    help="only build this cycle (repeatable)")
    args = ap.parse_args()

    years = args.year or VOTE_COUNT_YEARS

    ballots = pd.read_csv(VOTE_COUNTS_CSV, low_memory=False)
    print(f"ballots: {len(ballots):,} rows covering {sorted(ballots['year'].unique())}")

    board_seats = board_seats_per_district(ballots)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    for year in years:
        winners = build_year(ballots, year, board_seats)
        out = winners_csv(year)
        winners.to_csv(out, index=False)
        print(f"  -> {out.name}")


if __name__ == "__main__":
    main()
