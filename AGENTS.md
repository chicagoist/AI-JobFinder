# Repository Guidelines

## Overview

Python CLI tool that automates German job applications: searches Indeed/LinkedIn, scores jobs against a candidate profile via LLM, generates German cover letters (Anschreiben) in DIN 5008 format, fills web forms or sends direct emails.

## Email Requirements (HARD — DO NOT BREAK)

Two email paths exist; each has strict content requirements:

### 1. Candidate Email (Batch `--send-email` / CC copy)
- **Body:** Full terminal output for that specific vacancy (cleaned of ANSI codes). Not a brief summary — the complete `TeeStdout` log captured during `process_job_url`.
- **Attachments (direct PDFs, not ZIP):**
  - `Anschreiben_<Company>.pdf` — the generated cover letter PDF
  - `Lebenslauf.pdf` — newest CV from `candidate_files` table (classification `Lebenslauf`, ordered by `mtime DESC LIMIT 1`)
  - **All** Zertifikat / Diplom / Zeugnis / Arbeitszeugnis PDFs from `candidate_files` table — unconditionally, without keyword filtering. These are documents that influenced the LLM scoring decision.

### 2. Recruiter Email (Direct `send_direct_email`)
- **Body:** The full Anschreiben (cover letter) text — including Betreffzeile, Anrede, body, and Grußformel.
- **Attachments:** Same as candidate email — `Anschreiben_<Company>.pdf` + `Lebenslauf.pdf` + all Zertifikat/Diplom/Zeugnis/Arbeitszeugnis PDFs from `candidate_files`.

### Implementation
- **Candidate path:** `email_sender.py` → `send_pending_emails()` — body = `clean_ansi_escape_codes(terminal_output)`, attachments queried from `candidate_files` table.
- **Recruiter path:** `direct_email_applier.py` → `send_direct_email()` + `collect_relevant_attachments()` — body = `anschreiben_text`, attachments include all candidate documents unconditionally.

**NEVER remove or weaken these requirements.** They are the core purpose of this application.

## Architecture

- **Entrypoint**: `src/agent.py` (~2855 lines) — CLI parser + browser orchestration + document pipeline
- **Config**: `src/config/` — `config.yaml` (API keys/SMTP/Chrome path), `job_criteria.yaml` (KO filters/scoring), `candidate_profile.json` (parsed CV data), `prompts.yaml` (LLM prompts). All have `.sample` templates.
- **Core package** `src/job_agent/`:
  - `llm.py` — Gemini client with key rotation + OpenRouter fallback
  - `db.py` — SQLite (`src/output/applications.db`), tables: `applied_jobs`, `user_rejections`, `candidate_files`
  - `config.py` — YAML/JSON loaders, `DEFAULT_PROMPTS`, `restore_active_configs_from_samples()`
  - `utils.py` — `Colors` (ANSI), `force_ipv4()` (monkey-patch), `clean_and_repair_json()` (state machine), `TeeStdout`
  - `email_sender.py` — Batch ZIP + SMTP pending emails
  - `direct_email_applier.py` — Extracts recruiter email → SMTP with CC to candidate
  - `openrouter_llm.py`, `groq_llm.py`, `deepseek_llm.py` — Alternative providers (only OpenRouter is wired into `llm_request_with_fallback()`; Groq and DeepSeek modules exist but are not connected)
- **Data flow**: Search → Extract job text → Local KO filters → LLM score → Cover letter (LLM) → PDF (Playwright) → Apply (form/email) → Log to DB

## Key Directories

| Path | Purpose |
|------|---------|
| `src/` | Source code |
| `src/config/` | YAML/JSON config files + `.sample` templates |
| `src/output/` | PDFs, ZIPs, `applications.db` |
| `src/job_agent/` | Core library |
| `documents/` | Candidate PDFs (CV, certs, diplomas) |
| `src/knowledge.md` | Detailed reference (browser modes, API key rotation, PDF setup, scoring quirks) |

## Branch & Git

- **Active branch**: `develop`. `main` is stable/production only — merged from `develop` on explicit request (`merge`).
- **No direct commits to `main`**.
- **Commit policy**: After EVERY successful test run, run `git add -A && git commit -m "fix: <description>"`. Use present-tense imperative (English or German).
- Before committing, verify `git status` shows NO tracked active configs (`config.yaml`, `candidate_profile.json`, `.env`, `*.db`, `*.pdf`, `output/`, `chrome_data/`, `C:\*`).
- `.gitignore` blocks all `*.md` except `README.md`, `AGENTS.md`, `src/knowledge.md` — new `.md` files are untracked by default.

## CLI Commands

```bash
# Install (PyMuPDF missing from requirements.txt — install separately)
pip install -r requirements.txt && pip install PyMuPDF && playwright install chromium

# Config GUI (no args = Tkinter window, does NOT auto-close)
python src/agent.py

# Search + review
python src/agent.py --search-jobs "Junior Java" --location "Frankfurt" --radius 25

# Search + auto-apply headless (--headless implies --auto-approve implies --send-email)
python src/agent.py --search-jobs "Remote" --location "Berlin" --radius 50 --headless

# Single URL
python src/agent.py --url "https://de.linkedin.com/jobs/view/..."

# Parse CV + generate profile
python src/agent.py --parse-cv

# Send pending email summaries (standalone — skips Playwright)
python src/agent.py --send-email

# Reset workspace (restores .sample configs, deletes DB + PDFs, creates RESTORE commit)
python src/agent.py --reset-candidate

# Retry failed email submissions
python src/retry_email.py --list-failed
python src/retry_email.py --retry-all-failed

# Type check (Linux/macOS) — mypy only checks job_agent/, not agent.py
bash src/check_types.sh

# Skip direct email sending (testing only, used with --url or --search-jobs)
python src/agent.py --url "https://de.linkedin.com/jobs/view/..." --no-email

# Override Chrome user data directory
python src/agent.py --search-jobs "Remote" --location "Berlin" --chrome-data-dir "/path/to/chrome"

# Type check (Windows PowerShell)
pwsh src/check_types.ps1
```

### Flag Chaining

`--headless` auto-enables `--auto-approve` (no visible browser window to review). `--auto-approve` implies `--send-email`. When using `--headless`, Indeed is effectively skipped (Cloudflare blocks headless browsers).

## Install Quirks

- `requirements.txt` lists only `google-genai`, `playwright`, `pyyaml`. **`PyMuPDF` (fitz) is required** for PDF text extraction (`agent.py:591`) but is NOT listed — install separately.
- **`reportlab` is NOT required** despite being mentioned in `README.md`. The codebase uses Playwright's `page.pdf()` for PDF generation, never `reportlab`.
- OpenRouter API key goes in **`OPENROUTER_API_KEY` environment variable**, NOT in `config.yaml`.
- Google Gemini keys (up to 5) go in `config.yaml` → `gemini.api_keys`. Rotation is automatic.

## Browser Page Management

| Mode | Behavior |
|------|----------|
| **Without `--headless`** | Search page stays open. ONE persistent processing page reused for all jobs. You see each job listing load. |
| **With `--headless`** | Search page closed after search. Each job gets a fresh page (create → process → close). No visible window. |
| **`--url` or `--interactive`** | Always uses `with_new_page()` (create → process → close). |

## Document Scanning Pipeline

On every startup, `index_candidate_files()` in `agent.py`:

1. Globs `documents/*.pdf` and `src/output/*.pdf`
2. Compares with `candidate_files` DB table (detects added/modified/deleted)
3. For each new/modified PDF: reads first 1000 chars, classifies by filename → text keywords → LLM fallback
4. Dispatches to parser: `parse_cv()` (Lebenslauf) → writes `candidate_profile.json`, others (`parse_zertifikat_pdf`, etc.) → store parsed JSON
5. Profile loaded from DB on next run (falls back to JSON file)

**Critical**: The `education` field must contain a `curriculum` entry with detailed course modules so the scoring LLM can match against job requirements. The `parse_cv()` prompt now requests this.

## What NOT to Do

| Forbidden | Why |
|-----------|-----|
| Commit `config.yaml` or `candidate_profile.json` | Contains real API keys + personal data. `.gitignore` blocks them. |
| Commit `applications.db` | Personal data (emails, job history). Blocked by `.gitignore`. |
| Commit `*.pdf` or `*.html` | Contain candidate personal data. Blocked. |
| Commit Chrome profile dirs (`chrome_data/`, `C:\*`, `temp_profile/`) | Browser cache, cookies, sessions. Blocked. |
| Use async Playwright (`async with`) | The entire codebase uses Playwright's **sync** API. Mixing async will break. |
| Skip `clean_and_repair_json()` on LLM responses | LLM returns markdown-wrapped JSON with unescaped quotes. The state-machine in `utils.py` fixes this. |
| Remove `force_ipv4()` from `utils.py` | Kali Linux has broken IPv6; this monkey-patch is required. |
| Overwrite `.sample` files without testing `--reset-candidate` | The restore mechanism copies `.sample` → active files. Broken samples = broken reset. |
| Add `generation_config={"response_mime_type": "application/json"}` to OpenRouter calls | OpenRouter doesn't support this Gemini parameter. Use explicit JSON instruction in prompt text instead. |
| Change dedup logic in `is_already_applied()` | Matches by URL exact match OR cleaned company+title (see `job_agent/db.py:91`). Breaking this causes duplicate applications. |
| Remove `try/except ALTER TABLE` in `db.py` | DB migrations are implicit (`db.py:46-57`). Removing the try/except crashes on existing databases. |
| Forget `import re` and `import urllib.parse` | PLZ detection (`re.match(r"\d{5}")`) and URL encoding (`urllib.parse.quote()`) will fail. Both required for postal-code location support. |
| Use bright CYAN for dividers / labels | Reduces readability. Use `Colors.GREY` (dimmed) for labels and dividers so values stand out. |
| Skip `nargs="?"` on `--search-jobs` | Without it, `--search-jobs` without a value fails. `nargs="?"` allows empty query → show all vacancies. |
| Assume Windows-only Chrome paths | `config.yaml.sample` now shows examples for Windows, Linux, and macOS. Update `chrome_data_dir` for target OS. |

## Critical Gotchas

1. **Dual career path**: Profile can have IT (Junior → blocks Senior/Middle/Lead/Architect) AND Handwerk (Expert → allows all levels). `compute_forbidden_titles()` in `agent.py:1215` merges dynamic + static forbidden titles per job.
2. **LLM priority**: `config.yaml` `llm.priority: openrouter | gemini`. OpenRouter first → cheaper. Models tried in order: `gemini-2.5-flash` → `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-flash-latest`, then OpenRouter fallback.
3. **Chrome profile locking**: If Chrome is running, persistent context fails. Agent auto-fallbacks to `temp_profile/` without asking.
4. **Indeed Cloudflare**: 45s wait for manual resolution. In headless mode, Indeed is effectively skipped.
5. **MAX_LINKS config**: Job search result limit configurable via `job_criteria.yaml` → `search.max_results` (default ~25).
6. **SMTP fallback**: Port configured → 465 SSL. Direct email: 3 retry attempts. Batch: 2 attempts.
7. **GUI no longer auto-closes**: Config GUI stays open until user clicks Save or Cancel.
8. **PLZ location detection**: `--location "63517"` → Indeed uses URL-encoded `l=63517`, LinkedIn detects 5-digit PLZ via `re.match(r"\d{5}", location)` and appends `", Germany"` for geocoding.
9. **Output readability**: All labels use dimmed `Colors.GREY` with 2-space indent. Dividers use `Colors.GREY` instead of `Colors.CYAN`.
