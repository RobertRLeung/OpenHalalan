"""
The OpenHalalan data pipeline. One entry point for all three stages.

    python data/make.py              # rebuild both datasets from the committed raw scrapes, then audit
    python data/make.py --scrape     # re-scrape COMELEC first (slow, drives a real browser)
    python data/make.py --audit-only # just re-run the completeness audit
    python data/make.py --stage compiling

Stages, in dependency order:

  scraping    COMELEC websites -> data/raw_data/. Skipped by default: the raw scrapes are
              committed, so replication never needs to touch COMELEC.
  compiling   raw scrapes + data/source/ -> data/output/, the published datasets. Scripts run
              in the order listed below; each one's own docstring says what it does.
  audit       reports on both datasets; never modifies them.

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
        # Vote counts first: the winners are DERIVED from them.
        HERE / "compiling" / "build_vote_counts.py",
        HERE / "compiling" / "build_winners_from_ballots.py",
        HERE / "compiling" / "merge_winners.py",
        # Runs on the finished outputs, so it stays after the merge.
        (HERE / "compiling" / "backfill_person_fields.py", "--apply"),
    ],
    "audit": [
        HERE / "audit" / "audit.py",
    ],
}


def run_stage(name):
    print(f"\n{'#' * 78}\n# {name}\n{'#' * 78}", flush=True)
    for entry in STAGES[name]:
        script, script_args = (entry, []) if isinstance(entry, Path) else (entry[0], list(entry[1:]))
        print(f"\n{'=' * 78}\n{script.name}\n{'=' * 78}", flush=True)
        subprocess.run([sys.executable, str(script), *script_args], check=True)


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
