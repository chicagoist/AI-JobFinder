# Project Knowledge — AI-JobFinder

## What This Project Is

A Python-based CLI job-application assistant targeting the German job market. It uses official job APIs (Bundesagentur für Arbeit, Arbeitnow) instead of web scraping, scores job descriptions against a candidate profile via local LLM (Ollama), generates German cover letters (Anschreiben) in DIN 5008 format, and creates email drafts for manual user review.

**Legal Compliance Principle:** ALL operations are local. No cloud LLM, no automatic SMTP sending, no session-based scraping. The user retains full control.

## Legal Compliance — Core Rules

See `LEGAL_COMPLIANCE_PLAN.md` for the full plan. Key rules:

1. **No automatic SMTP sending** — generate `.eml` draft files only (`email_draft_generator.py`)
2. **No cloud LLM for PII** — default LLM is local via Ollama (`ollama_llm.py`)
3. **No session-based scraping** — use official job APIs (`job_sources/` package)
4. **No automated decisions** — scoring is a recommendation, user decides
5. **GDPR consent required** — `onboarding.py` first-run consent flow

## Email Draft Requirements (HARD — DO NOT BREAK)

Instead of SMTP sending, generate `.eml` draft files in `src/drafts/`:

### Candidate Email Draft
- **Body:** The full terminal output (`TeeStdout`) captured during `process_job_url` for that specific vacancy — cleaned of ANSI codes. The complete log, not a brief summary.
- **Attachments (direct PDF files, not ZIP):**
  1. `Anschreiben_<Company>.pdf` — generated cover letter
  2. `Lebenslauf.pdf` — newest CV from `candidate_files` (`ORDER BY mtime DESC LIMIT 1`)
  3. **All** Zertifikat / Diplom / Zeugnis / Arbeitszeugnis PDFs from `candidate_files` — unconditionally.
- **Implementation:** `email_draft_generator.py` → `generate_email_draft()`

### Recruiter Email Draft
- **Body:** The full Anschreiben (cover letter) text — Betreffzeile + Anrede + body + Grußformel.
- **Attachments:** Same set as candidate draft — CV + Anschreiben PDF + all score-influencing documents.
- **Implementation:** `email_draft_generator.py` → `generate_email_draft()`

## Key Directories & Files (Post-Compliance)

- **`agent.py`** — Main entry point. Uses job APIs for search, local LLM for scoring, generates email drafts.
- **`onboarding.py`** — GDPR consent flow on first run.
- **`job_agent/`** — Core package modules:
  - `llm.py` — LLM router with priority: local (Ollama) → OpenRouter → Gemini.
  - `ollama_llm.py` — Local LLM client via Ollama HTTP API.
  - `email_draft_generator.py` — Generates `.eml` / `.txt` draft files instead of SMTP sending.
  - `job_sources/` — Official job API adapters (Bundesagentur, Arbeitnow).
  - `db.py` — SQLite database helpers (`applications.db` in `output/`).
  - `config.py` — YAML/JSON config loaders, default prompt templates.
  - `utils.py` — ANSI colors, JSON cleaning/repair, `TeeStdout`, signal handling.
  - `direct_email_applier.py` — Email contact extraction (draft-only, no sending).
  - `email_sender.py` — Batch draft generation (no SMTP).
  - `openrouter_llm.py`, `deepseek_llm.py`, `groq_llm.py` — Alternative LLM providers (optional fallbacks).
- **`config/`** — YAML/JSON configuration files.
- **`drafts/`** — Generated `.eml` / `.txt` draft files for manual sending.
- **`output/`** — Generated cover-letter PDFs and `applications.db`.
- **`documents/`** — Candidate PDFs (CV, certificates, diplomas, etc.).
- **`scripts/`** — Utility scripts (e.g. `setup_local_llm.sh` for Ollama installation).

## Commands

### Install Dependencies
```bash
# Core packages
pip install playwright pyyaml google-genai PyMuPDF
playwright install chromium

# Local LLM (recommended for GDPR compliance)
bash scripts/setup_local_llm.sh
```

### First-Time Setup
```bash
# Restore sample config files to active ones (deletes DB + PDFs)
python agent.py --reset-candidate

# Generate a dummy CV for testing
python agent.py --generate-dummy-cv

# Parse CV to generate candidate profile (auto-scans documents/)
python agent.py --parse-cv
```

### Run the Agent

**Search jobs via official API (no scraping):**
```bash
python agent.py --search-jobs "Fachinformatiker" --location "Frankfurt am Main" --radius 25
```
Uses Bundesagentur für Arbeit + Arbeitnow APIs. No Playwright browser needed for search.

**Process a single URL (read-only):**
```bash
python agent.py --url "https://de.linkedin.com/jobs/view/..."
```
Playwright loads the page read-only — no session, no login.

**Generate email drafts (no SMTP sending):**
```bash
python agent.py --send-email
```
Creates `.eml` draft files in `src/drafts/` for manual sending.

**Test scoring locally:**
```bash
python agent.py --test-score path/to/job_description.txt
```

**Test cover letter generation:**
```bash
python agent.py --test-anschreiben "Company Name" path/to/job_description.txt
```

**Type check (Linux/macOS):**
```bash
bash src/check_types.sh
```

**Reset everything:**
```bash
python agent.py --reset-candidate
```

## Cross-Platform

- `src/config/config.yaml.sample` includes Chrome paths for all OS.
- Type checking: `bash check_types.sh` on Linux/macOS.
- All core Python code is OS-independent.
- Ollama runs on Linux, macOS, Windows (WSL2).

## Browser Page Management (Post-Compliance)

Playwright is ONLY used for:
- **PDF generation** (Anschreiben rendering) — read-only, no session, no login
- **Single URL processing** — as a convenience, user-requested

NO more search scraping, no persistent profiles, no headless search.

## Notable Conventions & Gotchas

1. **Local LLM is default** — `llm.priority: local` in config.yaml. Cloud LLMs are optional fallbacks.
2. **No SMTP sending** — All email output is `.eml` draft files. The user sends manually.
3. **Job APIs not scraping** — Bundesagentur für Arbeit and Arbeitnow APIs replace Indeed/LinkedIn scraping.
4. **GDPR consent on first run** — Privacy notice shown, consent logged to database.
5. **DIN 5008 PDF generation** — Cover letters rendered via Playwright `page.pdf()` with CSS `@page { size: A4; margin: ... }`.
6. **Database migrations are implicit** — `job_agent/db.py` uses `ALTER TABLE ... ADD COLUMN` wrapped in `try/except`.
7. **`consent_log` table** — Logs user consent with timestamp and version.
8. **`drafts/` directory** — Generated email drafts, gitignored (contains PII).
9. **Scoring is a recommendation** — Never auto-apply. Human review required.
10. **`clean_and_repair_json()`** — Always use on LLM responses (JSON wrapped in markdown).
11. **`force_ipv4()`** — Required on Kali Linux due to broken IPv6.
12. **Output colors** — Labels use `Colors.GREY` dimmed with 2-space indent. Dividers use `Colors.GREY`.

## Git Workflow

- **Branching**: `main` ist stabil/production. **Entwicklung** in `develop`.
- **Keine direkten Commits auf `main`** — nur Merges.
- Vor Commit: `git status` prüfen (keine aktiven Configs, keine Secrets).

## Git Commit Policy

- After EVERY successful test run: `git add -A && git commit -m "fix: <description>"`
- Use present-tense imperative (English or German).
