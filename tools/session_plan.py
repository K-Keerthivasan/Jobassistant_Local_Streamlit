"""Turn a prepared apply_cli session into a fill plan for tools/apply_browser.py.

    python tools/session_plan.py <session_id> --fields fields.json --out plan.json

Adds the resume/cover uploads and drops values the control cannot accept
(e.g. a phone number matched onto a country <select>), so the browser step
never types nonsense into a dropdown.

`build_plan` is imported by apply_browser's one-session `apply` command.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "resume.db"

RESUME_HINTS = ("resume", "cv", "curriculum")
COVER_HINTS = ("cover", "letter", "motivation")


def _best_option(options, value):
    """Match a planned value to a real <select> option, else None."""
    if not options:
        return None
    v = (value or "").strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    for o in options:
        if v and (v in o.lower() or o.lower() in v):
            return o
    return None


def load_session(session: str) -> dict:
    con = sqlite3.connect(DB)
    row = con.execute(
        "select data from apply_sessions where session_id = ? or session_id like ?",
        (session, session + "%")).fetchone()
    if not row:
        raise SystemExit("no session " + session)
    return json.loads(row[0])


def build_plan(session: str | dict, scanned_fields: list) -> tuple[dict, list, list]:
    """Returns (plan, skipped, unanswered).

    `unanswered` are required controls on the page that nothing filled -- those
    are the ones to ask the user about and then bank.
    """
    d = session if isinstance(session, dict) else load_session(session)
    scanned = {f["selector"]: f for f in scanned_fields}

    docs = d.get("documents", {})
    resume = (docs.get("resume") or {}).get("path") or ""
    cover = (docs.get("cover_letter") or {}).get("path") or ""

    out, skipped = [], []
    planned = list(d.get("standard_fields", [])) + list(d.get("screening_answers", []))
    for f in planned:
        sel, val = f.get("selector"), f.get("value")
        label, ftype = f.get("label", ""), f.get("type", "text")
        if not sel or val in (None, ""):
            continue
        live = scanned.get(sel, {})
        if ftype == "select" or live.get("type") == "select":
            opt = _best_option(live.get("options"), val)
            if not opt:
                skipped.append({"label": label, "value": val, "selector": sel,
                                "why": "not one of the options",
                                "options": live.get("options", [])})
                continue
            val = opt
        out.append({"selector": sel, "value": val, "type": live.get("type", ftype),
                    "label": label})

    # File inputs the planner does not own: attach the tailored documents.
    for sel, f in scanned.items():
        if f.get("type") != "file":
            continue
        lab = " ".join((f.get("label", ""), f.get("name", ""), f.get("id", ""))).lower()
        path = cover if any(h in lab for h in COVER_HINTS) else resume
        if path and Path(path).exists():
            out.append({"selector": sel, "value": path, "type": "file",
                        "label": f.get("label") or "file upload"})

    # Anything required on the page that nothing is filling.
    filled = {f["selector"] for f in out}
    unanswered = [f for sel, f in scanned.items()
                  if f.get("required") and sel not in filled and f.get("type") != "file"]

    plan = {"session": d.get("session_id"), "url": d.get("job_url"),
            "company": d.get("company"), "title": d.get("title"), "fields": out}
    return plan, skipped, unanswered


def report(plan, skipped, unanswered, warnings=()):
    print("{} - {}".format(plan.get("company"), plan.get("title")))
    for f in plan["fields"]:
        print("  {:9} {:36} {}".format(f["type"], f["label"][:36], str(f["value"])[:60]))
    for s in skipped:
        print("  SKIP      {} <- {!r} ({})".format(s["label"], s["value"], s["why"]))
    for u in unanswered:
        opts = u.get("options") or []
        print("  ASK       {} [{}]{}".format(
            u.get("label", "?")[:60], u.get("type"),
            "  options: " + " | ".join(opts[:6]) if opts else ""))
    for w in warnings:
        print("  WARN      " + str(w)[:150])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--fields", required=True, help="the fields.json the scan produced")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    d = load_session(a.session)
    scanned = json.loads(Path(a.fields).read_text(encoding="utf-8"))
    plan, skipped, unanswered = build_plan(d, scanned)
    Path(a.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print("plan -> {} ({} fields)".format(a.out, len(plan["fields"])))
    report(plan, skipped, unanswered, d.get("warnings", []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
