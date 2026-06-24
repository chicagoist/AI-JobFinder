# Repository Guidelines

## Overview

Python CLI tool that automates German job applications: searches job APIs (Bundesagentur, Arbeitnow), scores jobs against a candidate profile via local LLM (Ollama), generates German cover letters (Anschreiben) in DIN 5008 format, generates email drafts for manual review.

**KEY PRINCIPLE: This project operates FULLY LOCALLY — no cloud LLM, no automatic email sending, no session-based scraping.**

## Legal Compliance Requirements (HARD — DO NOT BREAK)

This project must NEVER violate EU/German law. The following rules are NON-NEGOTIABLE:

### 1. SMTP — Candidate Self-Email Only
- ✅ SMTP sending to candidate's OWN email address (data subject) IS ALLOWED
  - `send_candidate_email()` sends per-job application data to the user who runs the tool
  - The candidate is the data subject — GDPR Art. 6(1)(f) legitimate interest
- ❌ SMTP sending to RECRUITERS/EMPLOYERS is FORBIDDEN
  - `send_direct_email()` / any third-party SMTP auto-send is prohibited
  - `.eml` draft files for manually forwarding to recruiters are fine
- ✅ `--send-email` flag: sends per-job SMTP to candidate + generates digest `.eml` for backup
- ✅ Standalone `--send-email` (without `--pipeline`): iterates pending DB jobs and sends per-job SMTP

### 2. No Cloud LLM for PII Processing
- ❌ Google Gemini sending candidate PII to US servers is FORBIDDEN
- ✅ Default LLM must be LOCAL (Ollama: Qwen/Llama/Mistral)
- ✅ Cloud LLM (Gemini, OpenRouter) is OPTIONAL fallback only with explicit user consent
- ✅ `--no-cloud-llm` flag: forcibly blocks ALL remote LLM calls at runtime, overriding config
- ✅ `config.yaml` → `llm.priority: local` + `llm.allow_cloud_fallback: false` for permanent block

### 3. No Session-Based Scraping
- ❌ Web scraping with logged-in browser sessions (persistent Chrome profiles) is FORBIDDEN
- ✅ Use official job APIs: Bundesagentur für Arbeit, Arbeitnow
- ✅ Playwright is ONLY for PDF generation — read-only, no sessions, no login

### 4. No Automated Profiling Decisions
- ❌ Auto-applying based on LLM score is FORBIDDEN
- ✅ Scoring is a RECOMMENDATION only
- ✅ All outputs are drafts — user reviews and decides

### 5. GDPR Consent Required
- ✅ Privacy notice shown on first run
- ✅ Explicit consent logged to database before any processing

## Email Draft Requirements (HARD — DO NOT BREAK)

Instead of SMTP sending, generate `.eml` draft files:

### 1. Candidate Email Draft
- **Body:** Metadata prefix (company, job title, job URL) + full terminal output for that specific vacancy (cleaned of ANSI codes). The URL MUST be included so the candidate can review the original posting.
- **Attachments (direct PDFs, not ZIP):**
  - `Anschreiben_<Company>.pdf` — the generated cover letter PDF
  - `Lebenslauf.pdf` — newest CV from `candidate_files` table (classification `Lebenslauf`, ordered by `mtime DESC LIMIT 1`)
  - **Only** Zertifikat / Diplom / Zeugnis / Arbeitszeugnis PDFs whose `classification` is in the LLM's `relevant_documents` response. NOT all certs unconditionally. If `relevant_documents` is empty or missing, attach all certs (backward compat).

### 2. Recruiter Email Draft
- **Body:** The full Anschreiben (cover letter) text — including Betreffzeile, Anrede, body, and Grußformel.
- **Attachments:** Same as candidate draft — `Anschreiben_<Company>.pdf` + `Lebenslauf.pdf` + all Zertifikat/Diplom/Zeugnis/Arbeitszeugnis PDFs.

### Implementation
- **Candidate path:** `email_draft_generator.py` → `generate_email_draft()` — body = metadata prefix (company, title, URL) + `clean_ansi_escape_codes(terminal_output)`, attachments from `candidate_files`.
- **Recruiter path:** `email_draft_generator.py` → `generate_email_draft()` — body = `anschreiben_text` (DIN 5008 full text with header), same attachments.
- **SMTP path:** `email_sender.py` → `send_candidate_email()` — body = metadata prefix (company, title, URL) + `clean_ansi_escape_codes(terminal_output)`, same attachments.

**NEVER replace draft generation with SMTP sending.** This is the core legal protection.

## Execution TODO List (optimized for context/token window)

This TODO list breaks the restructuring into independent steps. Each step is a complete work unit that can be executed in one conversation turn.

### Step 1: Create `email_draft_generator.py`
- **Files:** NEU `src/job_agent/email_draft_generator.py`
- **What:** Module with `generate_email_draft()` — creates `.eml` + `.txt` files in `src/drafts/`
- **Input:** Same params as `send_direct_email()`
- **Output:** Path to saved draft file
- **Delete:** SMTP sending code from `direct_email_applier.py` and `email_sender.py`
- **Test:** `python -c "from job_agent.email_draft_generator import generate_email_draft; ..."`

### Step 2: Create `ollama_llm.py` + update `llm.py`
- **Files:** NEU `src/job_agent/ollama_llm.py`, EDIT `src/job_agent/llm.py`
- **What:** Local LLM client via Ollama HTTP API
- **Priority:** local → openrouter → gemini
- **Default:** `llm.priority: local` in config
- **Test:** `bash scripts/setup_local_llm.sh && python -c "from job_agent.ollama_llm import call_ollama; print(call_ollama('test'))"`

### Step 3: Create `job_sources/` package
- **Files:** NEU `src/job_agent/job_sources/__init__.py`, `bundesagentur.py`, `arbeitnow.py`
- **What:** Official job API adapters — no scraping, no browser sessions
- **Test:** `python -c "from job_agent.job_sources.bundesagentur import BundesagenturSource; print(BundesagenturSource().search('Python', 'Frankfurt'))"`

### Step 4: Refactor `agent.py` — API search + HITL scoring + draft pipeline
- **Files:** EDIT `src/agent.py`
- **What:** Replace Indeed/LinkedIn scraping with API search; replace auto-apply with draft generation; scoring = recommendation
- **Test:** `python -u src/agent.py --search-jobs "Fachinformatiker" --location "Frankfurt" --radius 25`

### Step 5: Create `onboarding.py` + GDPR consent
- **Files:** NEU `src/onboarding.py`, EDIT `src/job_agent/db.py`
- **What:** First-run consent flow, `consent_log` table, privacy notice
- **Test:** Run agent without DB → should show consent

### Step 6: Typecheck + commit + push
- **Run:** `bash src/check_types.sh`
- **Commit:** `git add -A && git commit -m "feat: legal compliance — local LLM, draft-only email, official APIs, HITL scoring, GDPR consent"`
- **Push:** `git push origin develop`

## Full Restructuring Plan

See `LEGAL_COMPLIANCE_PLAN.md` for the complete detailed plan with code snippets, risk assessment, and module map.

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

# Block cloud LLM (local only — fails if Ollama/llama-server unavailable)
python src/agent.py --search-jobs "Remote" --location "Berlin" --no-cloud-llm

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
## Hard Requirements (from session — DO NOT VIOLATE)

### 1. Seniority Level — Never Block Applications
- ❌ High experience years (20+) must NEVER prevent applying to ANY job.
- ❌ LLM prompt must NOT use seniority level to block jobs.
- ✅ Candidate can apply to ALL job levels regardless of experience.
- ✅ Only explicitly forbidden titles are blocked — by title match, NOT by seniority.

### 2. PDF to LLM — Text Only, Never Binary
- ✅ Only extracted TEXT from PDF (via fitz.get_text()) is sent to LLM — never binary PDF.
- ✅ All PDF processing (CV, certs, diplomas) uses `fitz` (PyMuPDF) to extract text first.
- ❌ Sending raw binary PDF content to any LLM is FORBIDDEN.

### 3. Local Model — llama3.2:3b-hr-assistant (REQUIRED)
- ✅ Default local model MUST be `llama3.2:3b-hr-assistant` for ALL LLM operations (CV parsing, scoring, cover letters).
- ✅ This model provides sufficient quality for German HR text tasks (~2GB).
- ✅ Set globally: `ollama_llm.py:DEFAULT_MODEL`, `config.yaml:llm.local_model`, `config.py:DEFAULT_PROMPTS`.
- ✅ CV parsing and all other LLM calls use `call_ollama(model=DEFAULT_MODEL)`.
- ✅ Only extracted TEXT from PDF (via fitz.get_text()) is sent to LLM — never binary PDF.

### 3. PDF Indexing — Only on Changes, Only in documents/
- ✅ PDFs analyzed via LLM ONLY on first run or when files change (mtime + file size).
- ✅ Only scans `documents/*.pdf` — NEVER scans `output/` (generated cover letters).
- ✅ candidate_files DB table tracks file_path, file_size, mtime, classification, parsed_json.
- ❌ Never re-parse unchanged PDFs.
- ❌ Never scan or parse files from `output/` directory.

### 4. Intake Prompt — No Seniority Filtering
- The job_intake_prompt must state: "Die Berufserfahrung (auch 20+ Jahre) darf NIEMALS zur Ablehnung führen."
- "Der Kandidat kann sich auf JEDES Stellenlevel bewerben unabhängig von seiner Erfahrung."

### 5. Email Mode Messages
- --send-email: Show "Emails sent to candidate via SMTP."
- Without: Show "Please open .eml files manually to send (GDPR compliance)."

### 6. --cloud-only Flag
- `--cloud-only` skips local LLM entirely and uses only OpenRouter → Gemini.
- Equivalent to setting priority: openrouter + allow_cloud_fallback: true, enforced at runtime.
- Mutually exclusive with --no-cloud-llm (the latter forbids cloud). Use --cloud-only when local models are too slow for testing.
- With --cloud-only, `llama3.2:3b-hr-assistant` must NEVER be used. CV parsing uses `llm_request_with_fallback()` like everything else.
- The `3b-hr-assistant` model is ONLY for --no-cloud-llm mode (local only).
- **CRITICAL**: When checking `CLOUD_ONLY` global in functions, use `import job_agent.llm as _llm_mod` then `_llm_mod.CLOUD_ONLY` — do NOT use `from job_agent.llm import CLOUD_ONLY` which copies the value at import time and misses runtime mutations.

### 7. Testing — min_score_to_apply: 3.0
- During all testing, set `scoring.min_score_to_apply: 3.0` globally and per industry.
- This ensures borderline jobs (score 3.0-4.9) are tested and not auto-rejected.
- Override to 5.0 for production to reduce false positives.
