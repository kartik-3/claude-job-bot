import difflib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from .prompts import (
    COVER_LETTER_PROMPT,
    COVER_LETTER_SYSTEM_PROMPT,
    RESUME_SYSTEM_PROMPT,
    RESUME_TAILOR_PROMPT,
)
from .render import markdown_to_pdf

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


def _call_llm(system: str, user_msg: str, max_tokens: int = 2048) -> str | None:
    """Call Claude. Uses Anthropic API if ANTHROPIC_API_KEY is set, otherwise falls
    back to the `claude` CLI (already authenticated via Claude Code)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            response = client.messages.create(
                model=_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Anthropic API call failed: %s", exc)
            return None

    # No API key — use the claude CLI (Claude Code's managed auth)
    full_prompt = f"{system}\n\n---\n\n{user_msg}"
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("claude CLI non-zero exit: %s", result.stderr[:200])
    except FileNotFoundError:
        logger.error("No LLM available: set ANTHROPIC_API_KEY or install the claude CLI")
    except subprocess.TimeoutExpired:
        logger.error("claude CLI timed out")
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert a string to a lowercase kebab-case slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _count_words(text: str) -> int:
    return len(text.split())


def _write_diff(original: str, tailored: str, diff_path: Path) -> None:
    """Write a unified diff between the original and tailored resume markdown."""
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        tailored.splitlines(keepends=True),
        fromfile="resume.md (original)",
        tofile="resume.md (tailored)",
    ))
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("".join(diff_lines) if diff_lines else "(no changes)\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Claude calls
# ---------------------------------------------------------------------------

def _call_claude(system: str, user: str) -> str | None:
    for attempt in range(2):
        result = _call_llm(system, user, max_tokens=2048)
        if result is not None:
            return result.strip()
        if attempt == 0:
            logger.warning("Claude call failed (attempt 1), retrying")
        else:
            logger.error("Claude call failed (attempt 2), skipping")
    return None


def _call_claude_resume(resume_md: str, job_description: str) -> str | None:
    user_msg = RESUME_TAILOR_PROMPT.format(
        resume=resume_md,
        job_description=job_description or "(no description provided)",
    )
    return _call_claude(RESUME_SYSTEM_PROMPT, user_msg)


def _call_claude_cover_letter(
    template_md: str,
    resume_md: str,
    job_description: str,
    company_name: str,
    role_title: str,
) -> str | None:
    user_msg = COVER_LETTER_PROMPT.format(
        template=template_md,
        resume=resume_md,
        job_description=job_description or "(no description provided)",
        company_name=company_name,
        role_title=role_title,
    )
    return _call_claude(COVER_LETTER_SYSTEM_PROMPT, user_msg)


# ---------------------------------------------------------------------------
# Public single-job API
# ---------------------------------------------------------------------------

def tailor_resume(resume_md: str, job_description: str) -> str:
    result = _call_claude_resume(resume_md, job_description)
    if result is None:
        raise RuntimeError("Resume tailoring failed after 2 attempts")
    return result


def tailor_and_save(resume_md: str, job_description: str, output_path: Path) -> Path:
    tailored = tailor_resume(resume_md, job_description)
    return markdown_to_pdf(tailored, output_path)


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
    result = _call_claude_cover_letter(
        template_md, resume_md, job_description, company_name, role_title
    )
    if result is None:
        raise RuntimeError("Cover letter generation failed after 2 attempts")
    return result


def tailor_cover_letter_and_save(
    template_md: str,
    resume_md: str,
    job_description: str,
    company_name: str,
    role_title: str,
    output_path: Path,
) -> Path:
    letter = tailor_cover_letter(
        template_md, resume_md, job_description, company_name, role_title
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(letter, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Review gate
# ---------------------------------------------------------------------------

def _review_and_confirm(content: str, label: str) -> bool:
    """Print content and prompt for approval. Auto-approves in non-interactive mode."""
    if not sys.stdin.isatty():
        return True
    sep = "=" * 60
    print(f"\n{sep}\nREVIEW: {label}\n{sep}")
    print(content)
    print(sep)
    return input("Save this? [y/N]: ").strip().lower() == "y"


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_tailoring(
    resume_md: str,
    cover_letter_template_md: str,
    output_dir: Path,
    review: bool = False,
) -> tuple[int, int]:
    """Tailor resume + cover letter for all should_apply jobs.

    Returns (tailored_count, failed_count).
    """
    from db import get_jobs_by_status, update_job_tailored

    jobs = get_jobs_by_status("should_apply")
    if not jobs:
        logger.info("No should_apply jobs to tailor")
        return 0, 0

    tailored_count = failed_count = 0

    for job in jobs:
        company = job["company"]
        title = job["title"]
        job_slug = f"{slugify(company)}-{slugify(title)}"
        jd = job.get("description") or ""

        logger.info("Tailoring: %s — %s", company, title)

        # ── Resume ──────────────────────────────────────────────────────────
        tailored_md = _call_claude_resume(resume_md, jd)
        if tailored_md is None:
            logger.error("Resume tailoring failed for %s — %s", company, title)
            update_job_tailored(job["id"], status="error", notes="resume tailoring failed")
            failed_count += 1
            continue

        diff_path = output_dir / "tailored_resumes" / f"{job_slug}.diff"
        _write_diff(resume_md, tailored_md, diff_path)
        logger.debug("Diff saved: %s", diff_path)

        if review and not _review_and_confirm(tailored_md, f"Resume: {company} — {title}"):
            logger.info("Skipped (rejected in review): %s — %s", company, title)
            continue

        resume_output = output_dir / "tailored_resumes" / f"{job_slug}.pdf"
        actual_resume_path = markdown_to_pdf(tailored_md, resume_output)

        # ── Cover letter ─────────────────────────────────────────────────────
        cover_letter_path: Path | None = None
        cl_md = _call_claude_cover_letter(
            cover_letter_template_md, resume_md, jd, company, title
        )
        if cl_md is None:
            logger.warning("Cover letter generation failed for %s — %s; continuing without it", company, title)
        else:
            word_count = _count_words(cl_md)
            if word_count > 350:
                logger.warning(
                    "Cover letter for %s is %d words (target <300) — saving anyway",
                    company, word_count,
                )
            if review and not _review_and_confirm(cl_md, f"Cover letter: {company} — {title}"):
                cl_md = None

        if cl_md is not None:
            cover_letter_output = output_dir / "cover_letters" / f"{job_slug}.md"
            cover_letter_output.parent.mkdir(parents=True, exist_ok=True)
            cover_letter_output.write_text(cl_md, encoding="utf-8")
            cover_letter_path = cover_letter_output

        # ── DB update ────────────────────────────────────────────────────────
        update_job_tailored(
            job["id"],
            tailored_resume_path=str(actual_resume_path),
            cover_letter_path=str(cover_letter_path) if cover_letter_path else None,
            status="tailored",
        )
        logger.info(
            "Saved: resume=%s diff=%s cover_letter=%s",
            actual_resume_path.name,
            diff_path.name,
            cover_letter_path.name if cover_letter_path else "none",
        )
        tailored_count += 1

    return tailored_count, failed_count
