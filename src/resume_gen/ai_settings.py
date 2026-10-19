"""AI controls you can change from the app, and a live map of how AI is used.

The AI Engine view edits a small set of settings at runtime. Changes apply
immediately to the running app and are saved to data/ai_settings.json, which
overrides the matching .env values on the next start. Only the fields listed in
EDITABLE can be changed this way.

`pipeline()` describes, for the current settings, every step of generating an
application: which steps call an AI engine, which engine, and which steps are
plain rules that never use AI.
"""

from __future__ import annotations

import json

from .config import ROOT, settings

_FILE = ROOT / "data" / "ai_settings.json"

# field -> (type, label, help)
EDITABLE: dict[str, tuple[type, str, str]] = {
    "default_engine": (str, "Default engine",
                       "Which engine runs when a request doesn't name one: hermes or ollama."),
    "ollama_model": (str, "Ollama model",
                     "The local model used for Ollama runs and for falling back when Hermes fails."),
    "allow_ollama_fallback": (bool, "Fall back to Ollama when Hermes fails",
                              "On: a failed Hermes call is retried on Ollama so the run completes. "
                              "Off: the Hermes error is shown instead."),
    "hermes_fast_mode": (bool, "Fast mode (one Hermes call per application)",
                         "On: one call writes the resume and cover letter; the resume version is "
                         "picked by keywords and the email uses a template. Off: adds the Hermes "
                         "resume-version pick, the email lines and the truth audit (3 more calls)."),
    "hermes_persona": (bool, "Hermes chooses the resume version",
                       "Only when fast mode is off. Otherwise the version comes from the lane or keywords."),
    "hermes_qa": (bool, "Hermes truth audit",
                  "Only when fast mode is off. A second pass that removes claims not in your "
                  "profile. The rule-based truth guard always runs either way."),
    "llm_timeout": (float, "Timeout per AI call (seconds)",
                    "A call running longer than this is stopped with an error."),
    "record_prompts": (bool, "Record prompts and replies",
                       "Keep a trimmed copy of each prompt and reply in the AI activity log on this machine."),
}

_ENGINES = ("hermes", "ollama")


def _coerce(name: str, value):
    kind = EDITABLE[name][0]
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "no", "off", "")
        return bool(value)
    if kind is float:
        v = float(value)
        if not 10 <= v <= 1800:
            raise ValueError("Timeout must be between 10 and 1800 seconds.")
        return v
    v = str(value).strip()
    if name == "default_engine" and v not in _ENGINES:
        raise ValueError("Default engine must be hermes or ollama.")
    if not v:
        raise ValueError(f"{EDITABLE[name][1]} cannot be empty.")
    return v


def current() -> dict:
    return {
        name: {"value": getattr(settings, name), "label": label, "help": help_, "type": kind.__name__}
        for name, (kind, label, help_) in EDITABLE.items()
    }


def _saved() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_saved() -> None:
    """Load data/ai_settings.json over the .env values. Bad entries are skipped."""
    for name, value in _saved().items():
        if name in EDITABLE:
            try:
                setattr(settings, name, _coerce(name, value))
            except (TypeError, ValueError):
                continue


def update(changes: dict) -> dict:
    """Validate, apply and save. Raises ValueError naming the first bad field."""
    clean = {}
    for name, value in (changes or {}).items():
        if name not in EDITABLE:
            raise ValueError(f"{name} cannot be changed here.")
        clean[name] = _coerce(name, value)
    for name, value in clean.items():
        setattr(settings, name, value)
    saved = _saved()
    saved.update(clean)
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return current()


def pipeline(hermes_up: bool | None = None) -> list[dict]:
    """The steps of one generation under the current settings.

    Each step: name, what it does, `kind` ("ai" or "rules"), the engine an AI
    step uses, and whether it runs at all right now."""
    hermes_default = settings.default_engine == "hermes"
    engine = "Hermes" if hermes_default else "Ollama"
    if hermes_default and hermes_up is False:
        engine = "Ollama (Hermes is down)" if settings.allow_ollama_fallback else "Hermes (down: calls will fail)"
    fast = settings.hermes_fast_mode and hermes_default
    steps = [
        {"name": "Pick the lane and resume version",
         "does": "Matches the job to a lane and one of your resume versions (IT Support, Web Developer and so on).",
         "kind": "ai" if (not fast and settings.hermes_persona and hermes_default) else "rules",
         "engine": engine if (not fast and settings.hermes_persona and hermes_default) else "Keywords and lane mapping",
         "runs": True},
        {"name": "Grade against the skill matrix",
         "does": "Tier A, B or C and the named gaps, from your lane matrix. No AI.",
         "kind": "rules", "engine": "Lane matrix", "runs": True},
        {"name": "Write resume and cover letter",
         "does": "One call with your profile, the posting and the format rules (fast mode); otherwise two calls.",
         "kind": "ai", "engine": engine, "runs": True},
        {"name": "Write email lines",
         "does": "The opener and fit line of the application email.",
         "kind": "rules" if fast else "ai",
         "engine": "Template" if fast else engine, "runs": True},
        {"name": "Truth audit",
         "does": "Re-reads every resume claim against your profile and removes unsupported ones.",
         "kind": "ai", "engine": "Hermes",
         "runs": bool(not settings.hermes_fast_mode and settings.hermes_qa and hermes_up is not False)},
        {"name": "Truth guard",
         "does": "Resets names, dates, titles, education and skills to your profile; strips invented numbers. Always runs.",
         "kind": "rules", "engine": "Rules", "runs": True},
        {"name": "Fit to one page",
         "does": "Picks type size and spacing, trims the least relevant bullets only if needed.",
         "kind": "rules", "engine": "Length fitter", "runs": True},
        {"name": "Render DOCX and PDF",
         "does": f"Word document, then PDF through {settings.pdf_engine}.",
         "kind": "rules", "engine": "Renderer", "runs": True},
    ]
    return steps


def apply_pipeline() -> list[dict]:
    """What happens on a job site in the Chrome workspace, and where AI helps."""
    return [
        {"name": "Open the posting and find the form",
         "does": "Follows the posting's own Apply link. When a page offers several Apply/Next "
                 "controls, Hermes picks one from that list only; otherwise fixed rules pick it.",
         "kind": "ai", "engine": "Hermes, only when there is a choice", "runs": True},
        {"name": "Fill confirmed answers",
         "does": "Your profile and saved answers only, matched to exact labels. No AI, no guessing.",
         "kind": "rules", "engine": "Saved answers", "runs": True},
        {"name": "Draft written answers",
         "does": "'Why this job' style questions are drafted from your resume evidence, then a "
                 "second Hermes pass rejects the draft if any claim isn't backed by that evidence.",
         "kind": "ai", "engine": "Hermes (draft, then check)", "runs": True},
        {"name": "Attach resume and cover letter",
         "does": "Uploads the exact generated files and checks the site shows them attached.",
         "kind": "rules", "engine": "File checks", "runs": True},
        {"name": "Stop for you",
         "does": "Login, CAPTCHA, consent, demographics, missing facts and the final Submit "
                 "click are always yours. AI never answers these.",
         "kind": "rules", "engine": "You", "runs": True},
    ]
