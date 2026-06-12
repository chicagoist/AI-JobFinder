# Repository Guidelines

## Project Overview
This project is an AI-powered automated job application agent designed for the German job market. It automates the process of searching for jobs on Indeed and LinkedIn, scoring them against a candidate profile, generating tailored cover letters (Anschreiben) in German, and either filling out application forms or sending direct emails to recruiters.

## Architecture & Data Flow
- **Main Entry Point**: `src/agent.py` handles CLI arguments and coordinates the application flow.
- **Configuration**: Managed in `src/config/`, including `config.yaml` (system), `job_criteria.yaml` (filtering), and `candidate_profile.json` (user data).
- **Core Modules** (`src/job_agent/`):
    - `llm.py`: Abstraction layer for LLM providers (Gemini, OpenRouter).
    - `db.py`: SQLite database layer for logging applications and candidate files.
    - `email_sender.py`: Handles sending summary emails to the candidate.
    - `direct_email_applier.py`: Extracts recruiter contact info and sends applications directly.
    - `config.py`: Configuration and prompt loading logic.
- **Data Flow**: Search (Indeed/LinkedIn) -> Extract Job Text -> Score Job (LLM) -> Generate Cover Letter (LLM) -> Render PDF (Playwright) -> Apply (Form Filler or Direct Email) -> Log to DB.

## Key Directories
- `src/`: Core source code.
- `src/config/`: Configuration files and templates (.sample).
- `src/output/`: Generated PDFs, ZIP packages, and the SQLite database.
- `documents/`: Candidate's CV, certificates, and diplomas.

## Development Commands
- **Install Dependencies**: `pip install -r requirements.txt`
- **Run Job Search**: `python src/agent.py --search-jobs "Junior Java" --location "Frankfurt" --radius 25`
- **Send Pending Emails**: `python src/agent.py --send-email`
- **Reset Workspace**: `python src/agent.py --reset-candidate`
- **Parse CV to Profile**: `python src/agent.py --parse-cv`

## Code Conventions & Common Patterns
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes.
- **Error Handling**: Uses `Colors` utility for terminal output. Most operations are wrapped in try-except with fallbacks.
- **Async/Sync**: Primarily synchronous using Playwright's sync API.
- **LLM Integration**: Uses `llm_request_with_fallback` to ensure reliability across providers.
- **PDF Generation**: Handled via Playwright's `page.pdf()`. Note: Requires headless mode or a dedicated fallback instance.

## Important Files
- `src/agent.py`: CLI and main orchestration.
- `src/output/applications.db`: The source of truth for all applied jobs.
- `src/config/config.yaml`: SMTP settings, API keys, and Chrome profile paths.

## Runtime/Tooling Preferences
- **Python**: 3.10+ required.
- **Browser**: Google Chrome (preferred) or Chromium.
- **LLM**: Gemini 1.5/2.0 Flash or OpenRouter.

## Testing & QA
- Isolated testing scripts should be used to verify SMTP connectivity and LLM response parsing.
- Use `--headless` mode for automated testing to ensure PDF generation works without a display.
