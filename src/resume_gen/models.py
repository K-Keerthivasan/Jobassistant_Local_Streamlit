"""Pydantic models. The Resume model mirrors the exact output SCHEMA the LLM is
told to return, so we can validate the model's JSON before rendering anything."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


# --------------------------------------------------------------------------- #
# Resume (matches the prompt SCHEMA exactly)
# --------------------------------------------------------------------------- #
class Link(BaseModel):
    label: str
    url: str


class Contact(BaseModel):
    email: str
    phone: str
    location: str
    links: list[Link] = Field(default_factory=list)


class ExperienceItem(BaseModel):
    company: str
    role: str
    location: str = ""
    start: str
    end: str
    # Display override for irregular spans (e.g. two separate stints). Set by the
    # truth-guard from the profile, never by the model.
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str
    credential: str
    year: str


class Resume(BaseModel):
    """One valid JSON object the generator returns, per the prompt SCHEMA."""

    fullName: str
    # The target job title, printed right-aligned beside the name. The truth-guard
    # sets it from the posting title, so whatever the model returns is replaced.
    headline: str = Field(
        default="",
        description="The target job title exactly as posted.",
    )
    contact: Contact
    # Legacy paragraph summary. New resumes use `summaryPoints`; older stored runs
    # still render their paragraph.
    summary: str = ""
    # Career summary as 3 short bullets (the current resume format).
    summaryPoints: list[str] = Field(default_factory=list)
    # Empty when the posting does not call for a skills section (the default for
    # non-technical roles); the renderer then omits the section.
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    # JD keywords intentionally reflected, for QA.
    keywordsMatched: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cover letter + application email (separate, smaller schemas)
# --------------------------------------------------------------------------- #
class CoverLetter(BaseModel):
    fullName: str
    contactLine: str = Field(
        description="single line: preferred name | location | email | phone | links"
    )
    greeting: str = Field(description="e.g. 'Dear Hiring Team,'")
    body: list[str] = Field(description="ordered paragraphs, no greeting/sign-off")
    signOff: str = Field(default="Best regards,")
    signature: str


class ApplicationDraft(BaseModel):
    """Fast-path response: one model call produces both long-form artifacts."""

    resume: Resume
    # Agents often mirror the camelCase used everywhere else in the schema.
    cover_letter: CoverLetter = Field(
        validation_alias=AliasChoices("cover_letter", "coverLetter")
    )


class ApplicationEmail(BaseModel):
    subject: str
    body: str = Field(description="plain-text email body, ready to send")


class EmailHook(BaseModel):
    """The two dynamic lines injected into the application email template:
    a role-appropriate opening line and one concrete fit line."""

    opener: str = ""
    hook: str = ""


class FollowupNote(BaseModel):
    """One fresh 'new value proposition' line for a follow-up message."""

    value: str = ""


class ScreeningAnswer(BaseModel):
    """A first-person answer to one application screening question."""

    answer: str


class NumberedAnswer(BaseModel):
    """One answer in a batch, keyed to its question's number."""

    id: int
    answer: str


class ScreeningAnswers(BaseModel):
    """Answers to several screening questions, returned from one model call."""

    answers: list[NumberedAnswer]


class JobExtract(BaseModel):
    """A job posting parsed out of a job-alert email (or pasted text)."""

    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""
    apply_url: str = ""
    contact_email: str = ""


# --------------------------------------------------------------------------- #
# The target job an application is generated against
# --------------------------------------------------------------------------- #
class TargetRole(BaseModel):
    company: str
    title: str
    description: str
    location: str = ""
    apply_url: str = ""
    contact_email: str = ""
