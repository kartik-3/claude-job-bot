# Job Application Bot — Build Plan

A personal bot that discovers jobs from target companies, evaluates fit against my resume, tailors resumes for good matches, auto-applies where possible, and queues the rest for manual review.

---

## Guiding Principles

- **Build iteratively.** Each phase ships independently and produces usable value before the next phase starts.
- **Company-first, not board-first.** We pull jobs directly from company ATS platforms (Greenhouse, Lever, Ashby, etc.) via their public APIs, not from LinkedIn/Indeed/Glassdoor.
- **Fail safe on auto-apply.** If the bot isn't 100% sure how to fill a required field, it aborts that application and logs what it didn't know. Better to skip than submit garbage.
- **Never invent experience.** Resume tailoring reorders and rephrases truthful bullets; it never fabricates.
- **Personal data stays local.** Resume, preferences, and form answers are gitignored.

---

## Architecture

```
job-bot/
├── PLAN.md                    # this file
├── CLAUDE.md                  # persistent instructions for Claude Code
├── README.md
├── .gitignore
├── .env                       # ANTHROPIC_API_KEY (gitignored)
├── requirements.txt
├── main.py                    # CLI entrypoint
│
├── profile/                   # ALL GITIGNORED
│   ├── resume.md              # base resume in markdown
│   ├── preferences.yaml       # target roles, locations, salary, remote, visa, seniority
│   ├── field_answers.yaml     # growing Q&A memory for application forms
│   └── cover_letters/         # per-job tailored cover letters
│
├── profile_templates/         # committed templates (copy to profile/ to use)
│   ├── resume.md
│   ├── preferences.yaml
│   ├── field_answers.yaml
│   ├── cover_letter_template.md   # filled per-job by tailor module; use as default
│   └── cover_letter_fallback.md   # fixed short paragraph for low-priority / char-limited forms
│
├── sources.yaml               # companies + ATS type (committed)
│
├── db/
│   └── jobs.sqlite            # gitignored
│
├── scrapers/
│   ├── __init__.py
│   ├── base.py                # shared interface
│   ├── greenhouse.py
│   ├── lever.py
│   ├── ashby.py
│   └── workday.py             # discovery only; auth required to apply
│
├── evaluator/
│   ├── __init__.py
│   ├── prompts.py
│   └── evaluate.py            # scores job vs resume, returns structured JSON
│
├── tailor/
│   ├── __init__.py
│   ├── prompts.py
│   ├── tailor.py              # produces per-job resume
│   └── render.py              # markdown → PDF
│
├── applier/
│   ├── __init__.py
│   ├── base.py                # Playwright session, field detection, screenshots
│   ├── field_matcher.py       # maps form fields to field_answers.yaml via Claude
│   ├── greenhouse.py
│   ├── lever.py
│   └── ashby.py
│
├── outputs/                   # gitignored
│   ├── tailored_resumes/
│   ├── cover_letters/         # generated per-job cover letters
│   ├── application_logs/
│   ├── screenshots/
│   ├── unknowns.yaml          # fields the bot didn't know how to fill
│   └── manual_queue.md        # jobs requiring manual application
│
└── tests/
```

---

## Phase 0 — Project Skeleton

**Goal:** Repo structure, config files, virtual environment, dependencies, database schema. No scraping yet.

**Deliverables:**
- Folder structure above
- `requirements.txt` with: `anthropic`, `playwright`, `pyyaml`, `sqlite-utils`, `requests`, `markdown`, `weasyprint` (or `pypandoc`), `python-dotenv`, `pydantic`, `pytest`
- `main.py` CLI stub with subcommands: `discover`, `evaluate`, `tailor`, `apply`, `status`
- SQLite schema for `jobs` table: `id`, `company`, `title`, `url`, `apply_url`, `ats`, `description`, `location`, `remote`, `posted_at`, `discovered_at`, `fit_score`, `status`, `evaluation_json`, `tailored_resume_path`, `applied_at`, `notes`
  - `status` values: `new`, `evaluated`, `should_apply`, `should_not_apply`, `tailored`, `applied`, `needs_manual`, `blocked`, `error`
- Template files in `profile_templates/` with dummy content
- `.gitignore` covering `profile/`, `db/`, `outputs/`, `.env`, `*.pdf`, `__pycache__/`, `.venv/`

**Done when:** `python main.py status` runs and reports "0 jobs in database".

---

## Phase 1 — Job Discovery

**Goal:** Given `sources.yaml`, pull all current jobs from each company's ATS into SQLite. Dedupe on re-runs.

**ATS endpoints to implement (in this order):**

1. **Greenhouse** — `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
2. **Lever** — `https://api.lever.co/v0/postings/{slug}?mode=json`
3. **Ashby** — `https://api.ashbyhq.com/posting-api/job-board/{slug}`
4. **Workday** *(stretch)* — per-tenant `/wday/cxs/{tenant}/{site}/jobs` search API
5. **SmartRecruiters** *(stretch)* — `https://api.smartrecruiters.com/v1/companies/{slug}/postings`

**Each scraper implements:**
```python
def fetch_jobs(company: Company) -> list[Job]: ...
```
Returns normalized `Job` dicts with the schema above. `apply_url` is the direct application link.

**Dedupe strategy:** Hash `(company, title, canonical_url)` as the primary key. Re-runs update `discovered_at` but don't duplicate.

**Sources file format:**
```yaml
- name: Stripe
  ats: greenhouse
  slug: stripe
- name: Figma
  ats: ashby
  slug: figma
```

**Helper: ATS detector.** A script that takes a company name or careers URL and guesses the ATS. Handy for bulk-populating `sources.yaml`.

**Done when:** `python main.py discover` pulls jobs from 3+ companies across 2+ ATS platforms and stores them with `status=new`.

---

## Phase 2 — Evaluation

**Goal:** For every `status=new` job, score fit against my resume and mark `should_apply` / `should_not_apply`.

**Approach:**
1. Hard-gate filters first (cheap, no LLM): location mismatch, seniority mismatch, explicit non-negotiables from `preferences.yaml`. Fail-fast these with reasons — don't waste tokens.
2. For jobs that pass gates, call Claude API with: base resume + JD + rubric.
3. Require structured JSON output validated with Pydantic:
   ```json
   {
     "fit_score": 0-100,
     "matched_requirements": ["..."],
     "missing_requirements": ["..."],
     "strengths_for_role": ["..."],
     "concerns": ["..."],
     "should_apply": true,
     "reasoning": "2-3 sentences"
   }
   ```
4. Threshold from `preferences.yaml` (default 70). Store full JSON in `evaluation_json`, set `status` and `fit_score`.

**Prompt design notes:**
- System prompt defines rubric and output schema.
- Give the model my non-negotiables so it can auto-reject.
- Instruct it to be calibrated, not optimistic — under-applying to bad fits is fine.

**Done when:** `python main.py evaluate` processes all `new` jobs, each ends up `should_apply` or `should_not_apply` with clear reasoning.

---

## Phase 3 — Resume Tailoring

**Goal:** For each `should_apply` job, produce a tailored resume PDF in `outputs/tailored_resumes/`.

**Rules (enforced in system prompt):**
- Reorder bullets by relevance to the JD.
- Rephrase bullets to echo JD language *only where truthful*.
- Drop bullets that waste space for this role.
- **Never invent skills, titles, employers, dates, or accomplishments.**
- Preserve all factual content (dates, company names, titles).

**Pipeline:**
1. Load `profile/resume.md` + JD.
2. Claude returns tailored resume markdown.
3. Render to PDF via `weasyprint` or `pandoc`.
4. Save to `outputs/tailored_resumes/{company}-{role-slug}.pdf`.
5. Generate cover letter: fill `profile_templates/cover_letter_template.md` with job-specific values from the JD using Claude. Apply tailoring rules:
   - Never invent company-specific claims; use `"the mission of {{company_name}} resonates with me"` if nothing concrete is available from the JD.
   - Bridge sentence must map to real resume content — pull from candidate summary, don't embellish.
   - Drop the optional paragraph when the JD is vague or generic.
   - Keep total length under 300 words.
   - Match tone to company: startup/casual JD → `"Hi team"` / `"Thanks"`; enterprise/finance → keep formal.
   - Never claim "passionate about" unless the resume supports it.
6. Save cover letter to `outputs/cover_letters/{company}-{role-slug}.md`.
7. Update job row: `tailored_resume_path`, `status=tailored`.

**Quality gate:** First 3–5 tailored resumes and cover letters I review manually before trusting the pipeline. Add a `--review` flag that pauses for approval before saving.

**Done when:** `python main.py tailor` produces per-job PDFs and cover letter `.md` files for all `should_apply` jobs.

---

## Phase 4 — Auto-Apply

**Goal:** For ATS forms that don't require login, fill and submit applications. Abort and log unknowns when uncertain.

**Stack:** Playwright (Python), one handler per ATS.

**Per-application flow:**
1. Navigate to `apply_url`, screenshot.
2. Detect all form fields → list of `(label, input_type, required, selector)`.
3. For each field, call `field_matcher.match(label)` which:
   - Looks up `field_answers.yaml` via fuzzy + Claude-assisted matching.
   - Returns either a value or `UNKNOWN`.
4. **If any *required* field returns UNKNOWN:**
   - Abort this application.
   - Append to `outputs/unknowns.yaml` with: company, role, field label, field type, surrounding context.
   - Set job `status=needs_manual`, write reason.
   - Move on.
5. If all required fields resolved:
   - Upload tailored resume PDF.
   - Fill every field.
   - **Cover letter field handling:**
     - If field present and tailoring was run → paste/upload `outputs/cover_letters/{company}-{role-slug}.md`.
     - If field present but tailoring wasn't run or failed → use `profile_templates/cover_letter_fallback.md`.
     - If field is optional and tailoring wasn't run → skip it.
   - Take pre-submit screenshot.
   - **If `--dry-run`:** stop here, save screenshot, mark `status=ready_to_submit`.
   - **Else:** click submit, screenshot confirmation, mark `status=applied`, record `applied_at`.

**`field_answers.yaml` seed contents:**
- Full name, email, phone, location
- LinkedIn URL, GitHub URL, portfolio URL
- Work authorization (US / other countries as relevant)
- Visa sponsorship needed (y/n)
- Years of experience (total and by skill)
- Current/expected compensation
- Notice period / earliest start date
- Willingness to relocate
- Preferred pronouns
- EEOC self-identification (gender, race, veteran, disability)
- "How did you hear about us?" default
- Cover letter fallback text (for forms that require it but tailoring wasn't run)

**Learning loop:** Every UNKNOWN I answer gets appended to `field_answers.yaml`. Next run, automatic.

**Start narrow:** Greenhouse only, `--dry-run` only, for the first week. Review every screenshot before enabling real submit.

**CAPTCHAs and bot checks:** Auto-fail → `status=needs_manual` with reason `captcha_detected`. Do not try to solve.

**Done when:** `python main.py apply --dry-run --ats greenhouse` produces submit-ready screenshots for all `tailored` Greenhouse jobs.

---

## Phase 5 — Manual Queue

**Goal:** Clean report of everything that couldn't be auto-applied.

**`outputs/manual_queue.md` is regenerated on every run and contains:**
- Jobs with `status=needs_manual` (including auth-required and unknown-field cases)
- Sorted by `fit_score` descending
- For each: company, role, direct apply URL, fit score, tailored resume path, reason it's manual

I open this file once a day, click through, apply by hand.

---

## Phase 6 — Quality of Life (later, optional)

- Daily cron / scheduled run: `discover → evaluate → tailor → apply --dry-run`
- Email or Slack digest of new `should_apply` jobs
- Web dashboard (even a simple Streamlit app) over the SQLite DB
- ATS auto-detector: "paste 50 company names, get `sources.yaml` back"
- Per-company cover letter templates
- Response tracking: log recruiter replies, interview invites, rejections

---

## Build Order

1. **Phase 0** — one evening. Skeleton + DB schema.
2. **Phase 1** — one or two evenings. Greenhouse first, then Lever, then Ashby. With 20 target companies loaded, this alone is valuable.
3. **Phase 2** — one evening. Once this works, the bot is already 70% useful — I can see scored, ranked jobs every morning.
4. **Phase 3** — one or two evenings. Iterate on the tailoring prompt with real JDs.
5. **Phase 4** — a week, unhurried. Start with dry-run, Greenhouse only. Expand after trust.
6. **Phase 5** — trivial once Phase 4 logs are in place.
7. **Phase 6** — when and if I want.

Don't start a phase until the previous phase is committed, tested on real data, and feels stable.

---

## Out of Scope (deliberately)

- LinkedIn scraping or Easy Apply automation (ToS, bot detection, account-risk)
- Indeed, Glassdoor, ZipRecruiter scraping (same reasons)
- Workday authenticated applications (account creation required; goes to manual queue)
- Custom career pages (Apple, Google, Meta, Netflix) — manual only
- Bypassing CAPTCHAs or bot-detection
- Storing login credentials or session cookies for any site