#!/usr/bin/env python3
"""Job application bot CLI."""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def cmd_discover(args: argparse.Namespace) -> None:
    import yaml
    from db import init_db, upsert_job
    from scrapers import get_scraper
    from scrapers.base import Company

    init_db()

    sources_path = Path("sources.yaml")
    companies = [Company(**c) for c in yaml.safe_load(sources_path.read_text())]

    total_new = 0
    for company in companies:
        scraper = get_scraper(company.ats)
        if scraper is None:
            logging.warning("No scraper for ATS '%s' (company: %s) — skipping", company.ats, company.name)
            continue
        try:
            jobs = scraper.fetch_jobs(company)
        except Exception as exc:
            logging.error("Failed to fetch jobs for %s: %s", company.name, exc)
            continue

        new_count = sum(upsert_job(job.model_dump()) for job in jobs)
        logging.info("%s: %d jobs fetched, %d new", company.name, len(jobs), new_count)
        total_new += new_count

    print(f"Discovery complete — {total_new} new jobs added")


def cmd_evaluate(args: argparse.Namespace) -> None:
    from db import init_db
    from evaluator.evaluate import load_preferences, run_evaluation

    init_db()

    prefs_path = Path("profile/preferences.yaml")
    resume_path = Path("profile/resume.md")

    if not prefs_path.exists():
        logging.error("Missing %s — copy from profile_templates/preferences.yaml", prefs_path)
        sys.exit(1)
    if not resume_path.exists():
        logging.error("Missing %s — copy from profile_templates/resume.md", resume_path)
        sys.exit(1)

    prefs = load_preferences(prefs_path)
    resume = resume_path.read_text()

    evaluated, should_apply, skipped = run_evaluation(prefs, resume)
    print(f"Evaluated {evaluated} jobs — {should_apply} to apply, {skipped} skipped")


def cmd_tailor(args: argparse.Namespace) -> None:
    from db import init_db
    from tailor.tailor import run_tailoring

    init_db()

    resume_path = Path("profile/resume.md")
    template_path = Path("profile_templates/cover_letter_template.md")
    output_dir = Path("outputs")

    if not resume_path.exists():
        logging.error("Missing %s — copy from profile_templates/resume.md", resume_path)
        sys.exit(1)

    resume_md = resume_path.read_text()
    template_md = template_path.read_text()

    tailored, failed = run_tailoring(
        resume_md, template_md, output_dir, review=args.review
    )
    print(f"Tailored {tailored} jobs — {failed} failed")


def cmd_apply(args: argparse.Namespace) -> None:
    from db import init_db
    from applier import run_apply

    init_db()

    field_answers_path = Path("profile/field_answers.yaml")
    outputs_dir = Path("outputs")

    if not field_answers_path.exists():
        logging.error(
            "Missing %s — copy from profile_templates/field_answers.yaml",
            field_answers_path,
        )
        sys.exit(1)

    dry_run = not args.submit
    if not dry_run:
        confirm = input("About to submit real applications. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    applied, dry_run_count, manual = run_apply(
        field_answers_path=field_answers_path,
        outputs_dir=outputs_dir,
        ats_filter=args.ats,
        dry_run=dry_run,
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[{mode}] Applied: {applied} | Dry-run complete: {dry_run_count} | Needs manual: {manual}")


def cmd_status(args: argparse.Namespace) -> None:
    from db import count_jobs, init_db

    init_db()
    total = count_jobs()
    print(f"{total} jobs in database")

    if total > 0:
        from db import STATUSES

        for status in STATUSES:
            n = count_jobs(status)
            if n:
                print(f"  {status}: {n}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-bot",
        description="Discover, evaluate, tailor, and apply to jobs.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="Pull new jobs from ATS sources into the DB")

    sub.add_parser("evaluate", help="Score new jobs against resume")

    tailor_p = sub.add_parser("tailor", help="Generate tailored resume PDFs for good-fit jobs")
    tailor_p.add_argument(
        "--review",
        action="store_true",
        help="Pause for manual approval before saving each tailored resume and cover letter",
    )

    apply_p = sub.add_parser("apply", help="Auto-apply to tailored jobs")
    apply_p.add_argument(
        "--submit",
        action="store_true",
        help="Actually submit (default: dry-run only)",
    )
    apply_p.add_argument("--ats", default=None, help="Limit to one ATS platform")

    sub.add_parser("status", help="Show counts by status")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format="%(levelname)s %(message)s", level=level)

    commands = {
        "discover": cmd_discover,
        "evaluate": cmd_evaluate,
        "tailor": cmd_tailor,
        "apply": cmd_apply,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
