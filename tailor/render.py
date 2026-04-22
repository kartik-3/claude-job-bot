import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_RESUME_CSS = """\
body { font-family: Georgia, serif; max-width: 860px; margin: 40px auto; padding: 0 24px; color: #111; line-height: 1.5; }
h1 { font-size: 1.8em; margin-bottom: 2px; }
h2 { font-size: 1.1em; border-bottom: 1px solid #ccc; padding-bottom: 3px; margin-top: 20px; text-transform: uppercase; letter-spacing: .05em; }
h3 { font-size: 1em; margin-bottom: 2px; }
p, li { font-size: 0.95em; margin: 3px 0; }
ul { margin: 4px 0 8px 18px; padding: 0; }
strong { font-weight: 600; }
"""


def _html_document(body_html: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        f"<style>{_RESUME_CSS}</style>"
        f"</head><body>{body_html}</body></html>"
    )


def _try_pandoc(markdown_text: str, output_path: Path) -> bool:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return False
    for extra_args in (
        ["--pdf-engine=xelatex"],
        ["--pdf-engine=pdflatex"],
        [],
    ):
        try:
            result = subprocess.run(
                [pandoc, "-", "--standalone", "-o", str(output_path),
                 "-V", "geometry:margin=1in", *extra_args],
                input=markdown_text.encode(),
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.debug("pandoc rendered PDF: %s", output_path)
                return True
            logger.debug("pandoc attempt failed: %s", result.stderr.decode()[:200])
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("pandoc error: %s", exc)
    return False


def _try_weasyprint(markdown_text: str, output_path: Path) -> bool:
    try:
        import markdown as md_lib
        import weasyprint

        html = _html_document(md_lib.markdown(markdown_text, extensions=["extra"]))
        weasyprint.HTML(string=html).write_pdf(str(output_path))
        logger.debug("weasyprint rendered PDF: %s", output_path)
        return True
    except Exception as exc:
        logger.debug("weasyprint failed: %s", exc)
        return False


def markdown_to_pdf(markdown_text: str, output_path: Path) -> Path:
    """Convert markdown to PDF. Falls back to styled HTML if no renderer is available.

    Install hints:
      PDF via pandoc : brew install pandoc   (also needs a LaTeX distro)
      PDF via pango  : brew install pango    (then weasyprint works)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if _try_pandoc(markdown_text, output_path):
        return output_path

    if _try_weasyprint(markdown_text, output_path):
        return output_path

    # Fallback: styled HTML (user can File → Print → Save as PDF in browser)
    import markdown as md_lib

    html_path = output_path.with_suffix(".html")
    html = _html_document(md_lib.markdown(markdown_text, extensions=["extra"]))
    html_path.write_text(html, encoding="utf-8")
    logger.warning(
        "No PDF renderer found — saved as HTML instead: %s\n"
        "  Enable PDF output with: brew install pandoc  "
        "OR  brew install pango",
        html_path,
    )
    return html_path
