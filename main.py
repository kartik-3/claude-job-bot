#!/usr/bin/env python3
"""Job application bot CLI."""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def cmd_detect(args: argparse.Namespace) -> None:
    """Test each company in sources.yaml and report whether its ATS config is reachable.
    For 404 companies, tries common slug/ATS variations to suggest a fix.
    """
    import requests
    import yaml
    from scrapers.base import Company

    sources_path = Path("sources.yaml")
    if not sources_path.exists():
        logging.error("sources.yaml not found")
        sys.exit(1)

    companies = [Company(**c) for c in yaml.safe_load(sources_path.read_text())]
    if args.company:
        companies = [c for c in companies if args.company.lower() in c.name.lower()]

    GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    LEVER      = "https://api.lever.co/v0/postings/{slug}"
    ASHBY      = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def probe(url: str) -> bool:
        try:
            r = requests.get(url, timeout=10)
            return r.ok
        except Exception:
            return False

    def slug_variants(name: str, current: str | None) -> list[str]:
        bare    = name.lower().replace(" ", "").replace("-", "").replace(".", "")
        hyphen  = name.lower().replace(" ", "-").replace(".", "")
        seen, out = set(), []
        for s in [current or "", bare, hyphen, name.lower()]:
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    SKIP_ATS = {"workday", "custom"}
    results = []

    for co in companies:
        if co.ats in SKIP_ATS:
            results.append((co.name, co.ats, co.slug, "skip", None))
            continue

        # Check if current config is live
        templates = {"greenhouse": GREENHOUSE, "lever": LEVER, "ashby": ASHBY}
        tmpl = templates.get(co.ats)
        current_ok = tmpl and co.slug and probe(tmpl.format(slug=co.slug))

        if current_ok:
            results.append((co.name, co.ats, co.slug, "ok", None))
            continue

        # Try all ATS × slug variations to find what works
        found = []
        for slug in slug_variants(co.name, co.slug):
            for ats, tmpl in templates.items():
                if probe(tmpl.format(slug=slug)):
                    found.append((ats, slug))
        results.append((co.name, co.ats, co.slug, "fail", found))

    # --- Print report ---
    ok = [r for r in results if r[3] == "ok"]
    fail = [r for r in results if r[3] == "fail"]
    skip = [r for r in results if r[3] == "skip"]

    print(f"\n{'='*60}")
    print(f"ATS Detection Report — {len(companies)} companies checked")
    print(f"{'='*60}")
    print(f"  Working : {len(ok)}")
    print(f"  Broken  : {len(fail)}")
    print(f"  Skipped : {len(skip)}  (workday/custom — need manual slug)\n")

    if fail:
        print("BROKEN — update your sources.yaml:")
        for name, ats, slug, _, found in fail:
            current = f"{ats}/{slug}" if slug else ats
            if found:
                suggestions = "  OR  ".join(f"{a}/{s}" for a, s in found)
                print(f"  {name:<30}  currently: {current}")
                print(f"  {'':30}  suggest  : {suggestions}")
            else:
                print(f"  {name:<30}  currently: {current}  → no match found (may be workday/custom)")

    if skip:
        print("\nSKIPPED (workday/custom) — add correct slug to sources.yaml:")
        print("  See scrapers/workday.py for instructions on finding Workday slugs.")
        for name, ats, slug, _, _ in skip:
            slug_str = f"  slug: {slug}" if slug else "  slug: ??? (needs to be set)"
            print(f"  {name:<30}  {ats}{slug_str}")

    if ok:
        print(f"\nWORKING ({len(ok)} companies):")
        for name, ats, slug, _, _ in ok:
            print(f"  {name:<30}  {ats}/{slug}")


def _fix_workday_urls(company_name: str, host: str, site: str) -> int:
    """Fix existing DB records that are missing /{site}/ in their Workday URL.
    Returns the number of rows updated."""
    from db import get_connection
    from scrapers.base import make_job_id

    broken_prefix = f"https://{host}/job/"
    correct_prefix = f"https://{host}/{site}/job/"

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, company, title, url FROM jobs WHERE ats='workday' AND company=? AND url LIKE ?",
            (company_name, f"https://{host}/job/%"),
        ).fetchall()
        for row in rows:
            new_url = row["url"].replace(broken_prefix, correct_prefix, 1)
            new_id = make_job_id(row["company"], row["title"], new_url)
            conn.execute(
                "UPDATE jobs SET id=?, url=?, apply_url=? WHERE id=?",
                (new_id, new_url, new_url, row["id"]),
            )
    return len(rows)


def _apply_filter(job: dict, prefs) -> tuple[bool, str]:
    """Run hard_gate + keyword_matches. Returns (passes, reason)."""
    from evaluator.filters import hard_gate, keyword_matches
    passes, reason = hard_gate(job, prefs)
    if not passes:
        return False, reason
    if not keyword_matches(job.get("description"), prefs):
        return False, "no tech keywords in description"
    return True, ""


def cmd_discover(args: argparse.Namespace) -> None:
    import json
    import yaml
    from db import get_jobs_by_status, init_db, update_job_evaluation, upsert_job
    from evaluator.evaluate import load_preferences
    from scrapers import get_scraper
    from scrapers.base import Company

    init_db()

    prefs_path = Path("profile/preferences.yaml")
    prefs = None
    if prefs_path.exists():
        prefs = load_preferences(prefs_path)
        logging.info(
            "Preferences loaded — %d target roles, locations: %s, remote_ok: %s",
            len(prefs.target_roles),
            prefs.locations,
            prefs.remote_ok,
        )
    else:
        logging.warning("profile/preferences.yaml not found — storing all jobs without filtering")

    sources_path = Path("sources.yaml")
    companies = [Company(**c) for c in yaml.safe_load(sources_path.read_text())]

    total_new = total_filtered = 0
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

        kept = filtered = 0
        for job in jobs:
            if prefs is not None:
                passes, reason = _apply_filter(job.model_dump(), prefs)
                if not passes:
                    logging.info("  skip  %s — %s [%s]", company.name, job.title, reason)
                    filtered += 1
                    continue
            if upsert_job(job.model_dump()):
                kept += 1

        total_new += kept
        total_filtered += filtered
        logging.info(
            "%s: %d fetched, %d new, %d filtered",
            company.name, len(jobs), kept, filtered,
        )

        # One-time URL fix for Workday jobs stored before the /{site}/ bug was fixed.
        if company.ats == "workday" and company.slug and "/" in company.slug:
            host_part, site = company.slug.split("/", 1)
            host = f"{host_part}.myworkdayjobs.com"
            fixed = _fix_workday_urls(company.name, host, site)
            if fixed:
                logging.info("%s: fixed %d broken Workday URLs", company.name, fixed)

    # Retroactively filter any status=new jobs already in the DB that no longer
    # match preferences (e.g. from runs before this feature existed, or after
    # preferences were tightened).
    retro_filtered = 0
    if prefs is not None:
        for job in get_jobs_by_status("new"):
            passes, reason = _apply_filter(job, prefs)
            if not passes:
                logging.info(
                    "  retro-filter  %s — %s [%s]",
                    job["company"], job["title"], reason,
                )
                update_job_evaluation(
                    job["id"],
                    fit_score=0,
                    status="should_not_apply",
                    evaluation_json=json.dumps({"hard_gate_reason": reason}),
                    notes=f"filtered at discover: {reason}",
                )
                retro_filtered += 1

    total_filtered += retro_filtered
    summary = f"Discovery complete — {total_new} new jobs added"
    if prefs is not None:
        summary += f", {total_filtered} filtered by preferences"
        if retro_filtered:
            summary += f" ({retro_filtered} retroactively from existing new jobs)"
    print(summary)


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


def cmd_report(args: argparse.Namespace) -> None:
    import csv as csv_mod

    from db import get_evaluated_jobs, init_db

    init_db()

    jobs = get_evaluated_jobs(status_filter=args.status or None)
    if not jobs:
        print("No evaluated jobs found.")
        return

    if args.output:
        out_path = Path(args.output)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv_mod.DictWriter(f, fieldnames=["score", "status", "company", "title", "url", "notes"])
            writer.writeheader()
            for job in jobs:
                writer.writerow({
                    "score":   job["fit_score"] if job["fit_score"] is not None else "",
                    "status":  job["status"] or "",
                    "company": job["company"] or "",
                    "title":   job["title"] or "",
                    "url":     job["apply_url"] or job["url"] or "",
                    "notes":   job["notes"] or "",
                })
        print(f"Saved {len(jobs)} jobs to {out_path}")
        return

    # Terminal table
    W_SCORE  = 6
    W_STATUS = 16
    W_CO     = 20
    W_TITLE  = 40

    header = (
        f"{'Score':>{W_SCORE}}  "
        f"{'Status':<{W_STATUS}}  "
        f"{'Company':<{W_CO}}  "
        f"{'Title':<{W_TITLE}}  "
        f"URL"
    )
    print(header)
    print("-" * len(header))

    for job in jobs:
        score = job["fit_score"]
        score_str = f"{score:>5}" if score is not None else "    -"
        status = (job["status"] or "")[:W_STATUS]
        company = (job["company"] or "")[:W_CO]
        title   = (job["title"]   or "")[:W_TITLE]
        url     = job["apply_url"] or job["url"] or ""
        print(
            f"{score_str}  "
            f"{status:<{W_STATUS}}  "
            f"{company:<{W_CO}}  "
            f"{title:<{W_TITLE}}  "
            f"{url}"
        )

    print(f"\n{len(jobs)} jobs listed.")


def cmd_status(args: argparse.Namespace) -> None:
    from db import count_jobs, get_company_stats, init_db

    init_db()
    total = count_jobs()
    print(f"{total} jobs in database")

    if total > 0:
        from db import STATUSES

        for status in STATUSES:
            n = count_jobs(status)
            if n:
                print(f"  {status}: {n}")

    if getattr(args, "companies", False):
        stats = get_company_stats()
        if not stats:
            return
        print(f"\n{len(stats)} companies scraped:\n")
        W_CO  = max(len(s["company"]) for s in stats)
        W_ATS = max(len(s["ats"])     for s in stats)
        header = f"  {'Company':<{W_CO}}  {'ATS':<{W_ATS}}  {'Total':>5}  {'Apply':>5}  {'Reject':>6}  {'Pending':>7}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for s in stats:
            print(
                f"  {s['company']:<{W_CO}}  {s['ats']:<{W_ATS}}"
                f"  {s['total']:>5}  {s['to_apply']:>5}  {s['rejected']:>6}  {s['pending']:>7}"
            )


def cmd_clear(args: argparse.Namespace) -> None:
    from db import count_jobs, get_connection, init_db

    init_db()
    total = count_jobs()
    if total == 0:
        print("Database is already empty.")
        return

    print(f"This will permanently delete all {total} jobs from the database.")
    confirm = input("Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    with get_connection() as conn:
        conn.execute("DELETE FROM jobs")
    print(f"Deleted {total} jobs.")


def cmd_serve(args: argparse.Namespace) -> None:
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

    from db import init_db
    init_db()

    from django.core.management import execute_from_command_line
    addr = f"{args.host}:{args.port}"
    print(f"API running at http://{addr}/api/jobs/")
    print(f"Start the React frontend: cd dashboard/frontend && npm install && npm run dev")
    execute_from_command_line(["manage.py", "runserver", addr, "--noreload"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-bot",
        description="Discover, evaluate, tailor, and apply to jobs.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    detect_p = sub.add_parser("detect", help="Test ATS configs in sources.yaml and suggest fixes for broken ones")
    detect_p.add_argument("--company", default=None, metavar="NAME",
                          help="Test only companies whose name contains this string")

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

    status_p = sub.add_parser("status", help="Show counts by status")
    status_p.add_argument(
        "--companies",
        action="store_true",
        help="Also show a per-company breakdown of jobs scraped",
    )

    sub.add_parser("clear", help="Delete all jobs from the database (prompts for confirmation)")

    serve_p = sub.add_parser("serve", help="Start the Django API server for the dashboard")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", default=8000, type=int, help="Bind port (default: 8000)")

    report_p = sub.add_parser("report", help="Show evaluated jobs ranked by fit score")
    report_p.add_argument(
        "--status",
        default=None,
        help="Filter by status (e.g. should_apply, should_not_apply, tailored)",
    )
    report_p.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Save as CSV instead of printing (e.g. --output results.csv)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format="%(levelname)s %(message)s", level=level)

    commands = {
        "detect": cmd_detect,
        "discover": cmd_discover,
        "evaluate": cmd_evaluate,
        "tailor": cmd_tailor,
        "apply": cmd_apply,
        "clear": cmd_clear,
        "serve": cmd_serve,
        "status": cmd_status,
        "report": cmd_report,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
