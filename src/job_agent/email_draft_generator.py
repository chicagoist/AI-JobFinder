"""Generate email draft files (.eml and .txt) instead of sending via SMTP.
GDPR compliance measure — no automatic email sending, all output is manual-review drafts."""

import os
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from job_agent.utils import Colors, sanitize_header, clean_ansi_escape_codes
from typing import Optional


def _build_msg(
    sender_name: str,
    smtp_user: str,
    to_email: str,
    body_text: str,
    attachment_paths: list[str],
    subject: str,
) -> MIMEMultipart:
    """Build a MIME multipart message (same as before, no SMTP involved)."""
    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{smtp_user}>"
    msg["To"] = to_email
    msg["Subject"] = sanitize_header(subject)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    for file_path in attachment_paths:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                filename = os.path.basename(file_path)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                msg.attach(part)
        except Exception:
            pass
    return msg


def generate_email_draft(
    smtp_config: dict,
    candidate_profile: dict,
    contact: dict,
    anschreiben_text: str,
    attachment_paths: list[str],
    job_title: str,
    company_name: str,
    url: Optional[str] = None,
    terminal_output: Optional[str] = None,
    is_candidate_copy: bool = False,
) -> Optional[str]:
    """Create .eml and .txt draft files in drafts/ directory.

    Returns path to the .eml file, or None if draft could not be created.
    No SMTP sending — the user opens and sends the draft manually.

    Parameters mirror the old send_direct_email() signature for a clean swap.
    """
    # Determine output directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    drafts_dir = os.path.join(base_dir, "drafts")
    os.makedirs(drafts_dir, exist_ok=True)

    # Build sender info from profile
    pi = candidate_profile.get("personal_info", {})
    sender_name = sanitize_header(
        " ".join(filter(None, [pi.get("first_name", ""), pi.get("last_name", "")]))
    )
    if not sender_name:
        sender_name = sanitize_header(pi.get("name", "Bewerber"))

    smtp_user = smtp_config.get("username", "bewerber@example.com")

    recipient_email = contact.get("email", "")
    if not recipient_email:
        print(f"{Colors.RED}No recipient email. Cannot generate draft.{Colors.END}")
        return None

    # Determine body text
    if is_candidate_copy and terminal_output:
        body_text = terminal_output  # full terminal log for candidate
    else:
        body_text = anschreiben_text  # Anschreiben text for recruiter

    # Build subject
    clean_job_title = sanitize_header(job_title)
    clean_company_name = sanitize_header(company_name)
    subject = f"Bewerbung: {clean_job_title} bei {clean_company_name}"
    if is_candidate_copy:
        subject = f"[KOPIE] {subject}"

    # Add recruiter/URL metadata to body for candidate copy
    if is_candidate_copy:
        recruiter = contact.get("recruiter_name")
        if recruiter:
            recruiter = recruiter.splitlines()[0].strip()
        meta = f"[KOPIE / COPY]\n\nBewerbung wurde von Ihrem JobAgent erstellt:\n"
        meta += f"  • Unternehmen: {clean_company_name}\n"
        meta += f"  • Position:    {clean_job_title}\n"
        if recruiter:
            meta += f"  • Ansprechpartner: {recruiter}\n"
        meta += f"  • Email:       {recipient_email}\n"
        if url:
            meta += f"  • URL:         {url}\n"
        meta += f"\n---\n\n{body_text}"
        body_text = meta

    # Build the MIME message
    msg = _build_msg(sender_name, smtp_user, recipient_email, body_text, attachment_paths, subject)

    # Safe filename
    safe_company = "".join(c for c in company_name if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    prefix = "KOPIE_" if is_candidate_copy else ""
    filename_base = f"{prefix}Bewerbung_{safe_company}_{date_str}"

    eml_path = os.path.join(drafts_dir, f"{filename_base}.eml")
    txt_path = os.path.join(drafts_dir, f"{filename_base}.txt")

    try:
        with open(eml_path, "wb") as f:
            f.write(msg.as_bytes())
        print(f"{Colors.GREEN}📧 E-Mail-Entwurf gespeichert: {eml_path}{Colors.END}")

        # Plain-text copy for quick preview
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"TO: {recipient_email}\n")
            f.write(f"FROM: {sender_name} <{smtp_user}>\n")
            f.write(f"SUBJECT: {subject}\n")
            f.write(f"ATTACHMENTS:\n")
            for p in attachment_paths:
                if os.path.exists(p):
                    f.write(f"  - {os.path.basename(p)}\n")
            f.write(f"\n---\n\n{body_text}\n")
        print(f"{Colors.GREEN}📄 Text-Entwurf gespeichert: {txt_path}{Colors.END}")
        print(f"{Colors.YELLOW}⚠️  Bitte öffnen und manuell versenden (kein automatischer Versand).{Colors.END}")

        return eml_path
    except Exception as e:
        print(f"{Colors.RED}Fehler beim Speichern des Entwurfs: {e}{Colors.END}")
        return None


def generate_candidate_digest_draft(
    smtp_config: dict,
    candidate_profile: dict,
    candidate_email: str,
    rows: list,
    conn,
) -> Optional[str]:
    """Generate a single digest .eml with all pending applications.

    Args:
        rows: list of (db_id, company_name, job_title, url, score, applied_date, terminal_output, pdf_path)
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    drafts_dir = os.path.join(base_dir, "drafts")
    os.makedirs(drafts_dir, exist_ok=True)

    pi = candidate_profile.get("personal_info", {})
    sender_name = sanitize_header(
        " ".join(filter(None, [pi.get("first_name", ""), pi.get("last_name", "")]))
    ) or sanitize_header(pi.get("name", "JobAgent"))
    smtp_user = smtp_config.get("username", "bewerber@example.com")
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    # Build digest body
    digest_lines = [f"Bewerbungs-Übersicht vom {date_str}", "=" * 50, ""]
    attachment_paths = []

    for row in rows:
        db_id, company_name, job_title, url, score, applied_date, terminal_output, pdf_path = row
        digest_lines.append(f"--- {job_title} bei {company_name} ---")
        digest_lines.append(f"  Score: {score}/10")
        digest_lines.append(f"  URL:   {url}")
        digest_lines.append(f"  Datum: {applied_date}")
        digest_lines.append("")

        # Attach the Anschreiben PDF
        if pdf_path and os.path.exists(pdf_path):
            if pdf_path not in attachment_paths:
                attachment_paths.append(pdf_path)

        # Add terminal output
        clean_log = clean_ansi_escape_codes(terminal_output or "")
        if clean_log:
            digest_lines.append(f"  Terminal-Ausgabe:")
            digest_lines.append(f"  {clean_log[:2000]}")
            if len(clean_log) > 2000:
                digest_lines.append(f"  ... ({len(clean_log)} Zeichen insgesamt)")
            digest_lines.append("")

    # Attach CV + all certs
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_path FROM candidate_files WHERE classification = 'Lebenslauf' ORDER BY mtime DESC LIMIT 1"
    )
    cv_row = cursor.fetchone()
    if cv_row:
        cv_abs = cv_row[0]
        if not os.path.isabs(cv_abs):
            cv_abs = os.path.normpath(os.path.join(base_dir, cv_abs))
        if os.path.exists(cv_abs) and cv_abs not in attachment_paths:
            attachment_paths.append(cv_abs)

    cursor.execute(
        "SELECT file_path FROM candidate_files WHERE classification IN ('Zertifikat', 'Diplom', 'Zeugnis', 'Arbeitszeugnis')"
    )
    for (doc_path,) in cursor.fetchall():
        doc_abs = doc_path
        if not os.path.isabs(doc_abs):
            doc_abs = os.path.normpath(os.path.join(base_dir, doc_abs))
        if os.path.exists(doc_abs) and doc_abs not in attachment_paths:
            _, ext = os.path.splitext(doc_abs)
            if ext.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
                attachment_paths.append(doc_abs)

    digest_text = "\n".join(digest_lines)
    subject = f"Bewerbungs-Übersicht vom {date_str} ({len(rows)} Stellen)"

    msg = _build_msg(sender_name, smtp_user, candidate_email, digest_text, attachment_paths, subject)

    eml_path = os.path.join(drafts_dir, f"BewerbungsUebersicht_{date_str}.eml")
    txt_path = os.path.join(drafts_dir, f"BewerbungsUebersicht_{date_str}.txt")

    try:
        with open(eml_path, "wb") as f:
            f.write(msg.as_bytes())
        print(f"{Colors.GREEN}📧 Übersichts-Entwurf gespeichert: {eml_path}{Colors.END}")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(digest_text)
        print(f"{Colors.GREEN}📄 Text-Übersicht gespeichert: {txt_path}{Colors.END}")
        print(f"{Colors.YELLOW}⚠️  Bitte öffnen und manuell versenden.{Colors.END}")

        # Mark all as email_sent=1 (draft generated)
        for row in rows:
            try:
                cursor.execute("UPDATE applied_jobs SET email_sent = 1 WHERE id = ?", (row[0],))
            except Exception:
                pass
        conn.commit()

        return eml_path
    except Exception as e:
        print(f"{Colors.RED}Fehler beim Speichern des Übersichts-Entwurfs: {e}{Colors.END}")
        return None
