"""Matrix grading: tier, gap flags and an evidence-traced fit sentence per job."""

from .grader import build_fit_sentence, grade, grade_job  # noqa: F401
from .requirements import extract_requirements  # noqa: F401
from .seniority import check_seniority, find_years  # noqa: F401
