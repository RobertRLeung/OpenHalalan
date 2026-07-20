"""
Reshape the 2010 national municipal results into the project's long format.

The 2010 presidential, vice-presidential and senatorial votes were recovered from a
municipal-level tabulation (data/source/2010_national_source.csv) that carries one ROW per
city/municipality and one COLUMN per candidate, prefixed by office:

    "P: AQUINO, Benigno Simeon III C."     <- president
    "VP: BINAY, Jejomar C."                <- vice president
    "S: BONG REVILLA, Ramon, Jr. B."       <- senator

Each cell is that candidate's vote total in that locality. This melts the wide table into
one row per (locality, candidate) and writes data/processed/national_2010.csv, the tidy
extract build_vote_counts.py consumes. The source also carries the PSGC of every locality
(adm3_psgc), kept alongside for traceability.

    python data/scraping/parse_2010.py

Coverage: 1,519 of the ~1,634 cities and municipalities (93%); 2010 is a national-race-only
cycle for the project - no local offices are in this source.

Source: the Ianmaps Election Bank, compiled by Ian (@ian_maps) and Joseph Ricafort
(@josephricafort), shared for this project. With thanks.
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source" / "2010_national_source.csv"
OUT = ROOT / "processed" / "national_2010.csv"

OFFICE = {"P": "PRESIDENT", "VP": "VICE PRESIDENT", "S": "SENATOR"}


def parse():
    # The source is Latin-1 (Filipino place names carry Ñ), not UTF-8.
    d = pd.read_csv(SRC, dtype=str, encoding="latin-1", low_memory=False)
    # Keep only rows that actually carry election data; the file also lists localities that
    # have geometry but no 2010 result (blank COMELEC name), which are dropped here.
    d = d[d["Municipality/City"].notna() & (d["Municipality/City"].astype(str).str.strip() != "")]

    rename = {"Region": "region", "Province.1": "province",
              "Municipality/City": "city", "adm3_psgc": "psgc"}
    value_cols = [c for c in d.columns if c.startswith(("P: ", "VP: ", "S: "))]
    m = (d.melt(id_vars=list(rename), value_vars=value_cols,
                var_name="col", value_name="votes")
           .rename(columns=rename))

    m = m[m["votes"].notna()]
    m["votes"] = m["votes"].str.replace(",", "", regex=False).str.strip()
    m = m[m["votes"].str.match(r"^\d+$", na=False)]           # drop "-" / blank non-votes

    m["position"] = m["col"].str.split(":", n=1).str[0].map(OFFICE)
    m["candidate_name"] = m["col"].str.split(":", n=1).str[1].str.strip()
    m["year"] = 2010
    m["votes"] = m["votes"].astype(int)

    out = m[["year", "region", "province", "city", "psgc",
             "position", "candidate_name", "votes"]]
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT.name}: {len(out):,} rows, "
          f"{out.city.nunique()} locality names, {out.province.nunique()} provinces")
    print(out.groupby("position").size().to_string())
    return out


if __name__ == "__main__":
    parse()
