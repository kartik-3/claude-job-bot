# job-bot

A personal job application bot that discovers roles from target companies, scores them against your resume, tailors your resume for good matches, and auto-applies where possible — queuing the rest for manual review.

**Company-first, not board-first.** Jobs are pulled directly from ATS platforms (Greenhouse, Lever, Ashby) via their public APIs, not scraped from LinkedIn or Indeed.

---

## What it does

| Phase | Command | What happens |
|-------|---------|-------------|
| 1 | `discover` | Fetches current openings from `sources.yaml`; pre-filters by title, location, and tech keywords using your preferences before storing |
| 2 | `evaluate` | Hard-gates remaining jobs (seniority, excluded titles); scores survivors against your resume via Claude; marks `should_apply` / `should_not_apply` |
| 3 | `tailor` | Generates a tailored resume PDF + cover letter per good-fit job |
| 4 | `apply` | Fills and submits ATS forms via Playwright; aborts on unknown fields |
| — | `status` | Shows job counts by status |
| — | `report` | Shows all evaluated jobs ranked by fit score; exportable to CSV |
| — | `clear` | Deletes all records from the database (prompts for confirmation) |
| — | `serve` | Starts the Django API server for the web dashboard |

---

## Setup

**Requirements:** Python 3.11+, Node.js 18+ (for the dashboard), [Playwright](https://playwright.dev/python/)

```bash
git clone https://github.com/kartik-3/claude-job-bot.git
cd claude-job-bot

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env          # add your ANTHROPIC_API_KEY
```

### PDF rendering (required for `tailor`)

The tailor module renders resumes to PDF using pandoc. Without it, resumes are saved as styled HTML (which you can print to PDF from a browser).

**macOS:**
```bash
brew install pandoc
brew install --cask basictex   # minimal LaTeX for pandoc's PDF engine
```

**Linux:**
```bash
sudo apt install pandoc texlive-xetex
```

Alternatively, install [pango](https://pango.gnome.org/) (`brew install pango`) to use WeasyPrint instead — both renderers are tried automatically.

Create your profile (gitignored — never committed):

```bash
mkdir -p profile/cover_letters
cp profile_templates/resume.example.md                  profile/resume.md
cp profile_templates/preferences.example.yaml           profile/preferences.yaml
cp profile_templates/field_answers.example.yaml         profile/field_answers.yaml
cp profile_templates/cover_letter_template.example.md   profile_templates/cover_letter_template.md
cp profile_templates/cover_letter_fallback.example.md   profile_templates/cover_letter_fallback.md
# Edit each file with your real information
```

Edit `sources.yaml` to add the companies you want to track.

**Finding the right slug for each ATS:**

| ATS | How to find the slug |
|-----|---------------------|
| Greenhouse | The slug is in the careers URL: `boards.greenhouse.io/{slug}/jobs` |
| Lever | The slug is in the URL: `jobs.lever.co/{slug}` |
| Ashby | The slug is in the URL: `jobs.ashbyhq.com/{slug}` |
| Workday | Visit the careers page → find the redirect to `{tenant}.wd{n}.myworkdayjobs.com/{site}/jobs` → slug format is `{tenant}.wd{n}/{site}` (e.g. `microsoft.wd1/MSFTExternal`) |

If you're unsure which ATS a company uses, run the auto-detector (see below).

---

## Running the bot

```bash
# Check database state (totals by pipeline status)
python main.py status

# Show per-company breakdown — how many jobs scraped per company,
# and how many are to-apply / rejected / still pending evaluation
python main.py status --companies

# Check which companies in sources.yaml are reachable and suggest fixes for broken ones
python main.py detect

# Test a specific company only
python main.py detect --company Uber

# Pull new jobs from all sources, pre-filtered by profile/preferences.yaml
python main.py discover

# Score new jobs against your resume
python main.py evaluate

# Generate tailored resume PDFs + cover letters for good-fit jobs
python main.py tailor

# Pause for manual approval before saving each result (recommended for first run)
python main.py tailor --review

# Dry-run auto-apply (screenshots only, nothing submitted)
python main.py apply

# Actually submit applications (use carefully)
python main.py apply --submit

# Limit apply to one ATS platform
python main.py apply --ats greenhouse

# Verbose logging
python main.py --verbose discover

# Delete all jobs from the database (will prompt for confirmation)
python main.py clear
```

### Viewing and exporting results

```bash
# Show all evaluated jobs ranked by fit score (terminal table)
python main.py report

# Filter by status
python main.py report --status should_apply        # only recommended roles
python main.py report --status should_not_apply    # only rejected roles (useful for sanity-checking)
python main.py report --status tailored            # roles with tailored resumes ready
python main.py report --status needs_manual        # roles that need manual application

# Export to CSV — opens directly in Excel or Google Sheets
python main.py report --output results.csv
python main.py report --status should_apply --output shortlist.csv

# The CSV columns are:
#   score     — fit score 0–100 (blank if rejected by hard gate before LLM scoring)
#   status    — current pipeline status
#   company   — company name
#   title     — job title
#   url       — direct link to the job / application page
#   notes     — one-line reasoning from Claude, or hard-gate rejection reason
```

After each run, check `outputs/manual_queue.md` for jobs that need manual attention (auth-required ATS, unknown form fields, CAPTCHAs).

---

## Web dashboard

A local React + Django dashboard for browsing jobs, filtering, and updating status.

### Start the dashboard

```bash
# Terminal 1 — Django API (port 8000)
python main.py serve

# Terminal 2 — React dev server (port 5173)
cd dashboard/frontend
npm install   # first time only
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

### Features

- **Stats bar** — live counts for `should_apply`, `tailored`, `applied`, `needs_manual`
- **Filters** — search by company/title, filter by status, company, or ATS platform
- **Inline status editing** — change a job's status from the dropdown; saved immediately to SQLite
- **Color-coded scores** — green ≥ 75, yellow 50–74, red < 50
- **Links** — direct links to the job listing and application page

---

## How discover pre-filtering works

When `profile/preferences.yaml` exists, `discover` drops non-matching jobs before they reach the database — saving LLM calls and keeping the DB clean.

A job is filtered out if:

| Check | Source field | Configured in |
|-------|-------------|---------------|
| Title is in `excluded_titles` | `title` | `preferences.yaml` → `excluded_titles` |
| Seniority too high (Staff, Principal, VP…) | `title` | built-in list |
| Seniority too low (Junior, Intern…) | `title` | built-in list + `preferences.yaml` → `seniority.min` |
| Title doesn't match any `target_roles` | `title` | `preferences.yaml` → `target_roles` |
| Location doesn't match | `location` | `preferences.yaml` → `locations` + `remote_ok` |
| Description has none of your `tech_keywords` | `description` | `preferences.yaml` → `tech_keywords` |

Jobs with no description (e.g. Workday) bypass the keyword check and go straight to LLM evaluation.

If `profile/preferences.yaml` is missing, all scraped jobs are stored (with a warning) — same behaviour as before.

---

## How evaluation works

For every `status=new` job that survived discovery filtering, `evaluate` runs two stages:

1. **Hard gate (no LLM)** — re-runs the same title/seniority/location checks as discovery (catches any that slipped through without preferences), plus checks `excluded_titles`. Failures are marked `should_not_apply` instantly with a reason, no API call made.

2. **LLM scoring** — Claude receives your resume, the JD, and your preferences (seniority range, locations, fit threshold). It returns a structured JSON score with matched requirements, concerns, and a `should_apply` boolean. Jobs scoring below `fit_score_threshold` (default 70) are marked `should_not_apply`.

---

## Project structure

```
sources.yaml              # companies + ATS type (edit this)
profile/                  # your resume, preferences, form answers (gitignored)
  cover_letters/          # per-job tailored cover letters (gitignored)
profile_templates/        # template files to copy from
  cover_letter_template.md   # filled per-job by tailor module (Phase 3)
  cover_letter_fallback.md   # fixed short paragraph for low-priority / char-limited forms
scrapers/                 # ATS API clients (Greenhouse, Lever, Ashby, Workday)
evaluator/                # Claude-powered fit scoring + pre-filters
  filters.py              # hard_gate and keyword_matches — used by both discover and evaluate
tailor/                   # resume tailoring + PDF rendering + cover letter generation
applier/                  # Playwright form automation
dashboard/                # web dashboard
  views.py                # Django API (GET /api/jobs/, PATCH /api/jobs/<id>/)
  frontend/               # Vite + React app
db/                       # SQLite database (gitignored)
outputs/                  # tailored PDFs, screenshots, logs (gitignored)
  cover_letters/          # generated cover letters (gitignored)
```

---

## Safety rules

- Profile data (`profile/`) is gitignored and never committed.
- `apply` defaults to dry-run; real submissions require `--submit`.
- Unknown required form fields → abort, log to `outputs/unknowns.yaml`, mark `needs_manual`.
- CAPTCHAs → mark `needs_manual`, move on.
- Resume content is sent only to the Anthropic API and the specific ATS form being applied to.
