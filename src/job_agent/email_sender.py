"""Email sender — sends per-job SMTP to candidate + generates batch digest drafts.
GDPR: SMTP sending is ONLY to the candidate's own email (data subject), never to recruiters."""

# -*- coding: utf-8 -*-
import os
import sys
import smtplib
import sqlite3
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional
from job_agent.utils import Colors, sanitize_header, clean_ansi_escape_codes
from job_agent.email_draft_generator import generate_candidate_digest_draft


def send_candidate_email(
    smtp_config: dict,
    candidate_profile: dict,
    company: str,
    job_title: str,
    anschreiben_txt_path: Optional[str],
    anschreiben_pdf_path: Optional[str],
    lebenslauf_path: Optional[str],
    cert_paths: list[str],
    terminal_output: str,
    url: Optional[str] = None,
) -> bool:
    """Send a per-job SMTP email to the candidate's own email address.

    This is GDPR-compliant: the candidate (data subject) receives their own
    application data. NEVER sends to recruiters/employers.

    Attachments: Anschreiben.txt + Anschreiben.pdf + Lebenslauf.pdf + relevant certs only.
    Body: metadata (company, job title, URL) + full terminal output (cleaned of ANSI codes).
    """
    candidate_email = candidate_profile.get("personal_info", {}).get("email")
    if not candidate_email:
        print(f"{Colors.RED}[send_candidate_email] No candidate email configured.{Colors.END}")
        return False

    pi = candidate_profile.get("personal_info", {})
    sender_name = sanitize_header(
        " ".join(filter(None, [pi.get("first_name", ""), pi.get("last_name", "")]))
    ) or sanitize_header(pi.get("name", "Bewerber"))

    smtp_host = smtp_config.get("host", "")
    smtp_port = smtp_config.get("port", 587)
    smtp_user = smtp_config.get("username", "")
    smtp_pass = smtp_config.get("password", "")
    use_tls = smtp_config.get("use_tls", True)

    if not smtp_host or not smtp_user:
        print(f"{Colors.RED}[send_candidate_email] SMTP not configured (host/user missing).{Colors.END}")
        return False

    # Build MIME message
    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{smtp_user}>"
    msg["To"] = candidate_email
    subject = f"Bewerbung als {sanitize_header(job_title)} bei {sanitize_header(company)}"
    msg["Subject"] = sanitize_header(subject)

    # Body: metadata + cleaned terminal output
    meta = f"Bewerbung als {sanitize_header(job_title)} bei {sanitize_header(company)}\n"
    if url:
        meta += f"URL: {url}\n"
    meta += f"\n---\n\n"
    body = meta + clean_ansi_escape_codes(terminal_output or "")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attach files
    attachment_paths = []
    if anschreiben_pdf_path and os.path.exists(anschreiben_pdf_path):
        attachment_paths.append(anschreiben_pdf_path)
    if anschreiben_txt_path and os.path.exists(anschreiben_txt_path):
        attachment_paths.append(anschreiben_txt_path)
    if lebenslauf_path and os.path.exists(lebenslauf_path):
        attachment_paths.append(lebenslauf_path)
    for p in cert_paths:
        if os.path.exists(p) and p not in attachment_paths:
            attachment_paths.append(p)

    for file_path in attachment_paths:
        try:
            with open(file_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                filename = os.path.basename(file_path)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                msg.attach(part)
        except Exception as e:
            print(f"{Colors.YELLOW}[send_candidate_email] Failed to attach {file_path}: {e}{Colors.END}")

    # Send via SMTP
    try:
        if use_tls:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [candidate_email], msg.as_string())
        server.quit()
        print(f"{Colors.GREEN}✅ SMTP sent to {candidate_email}: {subject}{Colors.END}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"{Colors.RED}[send_candidate_email] SMTP auth failed for {smtp_user}. Check credentials.{Colors.END}")
    except smtplib.SMTPException as e:
        print(f"{Colors.RED}[send_candidate_email] SMTP error: {e}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}[send_candidate_email] Failed: {type(e).__name__}: {e}{Colors.END}")
    return False


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
