"""
Reshape the 2010 national results into the project's long format.

data/source/2010_national_source.csv is a wide table: one row per city/municipality, one
column per candidate, prefixed by office.

    "P: AQUINO, Benigno Simeon III C."     <- president
    "VP: BINAY, Jejomar C."                <- vice president
    "S: BONG REVILLA, Ramon, Jr. B."       <- senator

This melts it into one row per locality and candidate, writing data/processed/national_2010.csv
for build_vote_counts.py. The locality PSGC is kept for traceability. 2010 is a
national-races-only cycle here; the source carries no local offices.

    python data/scraping/parse_2010.py

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
