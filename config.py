"""
Single source of truth for pipeline paths and settings.

Every script in data/scraping, data/compiling and data/audit imports from here, so no
script contains a machine-specific path. Edit config.yaml, not the scripts.

Usage from anywhere in the repo:

    from config import CONFIG, RAW_2022, PROCESSED
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent

with (ROOT / "config.yaml").open() as fh:
    CONFIG = yaml.safe_load(fh)


def path(key):
    """Resolve a key under `paths:` in config.yaml to an absolute path."""
    return ROOT / CONFIG["paths"][key]


RAW_2022 = path("raw_2022")
RAW_2025 = path("raw_2025")
SOURCE_WINNERS = path("source_winners")
PROCESSED = path("processed")
OUTPUT = path("output")
AUDIT = path("audit")

YEARS = CONFIG["datasets"]["years"]
SCRAPED_YEARS = CONFIG["datasets"]["scraped_years"]
WINNERS_COLUMNS = CONFIG["datasets"]["winners_columns"]
DROPPED_COLUMNS = CONFIG["datasets"]["dropped_columns"]
POSITIONS = CONFIG["datasets"]["positions"]

DEFAULT_COUNCILORS = CONFIG["compiling"]["default_councilors"]

WINNERS_CSV = OUTPUT / CONFIG["datasets"]["winners_file"]
VOTE_COUNTS_CSV = OUTPUT / CONFIG["datasets"]["vote_counts_file"]


def raw_dir(year):
    """Raw COMELEC scrape directory for a scraped year."""
    return path(f"raw_{year}")


def winners_csv(year):
    """Per-cycle intermediate winners file produced by data/compiling."""
    return PROCESSED / f"winners_{year}.csv"


def bootstrap():
    """
    Put the repo root on sys.path so scripts nested in data/*/ can `import config`.

    Call at the top of every pipeline script:

        import sys; from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    """
    PROCESSED.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
