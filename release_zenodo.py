"""
Publish a new version of the OpenHalalan dataset to Zenodo.

    export ZENODO_TOKEN=...            # zenodo.org > Applications > Personal access tokens
                                       # scopes: deposit:write, deposit:actions
    python release_zenodo.py --version 4.0 --notes "what changed"      # stages a DRAFT
    python release_zenodo.py --version 4.0 --notes "..." --publish     # and mints the DOI

Uploads the two published datasets from data/output/ as a NEW VERSION of the existing
record, which is what keeps the concept DOI (10.5281/zenodo.17783099) pointing at the
newest data. Every prior version stays citable and reachable; nothing is overwritten.

By default it stops at a draft, so the record can be read back before a DOI is minted.
A DOI is permanent: once published it cannot be retracted, only superseded. That is the
whole reason this project re-scraped 2022 rather than archiving what it had.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from config import VOTE_COUNTS_CSV, WINNERS_CSV

API = "https://zenodo.org/api"
CONCEPT_RECID = "17783099"          # the "always the latest version" record
LATEST_RECID = "21331500"           # v3, the one being superseded

FILES = [WINNERS_CSV, VOTE_COUNTS_CSV]


def call(method, url, token, data=None, raw=None, content_type="application/json"):
    if "?" not in url:
        url += f"?access_token={token}"
    else:
        url += f"&access_token={token}"
    body = raw if raw is not None else (json.dumps(data).encode() if data else None)
    req = urllib.request.Request(url, data=body, method=method)
    if raw is None and data is not None:
        req.add_header("Content-Type", content_type)
    elif raw is not None:
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            text = r.read().decode()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"\n{method} {url.split('?')[0]} -> {e.code}\n{e.read().decode()[:800]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help='e.g. "4.0"')
    ap.add_argument("--notes", required=True, help="what changed in this version")
    ap.add_argument("--publish", action="store_true",
                    help="mint the DOI. Irreversible. Without this you get a draft.")
    args = ap.parse_args()

    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        sys.exit("ZENODO_TOKEN is not set")

    for f in FILES:
        if not Path(f).exists():
            sys.exit(f"missing {f} - run `python run_all.py` first")

    print(f"opening a new version of record {LATEST_RECID} ...")
    new = call("POST", f"{API}/deposit/depositions/{LATEST_RECID}/actions/newversion", token)
    draft_url = new["links"]["latest_draft"]
    draft = call("GET", draft_url, token)
    dep_id = draft["id"]
    print(f"  draft deposition {dep_id}")

    # A new version inherits the old version's FILES. They are the previous data, so they
    # have to go before the corrected ones are uploaded, or the record carries both.
    for f in draft.get("files", []):
        print(f"  removing inherited file {f['filename']}")
        call("DELETE", f"{API}/deposit/depositions/{dep_id}/files/{f['id']}", token)

    bucket = draft["links"]["bucket"]
    for path in FILES:
        path = Path(path)
        mb = path.stat().st_size / 1e6
        print(f"  uploading {path.name} ({mb:.1f} MB) ...")
        call("PUT", f"{bucket}/{path.name}", token, raw=path.read_bytes())

    meta = draft["metadata"]
    meta["version"] = args.version
    meta["description"] = (
        f"{meta.get('description', '')}"
        f"<p><strong>Version {args.version}.</strong> {args.notes}</p>"
    )
    print(f"  setting version {args.version}")
    call("PUT", f"{API}/deposit/depositions/{dep_id}", token, data={"metadata": meta})

    if not args.publish:
        print(f"\nDRAFT staged, NOT published. Review it, then re-run with --publish:")
        print(f"  https://zenodo.org/uploads/{dep_id}")
        return

    print("  publishing (this mints the DOI and cannot be undone) ...")
    pub = call("POST", f"{API}/deposit/depositions/{dep_id}/actions/publish", token)
    print(f"\npublished: {pub['doi']}")
    print(f"  record : https://zenodo.org/records/{pub['id']}")
    print(f"  concept: https://doi.org/10.5281/zenodo.{CONCEPT_RECID}  (always the latest)")


if __name__ == "__main__":
    main()
