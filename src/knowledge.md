# Project Knowledge — Gemini JobAgent

## What This Project Is

A Python-based CLI job-application automation agent targeting the German job market. It uses Playwright to browse Indeed/LinkedIn, scores job descriptions against a candidate profile via LLM (Gemini / OpenRouter), generates German cover letters (Anschreiben) in DIN 5008 format, and attempts to fill web forms or send direct emails.

## Email Requirements (HARD — DO NOT BREAK)

These are the strict email requirements — the core purpose of this application.

### Candidate Email (`--send-email` batch / CC copy)
When the agent sends a summary email to the candidate:
- **Body:** The full terminal output (`TeeStdout`) captured during `process_job_url` for that specific vacancy — cleaned of ANSI codes. The complete log, not a brief summary.
- **Subject:** `"Bewerbung: {job_title} bei {company_name}"`
- **Attachments (direct PDF files, not ZIP):**
  1. `Anschreiben_<Company>.pdf` — generated cover letter
  2. `Lebenslauf.pdf` — newest CV from `candidate_files` (`ORDER BY mtime DESC LIMIT 1`)
  3. **All** Zertifikat / Diplom / Zeugnis / Arbeitszeugnis PDFs from `candidate_files` — unconditionally (no keyword filter). These documents influenced the LLM scoring.
- **Implementation:** `email_sender.py` → `send_pending_emails()`

### Recruiter Email (`send_direct_email`)
When the agent sends a direct application to a recruiter/employer:
- **Body:** The full Anschreiben (cover letter) text — Betreffzeile + Anrede + body + Grußformel.
- **Subject:** `"Bewerbung: {job_title} bei {company_name}"`
- **Attachments:** Same set as candidate email — CV + Anschreiben PDF + all score-influencing documents.
- **CC to candidate:** The agent sends a `[KOPIE]` copy to the candidate's own email with job metadata + the Anschreiben.
- **Implementation:** `direct_email_applier.py` → `send_direct_email()` + `collect_relevant_attachments()`

## Key Directories & Files

- **`agent.py`** — Main entry point (~2700 lines). Contains browser orchestration, job search, scoring, cover-letter generation, form filling, the Tkinter configuration GUI, and the CLI argument parser.
- **`job_agent/`** — Core package modules:
  - `llm.py` — Gemini API client with key-rotation, model fallback, and OpenRouter fallback.
  - `db.py` — SQLite database helpers (`applications.db` in `output/`).
  - `config.py` — YAML/JSON config loaders, default prompt templates.
  - `utils.py` — ANSI colors, JSON cleaning/repair, `TeeStdout`, signal handling.
  - `openrouter_llm.py`, `deepseek_llm.py`, `groq_llm.py` — Alternative LLM providers.
  - `direct_email_applier.py` — Email contact extraction, SMTP sending.
  - `email_sender.py` — Packages pending applications into ZIP files and sends via SMTP.
- **`config/`** — YAML/JSON configuration files (see below).
- **`output/`** — Generated cover-letter PDFs and `applications.db`.
- **`documents/`** — Candidate PDFs (CV, certificates, diplomas, etc.).
- **`temp_profile/`** — Fallback Chrome profile when main profile is locked.
- **`chrome_data/`, `chrome_data_Debug/`** — Alternative Chrome profile directories for debugging/alternate sessions.
- **Test/support files:**
  - `check_types.sh` — Static type checker (Linux/macOS).
  - `check_types.ps1` — Static type checker (Windows PowerShell).
  - `retry_email.py` — Retry failed email submissions.

## Commands

### Install Dependencies
```bash
pip install playwright pyyaml google-genai PyMuPDF openai
playwright install chromium
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

**Launch configuration GUI (Tkinter):**
```bash
python agent.py
```
The GUI opens only when NO CLI flags are passed.

**Search jobs in real browser (watch agent work):**
```bash
python agent.py --search-jobs "Remote Hybrid" --location "Frankfurt am Main" --radius 25
```
Browser pages stay open — you watch the agent scroll through job listings.

**Search & auto-apply (headless, background, no browser window):**
```bash
python agent.py --search-jobs "Remote Hybrid" --location "Frankfurt am Main" --radius 25 --headless --auto-approve
```
Pages are created and closed per job. No visible browser window.

**Background mode with email fallback (full automation):**
```bash
python agent.py --headless --auto-approve --send-email
```
Auto-enables search for pending jobs, scores, generates cover letters, fills forms, and emails if form fails. Zero user interaction.

**Process a single URL:**
```bash
python agent.py --url "https://de.linkedin.com/jobs/view/..."
```

**Interactive mode:**
```bash
python agent.py --interactive
```

**Send pending application emails (ZIP packages):**
```bash
python agent.py --send-email
```
Sends pending applications from the database as ZIP packages via SMTP.

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
bash check_types.sh
```

**Type check (Windows PowerShell):**
```powershell
.\src\check_types.ps1
```

**Reset everything:**
```bash
python agent.py --reset-candidate
```

## Browser Page Management

| Mode | Behavior |
|---|---|
| **Without `--headless`** | Search page stays open. ONE persistent processing page reused for all jobs. You see each job listing load. |
| **With `--headless`** | Search page closed after search. Each job gets a fresh page (create → process → close). No visible window. |
| **`--url` or `--interactive`** | Always uses `with_new_page()` (create → process → close). |

## Cross-Platform

- `src/config/config.yaml.sample` includes Chrome paths for Windows (`C:\Users\...`), Linux (`~/.config/google-chrome`), and macOS (`~/Library/Application Support/Google/Chrome`).
- Type checking: `bash check_types.sh` on Linux/macOS, `.\check_types.ps1` on Windows PowerShell.
- PowerShell (`pwsh`) is available on all three platforms.
- All core Python code (`src/agent.py`, `src/job_agent/`) is OS-independent.

## Notable Conventions & Gotchas

1. **No dependency manifest** — No `requirements.txt` or `pyproject.toml`. Packages installed manually.
2. **Chrome profile locking** — If Chrome is running, the agent connects via CDP on port 9222. Otherwise it launches a persistent context. Lock errors auto-fallback to `temp_profile/` **without prompting** (interactive `y/n` removed).
3. **Headless auto-approve** — `--headless` auto-enables `--auto-approve` since there's no browser window to review applications.
4. **API key rotation** — Multiple Gemini keys in `config.yaml` are rotated automatically. Falls back through cheaper models (`gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-flash-latest`) before trying OpenRouter.
5. **LLM priority** — `config.yaml` supports `llm.priority: gemini | openrouter`. Default is Gemini with OpenRouter fallback. When using OpenRouter, an `openrouter:` section in `config.yaml` is required with `api_key` and `model` fields.
6. **Indeed Cloudflare** — Indeed blocks headless/automated requests. The agent waits 45 seconds for manual Cloudflare resolution. In headless mode, Indeed is effectively skipped.
7. **Database migrations are implicit** — `job_agent/db.py` uses `ALTER TABLE ... ADD COLUMN` wrapped in `try/except`.
8. **DIN 5008 PDF generation** — Cover letters rendered via Playwright `page.pdf()` with CSS `@page { size: A4; margin: ... }`.
9. **Fallback email on form failure** — In `--auto-approve` mode, if form filler returns 0 actions, cover letter is emailed to the candidate's own email address.
10. **`compute_forbidden_titles()`** — Dynamically generates forbidden job titles based on candidate profile seniority per direction (IT Junior blocks Senior/Middle/Lead/Architect; Handwerk Expert allows all levels). Called once per job URL. Merged with static list from `job_criteria.yaml`.
11. **`hr_assessment` in profile** — If empty, `compute_forbidden_titles()` falls back to "Global" mode (only blocks Projektmanager, Sales, Marketing Manager, HR). Re-run `--parse-cv` to populate.
12. **`parse_cv()` uses `llm_request_with_fallback()`** — CV parsing now uses OpenRouter priority (if configured) instead of direct Gemini call. The `generation_config={"response_mime_type": "application/json"}` is intentionally omitted since OpenRouter doesn't support it; the prompt explicitly requests JSON.
13. **PLZ location support** — `--location "63517"` → Indeed URL-encodes with `urllib.parse.quote()`, LinkedIn detects 5-digit PLZ via `re.match(r"\d{5}", location)` → appends `", Germany"`. Requires `import re` + `import urllib.parse` in `agent.py`.
14. **Output colors** — Labels (`Page title:`, `Company:`, `Job Title:`, `Match Score:`) use `Colors.GREY` dimmed with 2-space indent. Dividers use `Colors.GREY` instead of `Colors.CYAN` so values (bright colors) contrast clearly.

## Git Workflow (Pet Project Best Practices)

- **Branching**: `main` ist der stabile/production Branch. **Sämtliche Entwicklung** findet im `develop` Branch statt.
- **Keine direkten Commits auf `main`** — nur Merges von `develop` nach explizitem Befehl (`merge`).
- Für größere Features können kurzlebige Feature-Branches von `develop` abgezweigt werden.
- Vor einem Merge auf `main` immer `git status` prüfen (keine aktiven Configs, keine Secrets).

## Git Commit Policy

- **After EVERY successful real test run** (any CLI command that completes without error), run:
  ```bash
  git add -A && git commit -m "fix: <kurze Beschreibung der Änderung>"
  ```
- Before committing, verify `git status` shows NO tracked active configs (`config.yaml`, `candidate_profile.json`, `.env`, `*.db`, `*.pdf`, `output/`, `chrome_data/`, `C:\*`)
- Use present-tense imperative messages in English or German
