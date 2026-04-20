from pydantic import BaseModel


class EvaluationResult(BaseModel):
    fit_score: int
    matched_requirements: list[str]
    missing_requirements: list[str]
    strengths_for_role: list[str]
    concerns: list[str]
    should_apply: bool
    reasoning: str


def evaluate_job(resume: str, job_description: str) -> EvaluationResult:
    # Phase 2
    raise NotImplementedError
