#!/usr/bin/env python3
"""
Retry sending a direct email for a previously failed job application.

Usage:
    python3 retry_email.py <DB_ID>              # Retry a specific application by DB ID
    python3 retry_email.py --list-failed         # List all failed email entries
    python3 retry_email.py --retry-all-failed    # Retry all entries with failed email status

The script will:
1. Load the DB entry and check if it has a job URL
2. Launch a headless browser to fetch the job page
3. Re-extract contact info and job text
4. Re-generate the Anschreiben (cover letter)
5. Call send_direct_email() to send to the employer (and CC to candidate)
6. Update the DB status on success
"""

import os
import sys
import json
import sqlite3

# Add src to path for imports
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# Project root (parent of src/) — where documents/, config/, output/ live
WORKSPACE_DIR = os.path.dirname(SRC_DIR)
sys.path.insert(0, SRC_DIR)

from job_agent.config import load_config
from job_agent.utils import Colors, TeeStdout
from job_agent.llm import init_gemini
from job_agent.direct_email_applier import (
    extract_contact_info,
    personalize_anschreiben,
)
from job_agent.pipeline import JobPipeline
from playwright.sync_api import sync_playwright

# ─── DB helpers ──────────────────────────────────────────────────────────────

DB_PATH = os.path.join(SRC_DIR, "output", "applications.db")
PROFILE_PATH = os.path.join(SRC_DIR, "config", "candidate_profile.json")


def get_entry(db_id: int) -> dict | None:
    """Load a single application entry from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM applied_jobs WHERE id = ?", (db_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def list_failed_entries() -> list[dict]:
    """List all entries with a failed email status."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT id, company_name, job_title, url, status FROM applied_jobs "
        "WHERE (status LIKE '%Direct Email Failed%' OR status LIKE '%Email Failed%') "
        "  AND url NOT LIKE '%example.com%'"
        "ORDER BY id"
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_status(db_id: int, new_status: str, email_sent: int = 1):
    """Update the status and email_sent flag of an entry."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE applied_jobs SET status = ?, email_sent = ? WHERE id = ?",
        (new_status, email_sent, db_id),
    )
    conn.commit()
    conn.close()


# ─── Core retry logic ────────────────────────────────────────────────────────

def retry_single(db_id: int) -> int:
    """
    Retry email for a single DB entry.
    Returns: 0 on success, 1 on failure, 2 on skip (not retry-able).
    """
    entry = get_entry(db_id)
    if not entry:
        print(f"{Colors.RED}Error: No entry found with ID {db_id}{Colors.END}")
        return 1

    status = entry["status"]
    url = entry.get("url", "")
    company = entry.get("company_name", "Unknown")
    title = entry.get("job_title", "Unknown")

    print(f"\n{Colors.CYAN}{'='*70}{Colors.END}")
    print(f"{Colors.CYAN}Retrying email for ID {db_id}: {title} at {company}{Colors.END}")
    print(f"{Colors.CYAN}Current status: {status}{Colors.END}")
    print(f"{Colors.CYAN}URL: {url}{Colors.END}")

    # Check if this entry is even retry-able
    if "Failed" not in status:
        print(f"{Colors.YELLOW}Status is not a failure — no need to retry.{Colors.END}")
        return 2

    if not url or "example.com" in url:
        print(f"{Colors.RED}Cannot retry: no real job URL (test/mock entry).{Colors.END}")
        return 2

    # Load config and profile
    print(f"\n{Colors.BLUE}Loading configuration...{Colors.END}")
    config = load_config()
    smtp_config = config.get("smtp", {})

    if not smtp_config.get("host"):
        print(f"{Colors.RED}SMTP not configured in config.yaml. Aborting.{Colors.END}")
        return 1

    if not os.path.exists(PROFILE_PATH):
        print(f"{Colors.RED}Candidate profile not found: {PROFILE_PATH}{Colors.END}")
        return 1

    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        candidate_profile = json.load(f)

    candidate_email = candidate_profile.get("personal_info", {}).get("email")
    if not candidate_email:
        print(f"{Colors.RED}Candidate email not set in profile.{Colors.END}")
        return 1

    # Initialize LLM (for Anschreiben generation)
    init_gemini()

    # Set up output capture for DB logging
    tee = TeeStdout()

    # Launch browser and fetch job page
    print(f"\n{Colors.BLUE}Launching headless browser to fetch job page...{Colors.END}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Extract page text
            job_text = page.evaluate("() => document.body.innerText") or ""
            browser.close()

            if not job_text.strip():
                print(f"{Colors.RED}Could not extract text from job page.{Colors.END}")
                return 1

            # Detect Cloudflare / bot-blocking pages
            cloudflare_markers = [
                "Cloudflare", "Just a moment", "Checking your browser",
                "DDoS protection", "captcha",
            ]
            if any(m.lower() in job_text.lower() for m in cloudflare_markers):
                print(f"{Colors.RED}⚠️  Job page blocked by Cloudflare (anti-bot protection).{Colors.END}")
                print(f"{Colors.YELLOW}   Indeed and some sites block headless browsers. Try the URL in a regular browser.{Colors.END}")
                return 1

            print(f"{Colors.GREEN}Job page fetched: {len(job_text)} chars of text.{Colors.END}")

    except Exception as e:
        print(f"{Colors.RED}Failed to fetch job page: {e}{Colors.END}")
        return 1

    # Extract contact info
    contact = extract_contact_info(job_text)
    if not contact or not contact.get("email"):
        print(f"{Colors.YELLOW}No employer email found in job text — fallback to candidate.{Colors.END}")
        contact = {"email": candidate_email, "recruiter_name": None}
        fallback_mode = True
    else:
        print(f"{Colors.GREEN}Found contact email: {contact['email']}{Colors.END}")
        if contact.get("recruiter_name"):
            print(f"{Colors.GREEN}Found recruiter name: {contact['recruiter_name']}{Colors.END}")
        fallback_mode = False

    # Generate Anschreiben
    print(f"\n{Colors.BLUE}Generating Anschreiben...{Colors.END}")
    try:
        from agent import generate_anschreiben
    except ImportError as e:
        print(f"{Colors.RED}Failed to import agent.py: {e}{Colors.END}")
        return 1

    cv_text_raw = "Nicht verfügbar"
    try:
        cv_name = config["user_profile"].get("cv_path", "Lebenslauf_UserName.pdf")
        cv_file_path = os.path.join(os.path.dirname(__file__), cv_name)
        if os.path.exists(cv_file_path):
            import fitz
            doc = fitz.open(cv_file_path)
            cv_text_raw = ""
            for page in doc:
                cv_text_raw += page.get_text()
            doc.close()
            cv_text_raw = cv_text_raw.strip()
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not read CV PDF for Anschreiben: {e}{Colors.END}")
    ans_data = generate_anschreiben(candidate_profile, job_text, config, cv_text=cv_text_raw)
    if not ans_data:
        print(f"{Colors.RED}Failed to generate Anschreiben.{Colors.END}")
        return 1

    # Extract full_text for email/personalization (Phase 8: dict with full_text field)
    ans_text = ans_data.get("full_text", "") if isinstance(ans_data, dict) else str(ans_data)
    if not ans_text or ans_text == "Leider konnte kein Anschreiben generiert werden.":
        print(f"{Colors.RED}Failed to generate Anschreiben (empty text).{Colors.END}")
        return 1

    # Personalize if recruiter name found
    if not fallback_mode and contact.get("recruiter_name"):
        print(f"{Colors.BLUE}Personalizing Anschreiben for {contact['recruiter_name']}...{Colors.END}")
        ans_text = personalize_anschreiben(ans_text, contact["recruiter_name"])

    print(f"{Colors.GREEN}Anschreiben generated: {len(ans_text)} chars.{Colors.END}")

    # Generate and save Anschreiben PDF (needs Playwright browser context)
    print(f"{Colors.BLUE}Generating Anschreiben PDF...{Colors.END}")
    safe_company = "".join([c for c in company if c.isalnum() or c in (" ", "_")]).strip().replace(" ", "_")
    pdf_path = os.path.join(SRC_DIR, "output", f"Anschreiben_{safe_company}_retry.pdf")
    try:
        # Re-launch a minimal browser for PDF rendering
        with sync_playwright() as p:
            pdf_browser = p.chromium.launch(headless=True)
            pdf_page = pdf_browser.new_page()
            try:
                from agent import save_anschreiben_pdf
                save_anschreiben_pdf(ans_text, company, candidate_profile, pdf_path, browser_context=pdf_page.context)
                print(f"{Colors.GREEN}PDF saved: {pdf_path}{Colors.END}")
            finally:
                pdf_browser.close()
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not generate PDF: {e}. Proceeding without PDF attachment.{Colors.END}")
        pdf_path = ""

    # Collect attachments via pipeline helper
    print(f"{Colors.BLUE}Collecting attachments...{Colors.END}")
    pipeline = JobPipeline(workspace_dir=WORKSPACE_DIR)
    pipeline.initialize()
    attachments = pipeline._collect_candidate_docs()
    if pdf_path and os.path.exists(pdf_path):
        attachments.insert(0, pdf_path)

    if not attachments:
        print(f"{Colors.YELLOW}Warning: No attachments found (no CV PDF indexed?).{Colors.END}")

    # Generate candidate-only draft (GDPR: no auto-send, no employer)
    print(f"\n{Colors.BLUE}Generating candidate-only draft...{Colors.END}")
    candidate_contact = {
        "email": candidate_email,
        "recruiter_name": contact.get("recruiter_name", "") if contact else "",
    }
    from job_agent.email_draft_generator import generate_email_draft
    draft_path = generate_email_draft(
        smtp_config=smtp_config,
        candidate_profile=candidate_profile,
        contact=candidate_contact,
        anschreiben_text=ans_text,
        attachment_paths=attachments,
        job_title=title,
        company_name=company,
        url=url,
        terminal_output=tee.getvalue() if tee else None,
        is_candidate_copy=True,
    )

    if draft_path:
        new_status = "Draft Generated (Retry)"
        update_status(db_id, new_status, email_sent=1)
        # Save terminal output to DB
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            terminal = tee.getvalue() if tee else ""
            c.execute(
                "UPDATE applied_jobs SET terminal_output = ?, pdf_path = ? WHERE id = ?",
                (terminal, pdf_path if pdf_path else None, db_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        print(f"\n{Colors.GREEN}{'='*70}{Colors.END}")
        print(f"{Colors.GREEN}✅ Candidate draft generated: {draft_path}{Colors.END}")
        print(f"{Colors.YELLOW}📤 Bitte öffnen und manuell versenden.{Colors.END}")
        return 0
    else:
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}❌ Failed to generate candidate draft.{Colors.END}")
        return 1


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 retry_email.py <DB_ID>              # Retry a single entry")
        print("  python3 retry_email.py --list-failed         # List all failed entries")
        print("  python3 retry_email.py --retry-all-failed    # Retry all failed entries")
        sys.exit(1)

    if sys.argv[1] == "--list-failed":
        entries = list_failed_entries()
        if not entries:
            print(f"{Colors.GREEN}No failed email entries found.{Colors.END}")
        else:
            print(f"{Colors.CYAN}Found {len(entries)} failed email entries:{Colors.END}\n")
            for e in entries:
                print(f"  ID={e['id']:>4} | {e['company_name'][:35]:<35} | {e['job_title'][:45]:<45} | {e['status']}")
        sys.exit(0)

    if sys.argv[1] == "--retry-all-failed":
        entries = list_failed_entries()
        if not entries:
            print(f"{Colors.GREEN}No failed email entries to retry.{Colors.END}")
            sys.exit(0)

        print(f"{Colors.CYAN}Retrying {len(entries)} failed entries...{Colors.END}")
        results = {"ok": 0, "fail": 0, "skip": 0}
        for e in entries:
            rc = retry_single(e["id"])
            if rc == 0:
                results["ok"] += 1
            elif rc == 1:
                results["fail"] += 1
            else:
                results["skip"] += 1

        print(f"\n{Colors.CYAN}{'='*70}{Colors.END}")
        print(f"{Colors.CYAN}Done: {results['ok']} sent, {results['fail']} failed, {results['skip']} skipped{Colors.END}")
        sys.exit(0 if results["fail"] == 0 else 1)

    # Single ID mode
    try:
        db_id = int(sys.argv[1])
    except ValueError:
        print(f"{Colors.RED}Error: '{sys.argv[1]}' is not a valid DB ID.{Colors.END}")
        sys.exit(1)

    sys.exit(retry_single(db_id))


if __name__ == "__main__":
    main()
