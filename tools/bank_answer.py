"""Save a screening answer so the next application reuses it.

Whenever a form asks something the app cannot answer, ask the user in chat and
then bank the reply here -- it goes in the same `answers` table apply_cli reads,
keyed on the normalised question text.

    python tools/bank_answer.py "Are you willing to relocate?" "No"
    python tools/bank_answer.py "Notice period" "2 weeks" --company "AutoCanada"
    python tools/bank_answer.py --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "resume.db"


def norm(q: str) -> str:
    """Same shape the bank already uses: lowercased, punctuation stripped."""
    q = (q or "").strip().lower()
    q = re.sub(r"[^a-z0-9 ]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def put(question: str, answer: str, company: str = "", verified: bool = True) -> str:
    n = norm(question)
    if not n:
        sys.exit("empty question")
    con = sqlite3.connect(DB)
    row = con.execute("select id, data from answers where norm = ?", (n,)).fetchone()
    if row:
        aid, data = row[0], json.loads(row[1])
        data.update({"answer": answer, "question": question, "verified": verified})
        con.execute(
            "update answers set answer = ?, question = ?, verified = ?, data = ? where id = ?",
            (answer, question, int(verified), json.dumps(data), aid))
        action = "updated"
    else:
        aid = hashlib.sha1(n.encode()).hexdigest()[:16]
        data = {"id": aid, "norm": n, "question": question, "answer": answer,
                "tags": [], "verified": verified, "times_used": 0,
                "source_company": company, "date_added": date.today().isoformat()}
        con.execute(
            "insert into answers (id, norm, question, answer, verified, times_used,"
            " source_company, date_added, data) values (?,?,?,?,?,?,?,?,?)",
            (aid, n, question, answer, int(verified), 0, company,
             date.today().isoformat(), json.dumps(data)))
        action = "added"
    con.commit()
    print("{} [{}] {!r} -> {!r}".format(action, aid, question, answer))
    return aid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("answer", nargs="?")
    ap.add_argument("--company", default="")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        con = sqlite3.connect(DB)
        rows = con.execute(
            "select question, answer, times_used from answers order by question").fetchall()
        print("{} banked answers".format(len(rows)))
        for q, ans, used in rows:
            print("  {:58} {:28} (used {})".format(q[:58], str(ans)[:28], used))
        return 0

    if not a.question or a.answer is None:
        ap.error("give a question and an answer, or --list")
    put(a.question, a.answer, a.company)
    return 0


if __name__ == "__main__":
    sys.exit(main())
