# Repository Guidelines

## Overview

Python CLI tool that automates German job applications: searches Indeed/LinkedIn, scores jobs against a candidate profile via LLM, generates German cover letters (Anschreiben) in DIN 5008 format, fills web forms or sends direct emails.

## Architecture

- **Entrypoint**: `src/agent.py` (~2700 lines) — CLI parser + browser orchestration + document pipeline
- **Config**: `src/config/` — `config.yaml` (API keys/SMTP/Chrome path), `job_criteria.yaml` (KO filters/scoring), `candidate_profile.json` (parsed CV data), `prompts.yaml` (LLM prompts)
- **Core package** `src/job_agent/`:
  - `llm.py` — Gemini client with key rotation + OpenRouter fallback
  - `db.py` — SQLite (`src/output/applications.db`), tables: `applied_jobs`, `user_rejections`, `candidate_files`
  - `config.py` — YAML/JSON loaders, `DEFAULT_PROMPTS`, `restore_active_configs_from_samples()`
  - `utils.py` — `Colors` (ANSI), `force_ipv4()` (monkey-patch), `clean_and_repair_json()` (state machine), `TeeStdout`
  - `email_sender.py` — Batch ZIP + SMTP pending emails
  - `direct_email_applier.py` — Extracts recruiter email → SMTP with CC to candidate
  - `openrouter_llm.py`, `groq_llm.py`, `deepseek_llm.py` — Alternative providers
- **Data flow**: Search → Extract job text → Local KO filters → LLM score → Cover letter (LLM) → PDF (Playwright) → Apply (form/email) → Log to DB

## Key Directories

| Path | Purpose |
|------|---------|
| `src/` | Source code |
| `src/config/` | YAML/JSON config files + `.sample` templates |
| `src/output/` | PDFs, ZIPs, `applications.db` |
| `src/job_agent/` | Core library |
| `documents/` | Candidate PDFs (CV, certs, diplomas) |
| `src/.agents/` | Codebuff agent type definitions (keep) |

## CLI Commands

```bash
# Install
pip install -r requirements.txt && playwright install chromium

# Config GUI (no args = Tkinter window, no longer auto-closes)
python src/agent.py

# Search + review
python src/agent.py --search-jobs "Junior Java" --location "Frankfurt" --radius 25

# Search + auto-apply headless
python src/agent.py --search-jobs "Remote" --location "Berlin" --radius 50 --headless --auto-apply

# Single URL
python src/agent.py --url "https://de.linkedin.com/jobs/view/..."

# Parse CV + generate profile
python src/agent.py --parse-cv

# Send pending email summaries
python src/agent.py --send-email

# Reset workspace (restores .sample configs, deletes DB + PDFs)
python src/agent.py --reset-candidate

# Mock test (offline, mocks search, uses real LLM)
python src/mock_jobs.py

# Retry failed email submissions
python src/retry_email.py --list-failed
python src/retry_email.py --retry-all-failed

# Type check
bash src/check_types.sh

# LLM connectivity test
python src/test_genai.py

# Playwright test
python src/test_pw.py
```

## Document Scanning Pipeline

On every startup, `index_candidate_files()` in `agent.py`:

1. Globs `documents/*.pdf` and `src/output/*.pdf`
2. Compares with `candidate_files` DB table (detects added/modified/deleted)
3. For each new/modified PDF: reads first 1000 chars, classifies by filename → text keywords → LLM fallback
4. Dispatches to parser: `parse_cv()` (Lebenslauf) → writes `candidate_profile.json`, others (`parse_zertifikat_pdf`, etc.) → store parsed JSON
5. Profile loaded from DB on next run (falls back to JSON file)

**Critical**: The `education` field must contain a `curriculum` entry with detailed course modules so the scoring LLM can match against job requirements. The `parse_cv()` prompt now requests this.

## Git Commit Policy

- **After EVERY successful real test run** (any CLI command that completes without error), run:
  ```bash
  git add -A && git commit -m "fix: <kurze Beschreibung der Änderung>"
  ```
- Before committing, verify `git status` shows NO tracked active configs (`config.yaml`, `candidate_profile.json`, `.env`, `*.db`, `*.pdf`, `output/`, `chrome_data/`, `C:\*`)
- Use present-tense imperative messages in English or German

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
| Change dedup logic in `is_already_applied()` | Matches by URL exact match OR cleaned company+title. Breaking this causes duplicate applications. |
| Remove `try/except ALTER TABLE` in `db.py` | DB migrations are implicit. Removing the try/except crashes on existing databases. |

## Important Files

- `src/agent.py` — All orchestration logic
- `src/output/applications.db` — Source of truth for applications
- `src/config/config.yaml` — SMTP, API keys, Chrome path (gitignored)
- `src/knowledge.md` — Detailed reference (browser modes, API key rotation, PDF setup, scoring quirks)

## Critical Gotchas

1. **Chrome profile locking**: If Chrome is running, persistent context fails. Agent now auto-fallbacks to `temp_profile/` without asking.
2. **LLM priority**: `config.yaml` `llm.priority: openrouter | gemini`. OpenRouter first → cheaper.
3. **Headless → auto-approve**: `--headless` auto-enables `--auto-approve` (no browser window to review).
4. **Indeed Cloudflare**: 45s wait for manual resolution. In headless mode, Indeed is effectively skipped.
5. **Forbidden titles**: Dual career path — IT Junior blocks Senior/Middle/Lead/Architect; Handwerk Expert allows all.
6. **SMTP fallback**: Port configured → 465 SSL. Direct email: 3 retry attempts. Batch: 2 attempts.
7. **GUI no longer auto-closes**: Config GUI stays open until user clicks Save or Cancel.
