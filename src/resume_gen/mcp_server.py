"""MCP tools for the approval-first job-application workflow.

This server gives ChatGPT/Codex a narrow connection to Resume Studio. Browser
navigation remains the browser controller's job; these tools own candidate data,
tailored documents, field plans, the human approval gate, and the audit trail.

Run locally (stdio, used by the personal Codex plugin)::

    python -m resume_gen.mcp_server

Run for ChatGPT developer-mode connections (streamable HTTP at ``/mcp``)::

    python -m resume_gen.mcp_server --transport streamable-http --port 8090
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .automation import autoapply
from .intake import apply_sessions, runs, store


INSTRUCTIONS = """Resume Studio is the source of truth for job applications.
For a queue run, start with list_application_candidates and process one job at a
time. Use browser tools only to inspect and fill the current job site. First call
prepare_job_application with the fields read from the page. Fill only values in
the returned plan. Then show the complete approval summary and ask the user for
a fresh yes/no decision. Never call decide_job_application with approved=true
until the user explicitly approves that session. Never click Submit unless the
decision result says may_submit=true. Never bypass login, CAPTCHA, consent, or
required unanswered fields. Always record the observed final outcome."""

mcp = FastMCP(
    "resume-studio",
    instructions=INSTRUCTIONS,
    host="127.0.0.1",
    port=8090,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
LOCAL_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
APPROVAL_GATE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)


def _job_summary(job) -> dict[str, Any]:
    d = job.model_dump() if hasattr(job, "model_dump") else dict(job)
    return {
        "job_key": d.get("key_id", ""),
        "company": d.get("company", ""),
        "title": d.get("title", ""),
        "location": d.get("location", ""),
        "status": d.get("status", ""),
        "apply_url": d.get("apply_url", ""),
        "applied": bool(d.get("applied")),
        "priority": d.get("priority_level", ""),
        "generated_run_id": d.get("notes", ""),
    }


@mcp.tool(
    title="List job opportunities",
    description="List jobs saved in Resume Studio so the user can choose one to review, generate, or apply to.",
    annotations=READ_ONLY,
)
def list_job_opportunities(
    status: str = "", query: str = "", limit: int = 25
) -> dict[str, Any]:
    jobs = store.list_queue(status=status or None)
    needle = query.strip().casefold()
    if needle:
        jobs = [
            job for job in jobs
            if needle in " ".join((job.company, job.title, job.location)).casefold()
        ]
    items = [_job_summary(job) for job in jobs[: max(1, min(limit, 100))]]
    return {"jobs": items, "count": len(items)}


@mcp.tool(
    title="List application candidates",
    description=(
        "List generated, unapplied jobs ready for an MCP-guided browser application. "
        "Defaults to jobs found in the past seven days and returns queue priority, "
        "generated run id, apply URL, ATS, and known restriction flags."
    ),
    annotations=READ_ONLY,
)
def list_application_candidates(
    days: int = 7, limit: int = 100, company: str = ""
) -> dict[str, Any]:
    window = max(1, min(int(days), 365))
    capped = max(1, min(int(limit), 100))
    since = (date.today() - timedelta(days=window)).isoformat()
    rows = autoapply.candidates(limit=capped, since=since, company=company)
    return {
        "candidates": rows,
        "count": len(rows),
        "since": since,
        "likely_restricted": sum(1 for row in rows if row.get("likely_blocked")),
    }


@mcp.tool(
    title="Get a job opportunity",
    description="Get the complete saved posting for one Resume Studio job key before preparing an application.",
    annotations=READ_ONLY,
)
def get_job_opportunity(job_key: str) -> dict[str, Any]:
    job = store.get_job(job_key)
    if job is None:
        raise ValueError(f"No job found for key {job_key!r}.")
    return job.model_dump()


@mcp.tool(
    title="List application history",
    description="List recent generated applications and approval sessions without changing anything.",
    annotations=READ_ONLY,
)
def list_application_history(limit: int = 25) -> dict[str, Any]:
    capped = max(1, min(limit, 100))
    recent_runs = runs.list_runs()[:capped]
    recent_sessions = apply_sessions.list_sessions(limit=capped)
    return {
        "generated": recent_runs,
        "approval_sessions": [
            {
                "session_id": s.get("session_id", ""),
                "job_key": s.get("job_key", ""),
                "company": s.get("company", ""),
                "title": s.get("title", ""),
                "status": s.get("status", ""),
                "created_at": s.get("created_at", ""),
                "submit_by": s.get("submit_by", ""),
            }
            for s in recent_sessions
        ],
    }


@mcp.tool(
    title="Prepare a job application",
    description=(
        "Prepare, but never submit, one application. Pass the job page's visible form controls "
        "so Resume Studio can map identity fields, draft truthful screening answers, render the "
        "documents, and return a fill plan plus the approval summary."
    ),
    annotations=LOCAL_WRITE,
)
def prepare_job_application(
    job_url: str,
    company: str = "",
    title: str = "",
    description: str = "",
    location: str = "",
    form_fields: list[dict[str, Any]] | None = None,
    run_id: str = "",
    regenerate: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    return autoapply.prepare(
        job_url=job_url,
        company=company,
        title=title,
        description=description,
        location=location,
        fields=form_fields or [],
        run_id=run_id,
        regenerate=regenerate,
        model=model,
    )


@mcp.tool(
    title="Get application approval packet",
    description="Read one prepared application's field plan, warnings, documents, and human approval summary.",
    annotations=READ_ONLY,
)
def get_application_approval(session_id: str) -> dict[str, Any]:
    session = apply_sessions.get_session(session_id)
    if session is None:
        raise ValueError(f"No application session found for {session_id!r}.")
    session["summary"] = autoapply.build_summary(session)
    return session


@mcp.tool(
    title="Record the user's application decision",
    description=(
        "THE HUMAN APPROVAL GATE. Call with approved=true only after showing this session's full "
        "summary and receiving an explicit fresh yes from the user. A true result may authorize a "
        "separate browser tool to click Submit; this tool itself never submits. Use approved=false "
        "to reject and close the attempt."
    ),
    annotations=APPROVAL_GATE,
)
def decide_job_application(
    session_id: str,
    approved: bool,
    edits: dict[str, str] | None = None,
    submit_by: str = "agent",
    note: str = "",
) -> dict[str, Any]:
    return autoapply.confirm(
        session_id,
        approved=approved,
        edits=edits,
        submit_by=submit_by,
        note=note,
    )


@mcp.tool(
    title="Record application result",
    description=(
        "After the browser or user finishes, record the observed result as submitted, failed, "
        "or rejected. Do not report submitted unless the site displayed a success state."
    ),
    annotations=LOCAL_WRITE,
)
def record_application_result(
    session_id: str,
    status: str,
    note: str = "",
    verified_success: bool | None = None,
    submitted_by: str = "",
) -> dict[str, Any]:
    return autoapply.log_outcome(
        session_id,
        status=status,
        note=note,
        verified_success=verified_success,
        submitted_by=submitted_by,
    )


@mcp.tool(
    title="Update job tracking",
    description="Update local Resume Studio tracking fields for a saved job. This does not contact or apply to an employer.",
    annotations=LOCAL_WRITE,
)
def update_job_tracking(
    job_key: str,
    status: str = "",
    priority_level: str = "",
    repeatable: bool | None = None,
    irrelevant: bool | None = None,
) -> dict[str, Any]:
    job = store.get_job(job_key)
    if job is None:
        raise ValueError(f"No job found for key {job_key!r}.")
    if status:
        job = store.update_status(job_key, status) or job
    if priority_level:
        job = store.set_priority_override(job_key, priority_level) or job
    if repeatable is not None:
        job = store.set_repeatable(job_key, repeatable) or job
    if irrelevant is not None:
        job = store.set_irrelevant(job_key, irrelevant) or job
    return _job_summary(job)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Resume Studio MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    mcp.settings.port = args.port
    mcp.settings.host = args.host
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
