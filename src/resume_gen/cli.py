"""Command-line interface.

Examples:
  python -m resume_gen.cli check
  python -m resume_gen.cli generate --job data/jobs/opg.json
  python -m resume_gen.cli generate --company "OPG" --title "Junior Full-Stack Developer" \\
      --jd-file data/jobs/opg.txt --no-pdf
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .config import settings
from .llm import ollama_client
from .models import TargetRole
from .pipeline import run
from .profile import load_profile

app = typer.Typer(add_completion=False, help="Automatic Resume Generator")
console = Console()


@app.command()
def check():
    """Health check: Ollama reachable, model present, profile loads."""
    ok = True
    if ollama_client.health():
        console.print(f"[green]\\[ok][/] Ollama reachable at {settings.ollama_host}")
    else:
        console.print(f"[red]\\[!!][/] Ollama NOT reachable at {settings.ollama_host}")
        ok = False
    console.print(f"  model: [cyan]{settings.ollama_model}[/]  temp: {settings.ollama_temperature}")

    try:
        p = load_profile()
        console.print(f"[green]\\[ok][/] Profile loaded: {p.get('full_name')} "
                      f"({len(p.get('experience', []))} roles)")
    except Exception as e:
        console.print(f"[red]\\[!!][/] Profile failed to load: {e}")
        ok = False

    console.print(f"  output dir: {settings.output_dir}")
    raise typer.Exit(0 if ok else 1)


@app.command()
def generate(
    job: Path = typer.Option(None, help="Path to a target_role JSON file."),
    company: str = typer.Option(None),
    title: str = typer.Option(None),
    jd_file: Path = typer.Option(None, help="Path to a plain-text job description."),
    jd: str = typer.Option(None, help="Inline job description text."),
    location: str = typer.Option("", help="Job location."),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Also export PDFs."),
    strict: bool = typer.Option(False, "--strict", help="Strip fabricated metrics, not just flag them."),
    model: str = typer.Option(None, "--model", help="Override OLLAMA_MODEL for this run."),
):
    """Generate resume + cover letter + email for one target role."""
    if job:
        target = TargetRole.model_validate_json(Path(job).read_text(encoding="utf-8"))
    else:
        if not (company and title):
            raise typer.BadParameter("Provide --job FILE, or both --company and --title.")
        description = jd or (Path(jd_file).read_text(encoding="utf-8") if jd_file else "")
        if not description:
            raise typer.BadParameter("Provide a job description via --jd or --jd-file.")
        target = TargetRole(company=company, title=title, description=description, location=location)

    if model:
        settings.ollama_model = model
    console.print(f"Generating for [bold]{target.title}[/] @ [bold]{target.company}[/] "
                  f"using [cyan]{settings.ollama_model}[/] …")
    result = run(target, make_pdf=pdf, strict=strict)

    console.print(f"\n[green]Done.[/] Output: [bold]{result['folder']}[/]")
    for k, v in result["paths"].items():
        tag = "[red]" if k.endswith("error") else "[green]"
        console.print(f"  {tag}{k}[/]: {v}")

    qa = result["qa"]
    if result["qa_has_violations"]:
        console.print("\n[yellow]Truth-guard caught issues (see qa_report.json):[/]")
        for fix in qa["identity_fixed"]:
            console.print(f"  [yellow]identity[/]: {fix}")
        if qa["skills_dropped"]:
            console.print(f"  [yellow]dropped invented skills/certs[/]: {', '.join(qa['skills_dropped'])}")
        for ef in qa.get("experience_fixed", []):
            console.print(f"  [yellow]experience[/] ({ef['company']}): {'; '.join(ef['changes'])}")
        for um in qa.get("unmatched_experience", []):
            console.print(f"  [red]UNMATCHED experience[/]: {um['role']} @ {um['company']} "
                          f"— could not tie to your profile; review manually.")
        for ub in qa.get("ungrounded_in_bullets", []):
            console.print(f"  [red]ungrounded term[/] ({ub['company']}): {', '.join(ub['terms'])} "
                          f"— \"{ub['bullet'][:70]}…\"")
        for fab in qa["fabricated_numbers"]:
            console.print(f"  [yellow]fabricated number[/] ({fab['company']}): "
                          f"{', '.join(fab['numbers'])} — \"{fab['bullet'][:70]}…\"")
        if not strict:
            console.print("  [dim]Re-run with --strict to auto-strip the fabricated metrics.[/]")
    else:
        console.print("\n[green]Truth-guard: no violations.[/]")

    if result["keywordsMatched"]:
        console.print(f"\n[dim]Keywords matched (QA):[/] {', '.join(result['keywordsMatched'])}")


if __name__ == "__main__":
    app()
