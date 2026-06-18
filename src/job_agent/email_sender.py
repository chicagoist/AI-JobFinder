from job_agent.utils import sanitize_header
# -*- coding: utf-8 -*-
import os
import sys
import ssl
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from job_agent.utils import Colors, clean_ansi_escape_codes

def send_pending_emails(config, candidate_profile, conn):
    print(f"\n{Colors.BLUE}--- Processing pending job application emails ---{Colors.END}")
    
    # 1. Retrieve and validate SMTP configuration
    smtp_config = config.get("smtp", {})
    smtp_host = smtp_config.get("host")
    smtp_port = smtp_config.get("port")
    smtp_user = smtp_config.get("username")
    smtp_pass = smtp_config.get("password")
    
    # Check for empty or template values
    if not smtp_host or not smtp_port or not smtp_user or not smtp_pass or "<YOUR_SMTP_PASSWORD" in smtp_pass or "<Username>" in smtp_user:
        print(f"{Colors.YELLOW}Warning: SMTP settings are not fully configured in config.yaml. Skipping email delivery.{Colors.END}")
        print(f"Please configure the 'smtp' section in your config.yaml file.")
        return
        
    # Retrieve recipient email from candidate profile
    candidate_email = candidate_profile.get("personal_info", {}).get("email")
    if not candidate_email:
        print(f"{Colors.RED}Error: Candidate email address is missing in candidate_profile.json. Skipping email delivery.{Colors.END}")
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
        print(f"{Colors.GREEN}No pending applications to email.{Colors.END}")
        return

    print(f"Found {len(rows)} pending application(s) to email.")

    # Pre-build packages: list of (db_id, msg, zip_path_or_None)
    packages = []
    for row in rows:
        db_id, company_name, job_title, url, score, applied_date, terminal_output, pdf_path = row
        print(f"\nPackaging application {db_id}: {Colors.CYAN}{job_title} at {company_name}{Colors.END}...")
        
        clean_log = clean_ansi_escape_codes(terminal_output or "")
        if not clean_log:
            clean_log = "No console output captured."
        
        clean_subj = sanitize_header(f"Bewerbung: {job_title} bei {company_name}")
        sender_name = sanitize_header(pi.get("name", "JobAgent"))
        
        msg = MIMEMultipart()
        msg['From'] = f"{sender_name} <{smtp_user}>"
        msg['To'] = candidate_email
        msg['Subject'] = clean_subj
        
        # Body = full terminal output for this vacancy
        msg.attach(MIMEText(clean_log, 'plain', 'utf-8'))
        
        # Attach Anschreiben PDF
        if pdf_path and os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(pdf_path)}"')
                    msg.attach(part)
            except Exception as e:
                print(f"{Colors.RED}Failed to attach Anschreiben PDF: {e}{Colors.END}")
        else:
            print(f"{Colors.YELLOW}Warning: Anschreiben PDF '{pdf_path}' not found on disk.{Colors.END}")
        
        # Attach CV (Lebenslauf) — newest only
        cursor2 = conn.cursor()
        cursor2.execute(
            "SELECT file_path FROM candidate_files WHERE classification = 'Lebenslauf' ORDER BY mtime DESC LIMIT 1"
        )
        cv_row = cursor2.fetchone()
        if cv_row:
            cv_abs = cv_row[0]
            if not os.path.isabs(cv_abs):
                cv_abs = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), cv_abs))
            if os.path.exists(cv_abs):
                try:
                    with open(cv_abs, "rb") as f:
                        part = MIMEBase("application", "pdf")
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(cv_abs)}"')
                        msg.attach(part)
                except Exception as e:
                    print(f"{Colors.RED}Failed to attach CV: {e}{Colors.END}")
        
        # Attach all Zertifikat/Diplom/Zeugnis/Arbeitszeugnis PDFs (all score-influencing documents)
        cursor2.execute(
            "SELECT file_path FROM candidate_files WHERE classification IN ('Zertifikat', 'Diplom', 'Zeugnis', 'Arbeitszeugnis')"
        )
        for (doc_path,) in cursor2.fetchall():
            doc_abs = doc_path
            if not os.path.isabs(doc_abs):
                doc_abs = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), doc_abs))
            if not os.path.exists(doc_abs):
                continue
            _, ext = os.path.splitext(doc_abs)
            if ext.lower() not in ('.pdf', '.png', '.jpg', '.jpeg'):
                continue
            try:
                with open(doc_abs, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(doc_abs)}"')
                    msg.attach(part)
            except Exception as e:
                print(f"{Colors.RED}Failed to attach {os.path.basename(doc_abs)}: {e}{Colors.END}")
        
        packages.append((db_id, msg, None))
    
    if not packages:
        print(f"{Colors.YELLOW}No packages built successfully.{Colors.END}")
        print(f"{Colors.BLUE}--- Email processing finished ---{Colors.END}\n")
        return
    
    # Single SMTP session for all emails
    import time
    time.sleep(10.0)
    ssl_ctx = ssl.create_default_context()
    try:
        ports_to_try = [int(smtp_port), 465] if int(smtp_port) != 465 else [465]
    except (TypeError, ValueError):
        print(f"{Colors.YELLOW}Warning: Invalid SMTP port '{smtp_port}'. Skipping email delivery.{Colors.END}")
        print(f"{Colors.BLUE}--- Email processing finished ---{Colors.END}")
        return
    server = None

    def _try_connect():
        for port_attempt, port in enumerate(ports_to_try):
            if port_attempt > 0:
                print(f"{Colors.YELLOW}Trying alternate port {port} (SSL)...{Colors.END}")
            for attempt in range(2):
                try:
                    print(f"Connecting to SMTP server {smtp_host}:{port} as {smtp_user} (attempt {attempt+1}/2)...")
                    if port == 465:
                        srv = smtplib.SMTP_SSL(str(smtp_host), port, timeout=20, context=ssl_ctx)
                    else:
                        srv = smtplib.SMTP(str(smtp_host), port, timeout=20)
                        code, _ = srv.ehlo()
                        if code < 200 or code >= 300:
                            code, _ = srv.helo()
                        code, _ = srv.starttls(context=ssl_ctx)
                        if code < 200 or code >= 300:
                            print(f"{Colors.YELLOW}STARTTLS returned {code}, continuing anyway...{Colors.END}")
                        srv.ehlo()
                    srv.login(str(smtp_user), str(smtp_pass))
                    return srv
                except smtplib.SMTPServerDisconnected as e:
                    print(f"{Colors.RED}SMTP disconnected (attempt {attempt+1}): {e}. Retrying...{Colors.END}")
                    time.sleep(3.0)
                except smtplib.SMTPAuthenticationError as e:
                    print(f"{Colors.RED}SMTP authentication failed: {e}. Check your Google App Password.{Colors.END}")
                    return None
                except (TimeoutError, OSError) as e:
                    print(f"{Colors.RED}SMTP connection error (attempt {attempt+1}): {e}. Retrying...{Colors.END}")
                    time.sleep(3.0)
                except Exception as e:
                    print(f"{Colors.RED}Error connecting SMTP (attempt {attempt+1}): {type(e).__name__}: {e}{Colors.END}")
                    if attempt == 1:
                        break
                    time.sleep(3.0)
        return None

    server = _try_connect()
    if server is None:
        print(f"{Colors.RED}Failed to connect to SMTP server. Emails will not be sent.{Colors.END}")
        print(f"{Colors.BLUE}--- Email processing finished ---{Colors.END}\n")
        return

    try:
        for db_id, msg, zip_path in packages:
            try:
                server.sendmail(str(smtp_user), [candidate_email], msg.as_string())
                print(f"{Colors.GREEN}Email sent successfully to {candidate_email} (job {db_id})!{Colors.END}")
                cursor.execute("UPDATE applied_jobs SET email_sent = 1 WHERE id = ?", (db_id,))
                conn.commit()
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except smtplib.SMTPServerDisconnected as e:
                print(f"{Colors.RED}SMTP disconnected while sending job {db_id}: {e}. Skipping remaining...{Colors.END}")
                break
            except Exception as e:
                print(f"{Colors.RED}Error sending email for job {db_id}: {type(e).__name__}: {e}. Skipping...{Colors.END}")
    finally:
        try:
            server.quit()
        except Exception:
            pass
            
    print(f"{Colors.BLUE}--- Email processing finished ---{Colors.END}\n")
