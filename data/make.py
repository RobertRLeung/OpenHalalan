"""
The OpenHalalan data pipeline. One entry point for all three stages.

    python data/make.py              # rebuild both datasets from the committed raw scrapes, then audit
    python data/make.py --scrape     # re-scrape COMELEC first (slow: hours, drives a real browser)
    python data/make.py --audit-only # just re-run the completeness audit
    python data/make.py --stage compiling

Stages, in dependency order:

  scraping    COMELEC websites -> data/raw_data/{2022,2025}/
              Skipped by default: the raw scrapes are committed, so replication never
              needs to touch COMELEC. Each scraper takes --region/--province to re-fetch
              one place, and skips municipalities already on disk.

  compiling   raw scrapes + data/source/ -> data/processed/ (intermediates)
                                         -> data/output/    (the published datasets)
              1. build_winners_2022.py   raw 2022 -> processed/winners_2022.csv
              2. build_winners_2025.py   raw 2025 -> processed/winners_2025.csv
              3. merge_winners.py        source 2004-2019 + both -> output/NLE_Winners_2004-2025.csv
              4. build_vote_counts.py    all raw scrapes         -> output/NLE_Vote_Counts_2022-2025.csv.gz

  audit       both datasets -> data/audit/{issues,coverage_*}.csv
              Reports only; never modifies the data.

All paths come from config.yaml. Requirements: pip install -r requirements.txt
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES = {
    "scraping": [
        HERE / "scraping" / "scrape_2022_comelec.py",
        HERE / "scraping" / "scrape_2025_comelec.py",
    ],
    "compiling": [
        HERE / "compiling" / "build_winners_2022.py",
        HERE / "compiling" / "build_winners_2025.py",
        HERE / "compiling" / "merge_winners.py",
        HERE / "compiling" / "build_vote_counts.py",
    ],
    "audit": [
        HERE / "audit" / "audit.py",
    ],
}


def run_stage(name):
    print(f"\n{'#' * 78}\n# {name}\n{'#' * 78}", flush=True)
    for script in STAGES[name]:
        print(f"\n{'=' * 78}\n{script.name}\n{'=' * 78}", flush=True)
        subprocess.run([sys.executable, str(script)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--scrape", action="store_true",
                    help="re-scrape COMELEC before compiling (slow; not needed for replication)")
    ap.add_argument("--audit-only", action="store_true",
                    help="skip rebuilding; just re-run the audit")
    ap.add_argument("--stage", choices=list(STAGES),
                    help="run a single stage")
    args = ap.parse_args()

    if args.stage:
        run_stage(args.stage)
    elif args.audit_only:
        run_stage("audit")
    else:
        if args.scrape:
            run_stage("scraping")
        run_stage("compiling")
        run_stage("audit")

    print("\nDone. Datasets in data/output/, audit report in data/audit/.")


if __name__ == "__main__":
    main()
