"""Email sender — generates batch digest draft files instead of sending via SMTP.
GDPR compliance: no automatic email sending, only .eml/.txt files for manual review."""

# -*- coding: utf-8 -*-
import os
import sys
import sqlite3
from job_agent.utils import Colors, clean_ansi_escape_codes
from job_agent.email_draft_generator import generate_candidate_digest_draft


def send_pending_emails(config, candidate_profile, conn):
    """Generate draft .eml files for all pending applications.

    Replaces the old SMTP-based send_pending_emails(). Creates a digest
    .eml file in drafts/ with all pending applications as attachments.
    The user opens and sends manually.
    """
    print(f"\n{Colors.BLUE}--- Processing pending job application drafts ---{Colors.END}")

    # Retrieve recipient email from candidate profile
    candidate_email = candidate_profile.get("personal_info", {}).get("email")
    if not candidate_email:
        print(f"{Colors.RED}Error: Candidate email address is missing in candidate_profile.json. Skipping.{Colors.END}")
        return
    pi = candidate_profile.get("personal_info", {})

    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, company_name, job_title, url, score, applied_date, terminal_output, pdf_path 
            FROM applied_jobs 
            WHERE (status = 'Applied' OR status LIKE 'Applied (Direct Email%' OR status LIKE 'Applied (Email%') AND email_sent = 0
        """)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"{Colors.RED}Database error reading applied_jobs: {e}{Colors.END}")
        return

    if not rows:
        print(f"{Colors.GREEN}No pending applications to draft.{Colors.END}")
        return

    print(f"Found {len(rows)} pending application(s) to draft.")

    smtp_config = config.get("smtp", {})

    draft_path = generate_candidate_digest_draft(
        smtp_config=smtp_config,
        candidate_profile=candidate_profile,
        candidate_email=candidate_email,
        rows=rows,
        conn=conn,
    )

    if draft_path:
        print(f"{Colors.GREEN}✅ Übersichts-Entwurf erstellt: {draft_path}{Colors.END}")
        print(f"{Colors.YELLOW}📤 Bitte öffnen und manuell versenden.{Colors.END}")
    else:
        print(f"{Colors.RED}Fehler beim Erstellen des Übersichts-Entwurfs.{Colors.END}")

    print(f"{Colors.BLUE}--- Draft generation finished ---{Colors.END}\n")
