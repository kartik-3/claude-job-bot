# job-bot

A personal job application bot that discovers roles from target companies, scores them against your resume, tailors your resume for good matches, and auto-applies where possible — queuing the rest for manual review.

**Company-first, not board-first.** Jobs are pulled directly from ATS platforms (Greenhouse, Lever, Ashby) via their public APIs, not scraped from LinkedIn or Indeed.

---

## What it does

| Phase | Command | What happens |
|-------|---------|-------------|
| 1 | `discover` | Fetches current openings from `sources.yaml` into SQLite |
| 2 | `evaluate` | Scores each new job against your resume via Claude; marks `should_apply` / `should_not_apply` |
| 3 | `tailor` | Generates a tailored resume PDF + cover letter per good-fit job; saves a `.diff` for review |
| 4 | `apply` | Fills and submits ATS forms via Playwright; aborts on unknown fields |
| 5 | `status` | Shows job counts by status; `outputs/manual_queue.md` lists jobs needing manual attention |

---

## Setup

**Requirements:** Python 3.11+, [Playwright](https://playwright.dev/python/)

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
cp profile_templates/resume.md              profile/resume.md
cp profile_templates/preferences.yaml       profile/preferences.yaml
cp profile_templates/field_answers.yaml     profile/field_answers.yaml
# Edit each file with your real information
# cover_letter_template.md and cover_letter_fallback.md are used directly
# from profile_templates/ by the tailor and applier modules
```

Edit `sources.yaml` to add the companies you want to track.

---

## Running the bot

```bash
# Check database state
python main.py status

# Pull new jobs from all sources in sources.yaml
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
```

After each run, check `outputs/manual_queue.md` for jobs that need manual attention (auth-required ATS, unknown form fields, CAPTCHAs).

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
evaluator/                # Claude-powered fit scoring
tailor/                   # resume tailoring + PDF rendering + cover letter generation
applier/                  # Playwright form automation
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
