"""Pull a job's generated resume/cover PDFs out of the running app.

The API owns the documents (the container writes them to its own volume), so
the only supported way to get them is /download/{run_id}/{artifact}.

    python tools/fetch_docs.py <key_id_or_prefix> [--dest DIR]

Prints the local paths, one "resume=<path>" / "cover=<path>" per line.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "resume.db"
API = "http://localhost:8088"
ARTIFACTS = {"resume": "resume.pdf", "cover": "cover.pdf",
             "resume_docx": "resume.docx", "email": "email.txt"}


def job_row(key: str) -> tuple[str, dict]:
    con = sqlite3.connect(DB)
    row = con.execute(
        "select key_id, data from jobs where key_id = ? or key_id like ?",
        (key, key + "%"),
    ).fetchone()
    if not row:
        sys.exit("no job matching " + key)
    return row[0], json.loads(row[1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--dest", default=str(ROOT / "data" / "job-applications" / "outbox"))
    ap.add_argument("--want", default="resume,cover")
    a = ap.parse_args(argv)

    key_id, data = job_row(a.key)
    run_id = data.get("notes") or ""
    if not run_id:
        sys.exit("job {} has no run folder recorded".format(key_id))

    dest = Path(a.dest) / run_id
    dest.mkdir(parents=True, exist_ok=True)
    print("job={} run={}".format(key_id, run_id))

    ok = True
    for want in a.want.split(","):
        name = ARTIFACTS.get(want.strip())
        if not name:
            continue
        url = "{}/download/{}/{}".format(API, run_id, name)
        try:
            r = httpx.get(url, timeout=60)
        except Exception as e:
            print("{}=ERROR {}".format(want, e))
            ok = False
            continue
        if r.status_code != 200 or not r.content:
            print("{}=MISSING http {}".format(want, r.status_code))
            ok = False
            continue
        out = dest / name
        out.write_bytes(r.content)
        print("{}={}".format(want, out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
