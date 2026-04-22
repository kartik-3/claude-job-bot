"""Tests for Phase 3 tailoring — slugify, render path logic, word count.
No live API calls.
"""
from pathlib import Path

import pytest

from tailor.tailor import _count_words, slugify


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_text, expected", [
    ("Goldman Sachs", "goldman-sachs"),
    ("JP Morgan", "jp-morgan"),
    ("Software Engineer II", "software-engineer-ii"),
    ("Palo Alto Networks", "palo-alto-networks"),
    ("  Leading spaces  ", "leading-spaces"),
    ("multiple---dashes", "multiple-dashes"),
    ("Special! @#Chars$", "special-chars"),
    ("UPPERCASE", "uppercase"),
    ("already-slug", "already-slug"),
])
def test_slugify(input_text, expected):
    assert slugify(input_text) == expected


def test_slugify_company_role_combo():
    company = slugify("Walmart Global Tech")
    role = slugify("Senior Software Engineer")
    job_slug = f"{company}-{role}"
    assert job_slug == "walmart-global-tech-senior-software-engineer"
    assert " " not in job_slug
    assert job_slug == job_slug.lower()


# ---------------------------------------------------------------------------
# _count_words
# ---------------------------------------------------------------------------

def test_count_words_basic():
    assert _count_words("hello world") == 2


def test_count_words_cover_letter():
    # Typical cover letter should be under 300 words
    sample = """
    Dear Hiring Team,

    I'm writing to express my interest in the Software Engineer role at Acme Corp.
    The engineering challenges described in the job posting align well with my background
    in backend systems and data pipelines.

    In my current role at Goldman Sachs, I've built end-to-end ETL systems in Java on
    AWS Glue aggregating data from five upstream systems, processing millions of records
    in Snowflake with Spark optimizations.

    I hold an MS in Computer Science from SUNY Buffalo and would welcome the opportunity
    to discuss how my background could contribute to your team.

    Thank you for your consideration.
    Sincerely,
    Kartik Sehgal
    """
    assert _count_words(sample) < 300


# ---------------------------------------------------------------------------
# render path logic
# ---------------------------------------------------------------------------

def test_markdown_to_pdf_falls_back_to_html(tmp_path):
    """When no PDF renderer is available, a .html file is saved instead."""
    from unittest.mock import patch
    from tailor.render import markdown_to_pdf

    output_pdf = tmp_path / "resume.pdf"

    # Force both renderers to fail
    with patch("tailor.render._try_pandoc", return_value=False), \
         patch("tailor.render._try_weasyprint", return_value=False):
        result = markdown_to_pdf("# Hello\n\nWorld", output_pdf)

    assert result.suffix == ".html"
    assert result.exists()
    assert "Hello" in result.read_text()


def test_markdown_to_pdf_uses_pandoc_when_available(tmp_path):
    """When pandoc succeeds, return the .pdf path."""
    from unittest.mock import patch
    from tailor.render import markdown_to_pdf

    output_pdf = tmp_path / "resume.pdf"
    output_pdf.write_bytes(b"%PDF fake")  # simulate pandoc writing a file

    with patch("tailor.render._try_pandoc", return_value=True):
        result = markdown_to_pdf("# Hello", output_pdf)

    assert result == output_pdf


def test_markdown_to_pdf_creates_parent_dirs(tmp_path):
    """Output directory is created automatically."""
    from unittest.mock import patch
    from tailor.render import markdown_to_pdf

    deep_path = tmp_path / "a" / "b" / "c" / "resume.pdf"

    with patch("tailor.render._try_pandoc", return_value=False), \
         patch("tailor.render._try_weasyprint", return_value=False):
        result = markdown_to_pdf("# Test", deep_path)

    assert result.parent.exists()


# ---------------------------------------------------------------------------
# _write_diff
# ---------------------------------------------------------------------------

def test_write_diff_captures_changes(tmp_path):
    from tailor.tailor import _write_diff

    original = "# Resume\n\n- Bullet A\n- Bullet B\n"
    tailored = "# Resume\n\n- Bullet B\n- Bullet A (reordered)\n"
    diff_path = tmp_path / "test.diff"

    _write_diff(original, tailored, diff_path)

    content = diff_path.read_text()
    assert "--- resume.md (original)" in content
    assert "+++ resume.md (tailored)" in content
    assert "-" in content  # removed lines
    assert "+" in content  # added lines


def test_write_diff_no_changes(tmp_path):
    from tailor.tailor import _write_diff

    text = "# Resume\n\nNo changes here.\n"
    diff_path = tmp_path / "nodiff.diff"

    _write_diff(text, text, diff_path)

    assert diff_path.read_text() == "(no changes)\n"


def test_write_diff_creates_parent_dirs(tmp_path):
    from tailor.tailor import _write_diff

    diff_path = tmp_path / "a" / "b" / "resume.diff"
    _write_diff("old", "new", diff_path)
    assert diff_path.exists()


# ---------------------------------------------------------------------------
# Prompt formatting — no empty placeholders
# ---------------------------------------------------------------------------

def test_resume_tailor_prompt_has_no_unfilled_placeholders():
    from tailor.prompts import RESUME_TAILOR_PROMPT
    filled = RESUME_TAILOR_PROMPT.format(
        resume="dummy resume",
        job_description="dummy JD",
    )
    assert "{resume}" not in filled
    assert "{job_description}" not in filled


def test_cover_letter_prompt_has_no_unfilled_placeholders():
    from tailor.prompts import COVER_LETTER_PROMPT
    filled = COVER_LETTER_PROMPT.format(
        template="dummy template",
        resume="dummy resume",
        job_description="dummy JD",
        company_name="Acme",
        role_title="SWE",
    )
    assert "{template}" not in filled
    assert "{resume}" not in filled
    assert "{company_name}" not in filled
    assert "{role_title}" not in filled
