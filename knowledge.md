# AI-JobFinder — Project Knowledge

## What This Is

Python CLI tool that automates German job applications: searches Indeed/LinkedIn, scores jobs against a candidate profile via LLM, generates German cover letters (Anschreiben) in DIN 5008 format, fills web forms or sends direct emails.

## Key Code Locations

| Path | Purpose |
|------|---------|
| `src/agent.py` | Main entry point (~2855 lines): CLI parser, browser orchestration, Tkinter GUI, document pipeline |
| `src/job_agent/llm.py` | Gemini client with key rotation + OpenRouter fallback |
| `src/job_agent/db.py` | SQLite helpers (`output/applications.db`), tables: `applied_jobs`, `user_rejections`, `candidate_files` |
| `src/job_agent/config.py` | YAML/JSON loaders, `DEFAULT_PROMPTS`, `restore_active_configs_from_samples()` |
| `src/job_agent/utils.py` | `Colors` (ANSI), `force_ipv4()`, `clean_and_repair_json()` (state machine), `TeeStdout` |
| `src/job_agent/email_sender.py` | Batch ZIP + SMTP pending emails |
| `src/job_agent/direct_email_applier.py` | Extracts recruiter email → SMTP with CC to candidate |
| `src/job_agent/openrouter_llm.py` | OpenRouter API client (wired into fallback) |
| `src/job_agent/groq_llm.py`, `src/job_agent/deepseek_llm.py` | Alternative providers (exist but NOT wired into fallback) |
| `src/config/` | `config.yaml`, `job_criteria.yaml`, `candidate_profile.json`, `prompts.yaml` — all have `.sample` templates |
| `documents/` | Candidate PDFs (CV, certs, diplomas) |
| `src/output/` | Generated PDFs, ZIPs, `applications.db` |

## Commands

```bash
# Install (PyMuPDF missing from requirements.txt — install separately)
pip install -r requirements.txt && pip install PyMuPDF && playwright install chromium

# Config GUI (no args = Tkinter window)
python src/agent.py

# Search + review
python src/agent.py --search-jobs "Junior Java" --location "Frankfurt" --radius 25

# Headless auto-apply (implies --auto-approve, implies --send-email)
python src/agent.py --search-jobs "Remote" --location "Berlin" --radius 50 --headless

# Single URL
python src/agent.py --url "https://de.linkedin.com/jobs/view/..."

# Parse CV + generate profile
python src/agent.py --parse-cv

# Send pending email summaries (standalone — skips Playwright)
python src/agent.py --send-email

# Reset workspace (restores .sample configs, deletes DB + PDFs)
python src/agent.py --reset-candidate

# Retry failed email submissions
python src/retry_email.py --list-failed
python src/retry_email.py --retry-all-failed

# Type check — mypy only checks job_agent/, not agent.py
bash src/check_types.sh    # Linux/macOS
pwsh src/check_types.ps1   # Windows

# Skip direct email (testing)
python src/agent.py --url "..." --no-email
```

## Architecture & Data Flow

Search → Extract job text → Local KO filters → LLM score (0-10) → Cover letter (LLM) → PDF (Playwright `page.pdf()`) → Apply (form fill or direct email) → Log to DB.

**LLM routing:** Priority from `config.yaml` `llm.priority` (gemini/openrouter). Gemini models tried in order: `gemini-2.5-flash` → `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-flash-latest`, rotating up to 5 API keys on 429 errors. Falls back to OpenRouter when all keys/models exhausted.

**Browser modes:**
- Without `--headless`: search page stays open, one persistent processing page reused
- With `--headless`: search page closed, fresh page per job (create → process → close). Indeed effectively skipped (Cloudflare blocks headless)
- `--url` / `--interactive`: always `with_new_page()` (create → process → close)

## Critical Conventions & Gotchas

1. **Sync Playwright only** — entire codebase uses Playwright's sync API. Never use `async with`.
2. **`clean_and_repair_json()` required** — LLM returns markdown-wrapped JSON with unescaped quotes. State-machine in `utils.py` fixes this.
3. **`force_ipv4()` required** — Kali Linux has broken IPv6; monkey-patch in `utils.py` is essential.
4. **PyMuPDF not in requirements.txt** — required for PDF text extraction, install separately.
5. **ReportLab NOT required** — PDF generation uses Playwright's `page.pdf()`, never ReportLab.
6. **OpenRouter API key** goes in `OPENROUTER_API_KEY` environment variable, NOT `config.yaml`.
7. **Gemini keys** (up to 5) go in `config.yaml` → `gemini.api_keys`.
8. **Don't add `generation_config={"response_mime_type": "application/json"}` to OpenRouter calls** — OpenRouter doesn't support it. Use explicit JSON instruction in prompt text.
9. **Database migrations are implicit** — `ALTER TABLE ... ADD COLUMN` wrapped in `try/except` in `db.py`.
10. **Dedup logic** — `is_already_applied()` matches by URL exact match OR cleaned company+title. Don't break this.
11. **PLZ location** — `--location "63517"` requires `import re` + `import urllib.parse` in `agent.py`.
12. **Output style** — labels use dimmed `Colors.GREY` with 2-space indent. Dividers use `Colors.GREY` (not CYAN).
13. **`nargs="?"` on `--search-jobs`** — required for empty-query support (show all vacancies).
14. **Dual career path** — profile can have IT (Junior → blocks Senior/Middle/Lead/Architect) AND Handwerk (Expert → allows all levels). `compute_forbidden_titles()` merges dynamic + static forbidden titles per job.
15. **Chrome profile locking** — if Chrome is running, persistent context fails; auto-fallbacks to `temp_profile/` without prompting.
16. **SMTP fallback** — port 465 SSL. Direct email: 3 retry attempts. Batch: 2 attempts.

## Git

- **Active branch**: `develop`. `main` is stable/production only — merged from `develop` on explicit request.
- **No direct commits to `main`**.
- Commit after every successful test run: `git add -A && git commit -m "fix: <description>"`
- Never commit: `config.yaml`, `candidate_profile.json`, `.env`, `*.db`, `*.pdf`, `output/`, Chrome profile dirs.
- `.gitignore` blocks all `*.md` except `README.md`, `AGENTS.md`, `src/knowledge.md`, and the new root `knowledge.md`.

## Document Scanning Pipeline

On startup, `index_candidate_files()`:
1. Globs `documents/*.pdf` and `src/output/*.pdf`
2. Compares with `candidate_files` DB table (detects added/modified/deleted)
3. Classifies by filename → text keywords → LLM fallback
4. Dispatches to parser: `parse_cv()` (Lebenslauf) → writes `candidate_profile.json`
5. Profile loaded from DB on next run (falls back to JSON file)

**Critical**: `education` field must contain a `curriculum` entry with detailed course modules so the scoring LLM can match against job requirements.
