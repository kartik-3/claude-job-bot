# CLAUDE.md

See PLAN.md for architecture. Read it at phase start only.

## Code
- Python 3.11+, PEP8, ruff format
- Type hints on all signatures
- Pydantic v2 for all structured data (LLM responses, config, DB rows)
- `pathlib.Path` for all paths
- `logging` not `print`; level via `--verbose`
- YAML for human config, `.env` for secrets

## Tests
- pytest in `tests/`
- Test: scraper parsing (fixtures, no live calls), evaluator schema, field matcher, DB dedupe
- Skip Playwright unit tests; use dry-runs instead

## Git
- Branch per phase: `phase-N-name`
- Commit format: `phase-N: imperative summary`
- Verify no `profile/`, `db/`, `outputs/`, `.env` staged before every commit
- No direct pushes to `main`

## Hard Security Rules (non-negotiable)
- `profile/` is gitignored — never commit it
- Never commit `.env`
- Never log resume content, API keys, or field_answers values
- Resume goes only to: Anthropic API, the specific ATS form being applied to
- No credential/cookie/session storage for any job site
- CAPTCHA encountered → `status=needs_manual`, move on

## Auto-Apply Rules
- Required field can't be mapped → abort, log to `outputs/unknowns.yaml`, `status=needs_manual`
- `apply` defaults to `--dry-run`; real submission requires `--submit`
- Screenshot pre- and post-submit → `outputs/screenshots/`
- Max 1 live submission per 30s; no parallelism
- Log every field decision: `(label, matched_key, value_source)`
- Never estimate/guess on a required field

## LLM Calls
- Default model: `claude-sonnet-4-5`
- Always request JSON; validate with Pydantic; retry once on parse fail; skip on second fail
- Prompts in `prompts.py` per module, never inline strings
- LLM sets `should_apply` in DB only; it never triggers submission directly

## Dependencies
- Ask before adding; pin versions with comment explaining why

## Workflow
- Read files before editing; check for existing logic before adding
- For non-trivial changes: describe plan, wait for confirmation, then edit
- Flag unrelated issues; don't silently fix them
- Update PLAN.md if scope changes

## Non-Goals (push back if asked)
- LinkedIn/Indeed/Glassdoor scraping
- Auth bypass, CAPTCHA solving, credential storage
- Custom scrapers for Apple/Google/Meta/Netflix career pages
→ Alternative: manual queue