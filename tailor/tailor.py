from pathlib import Path


def tailor_resume(resume_md: str, job_description: str) -> str:
    # Phase 3
    raise NotImplementedError


def tailor_and_save(resume_md: str, job_description: str, output_path: Path) -> Path:
    # Phase 3
    raise NotImplementedError


def tailor_cover_letter(
    template_md: str,
    resume_md: str,
    job_description: str,
    company_name: str,
    role_title: str,
) -> str:
    """Fill cover_letter_template.md with job-specific values derived from the JD.

    Never invents claims not supported by resume_md or job_description.
    Returns populated markdown ready to paste or upload.
    """
    # Phase 3
    raise NotImplementedError


def tailor_cover_letter_and_save(
    template_md: str,
    resume_md: str,
    job_description: str,
    company_name: str,
    role_title: str,
    output_path: Path,
) -> Path:
    # Phase 3
    raise NotImplementedError
