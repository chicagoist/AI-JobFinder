from typing import Optional

from job_agent.utils import sanitize_header
import os
import re
import json
import ssl
import smtplib
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from job_agent.utils import Colors
from job_agent.config import PROMPTS
from job_agent.llm import llm_request_with_fallback, init_gemini

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

def _looks_like_name(text: str) -> bool:
    words = text.strip().split()
    if len(words) < 1 or len(words) > 3:
        return False
    for w in words:
        w_clean = w.strip(".,-–()\"'")
        if len(w_clean) < 2 or len(w_clean) > 30:
            return False
        if w_clean[0].islower():
            return False
    stopwords = {'Bewerbung', 'Email', 'Mail', 'Kontakt', 'Contact', 'Ansprechpartner',
                 'Recruiter', 'HR', 'Bitte', 'Per', 'Die', 'Der', 'Das', 'Mit', 'Für',
                 'Und', 'Oder', 'Bei', 'Auf', 'Ihre', 'Ihren', 'Ihrer', 'Sie', 'Wir',
                 'Tel', 'Telefon', 'Fax', 'Mobil', 'Mobiltelefon', 'Herr', 'Frau'}
    first_word = words[0].strip(".,-–()\"'")
    if first_word in stopwords:
        return False
    return True

NAME_REGEX = re.compile(
    r'(?:(?:Ansprechpartner|Ansprechpartnerin|Kontakt|contact|recruiter|HR|Ansprechpartner\s+für\s+Bewerbungen|Ihr\s+Ansprechpartner|bei\s+Rückfragen)\s*[:\-–]?\s*'
    r'([A-Z][A-Za-zÀ-ÖØ-öø-ÿ]+(?:[ \t][A-Z][A-Za-zÀ-ÖØ-öø-ÿ]+){0,2}))'
)

def extract_contact_info(job_text: str) -> dict | None:
    emails = EMAIL_REGEX.findall(job_text)
    if not emails:
        return None
    email = emails[0].strip()
    recruiter_name = None
    for name_match in NAME_REGEX.finditer(job_text):
        candidate = name_match.group(1).strip()
        if not EMAIL_REGEX.match(candidate) and _looks_like_name(candidate):
            recruiter_name = candidate
            break
    if not recruiter_name:
        try:
            init_gemini()
            prompt = PROMPTS.get("extract_recruiter_prompt", "").format(
                job_text=job_text[:3000],
                email=email
            )
            if prompt:
                resp = llm_request_with_fallback(prompt)
                if resp and resp.text.strip():
                    name = resp.text.strip()
                    if name and len(name) < 100 and not name.startswith('{') and not name.startswith('['):
                        recruiter_name = name
        except Exception:
            pass
    return {"email": email, "recruiter_name": recruiter_name}

def personalize_anschreiben(text: str, recruiter_name: str) -> str:
    if not recruiter_name:
        return text
    name = recruiter_name.strip().split('\n')[0].strip()
    if not name:
        return text
    name_lower = name.lower()
    if name_lower.startswith("herr "):
        greeting = f"Sehr geehrter {name[5:]},"
    elif name_lower.startswith("frau "):
        greeting = f"Sehr geehrte {name[5:]},"
    else:
        greeting = f"Guten Tag {name},"
    text = re.sub(
        r'Sehr geehrte (?:Damen und Herren|Damen\s+und\s+Herren|Herren|Damen)\s*,',
        greeting,
        text,
        count=1,
        flags=re.IGNORECASE
    )
    return text

def _resolve_path(p: str, base_dir: Optional[str] = None) -> str:
    """Resolve a relative path using base_dir when os.getcwd() may differ."""
    if not p:
        return p
    if os.path.isabs(p):
        return p
    if base_dir:
        return os.path.normpath(os.path.join(base_dir, p))
    # If relative and no base_dir, try to guess: if CWD is project root, prepend src/
    return os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p))

def collect_relevant_attachments(conn: sqlite3.Connection, job_text: str, anschreiben_pdf_path: str, workspace_dir: Optional[str] = None) -> list[str]:
    attachments = []
    cursor = conn.cursor()
    # Only the newest Lebenslauf
    cursor.execute(
        "SELECT file_path, parsed_json FROM candidate_files WHERE classification = 'Lebenslauf' ORDER BY mtime DESC LIMIT 1"
    )
    cv_row = cursor.fetchone()
    if cv_row:
        cv_abs = _resolve_path(cv_row[0], workspace_dir)
        if os.path.exists(cv_abs):
            attachments.append(cv_abs)
    # All Zertifikat/Diplom/Zeugnis/Arbeitszeugnis (include all, not just keyword-matched)
    cursor.execute(
        "SELECT file_path, classification, parsed_json FROM candidate_files WHERE classification IN ('Zertifikat', 'Diplom', 'Zeugnis', 'Arbeitszeugnis')"
    )
    for file_path, classification, parsed_json_str in cursor.fetchall():
        f_abs = _resolve_path(file_path, workspace_dir)
        if not os.path.exists(f_abs):
            continue
        _, ext = os.path.splitext(f_abs)
        if ext.lower() not in ('.pdf', '.png', '.jpg', '.jpeg'):
            continue
        if f_abs not in attachments:
            attachments.append(f_abs)
    if anschreiben_pdf_path and os.path.exists(anschreiben_pdf_path):
        if anschreiben_pdf_path not in attachments:
            attachments.insert(0, anschreiben_pdf_path)
    return attachments

def send_direct_email(smtp_config: dict, candidate_profile: dict, contact: dict,
                      anschreiben_text: str, attachment_paths: list[str],
                      job_title: str, company_name: str, url: Optional[str] = None) -> bool:
    server = None
    smtp_host = smtp_config.get("host")
    smtp_port = smtp_config.get("port")
    smtp_user = smtp_config.get("username")
    smtp_pass = smtp_config.get("password")
    
    if not smtp_host or not smtp_port or not smtp_user or not smtp_pass:
        print(f"{Colors.YELLOW}Warning: SMTP not configured. Skipping direct email.{Colors.END}")
        return False
    if "<" in str(smtp_pass) or "<" in str(smtp_user):
        print(f"{Colors.YELLOW}Warning: SMTP credentials contain placeholders. Skipping direct email.{Colors.END}")
        return False
        
    # Sanitize inputs for headers
    clean_job_title = sanitize_header(job_title)
    clean_company_name = sanitize_header(company_name)
    
    pi = candidate_profile.get("personal_info", {})
    sender_name = sanitize_header(" ".join(filter(None, [pi.get("first_name", ""), pi.get("last_name", "")])))
    if not sender_name:
        sender_name = sanitize_header(pi.get("name", "Bewerber"))
    
    recipient_email = contact.get("email", "")
    if not recipient_email:
        print(f"{Colors.RED}No recipient email to send to.{Colors.END}")
        return False

    def _build_msg(to_email: str, body_text: str, subject_prefix: str = "") -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = f"{sender_name} <{smtp_user}>"
        msg["To"] = to_email
        subj = f"Bewerbung: {clean_job_title} bei {clean_company_name}"
        if subject_prefix:
            subj = f"{subject_prefix} {subj}"
        msg["Subject"] = sanitize_header(subj)
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

    def _try_connect():
        ssl_ctx = ssl.create_default_context()
        try:
            ports_to_try = [int(smtp_port), 465] if int(smtp_port) != 465 else [465]
        except (TypeError, ValueError):
            print(f"{Colors.YELLOW}Warning: Invalid SMTP port '{smtp_port}'. Skipping direct email.{Colors.END}")
            return False
        for port_attempt, port in enumerate(ports_to_try):
            if port_attempt > 0:
                print(f"{Colors.YELLOW}Trying alternate port {port} (SSL)...{Colors.END}")
            for attempt in range(2):
                try:
                    if port == 465:
                        srv = smtplib.SMTP_SSL(str(smtp_host), port, timeout=20, context=ssl_ctx)
                    else:
                        srv = smtplib.SMTP(str(smtp_host), port, timeout=20)
                        srv.ehlo()
                        srv.starttls(context=ssl_ctx)
                        srv.ehlo()
                    srv.login(str(smtp_user), str(smtp_pass))
                    return srv
                except (smtplib.SMTPServerDisconnected, smtplib.SMTPHeloError) as e:
                    print(f"{Colors.RED}SMTP connection failed (port {port}, attempt {attempt+1}): {e}. Retrying...{Colors.END}")
                    import time
                    time.sleep(2.0)
                except smtplib.SMTPAuthenticationError as e:
                    print(f"{Colors.RED}SMTP authentication failed: {e}. Check your Google App Password.{Colors.END}")
                    return None
                except (TimeoutError, OSError) as e:
                    print(f"{Colors.RED}SMTP connection timeout/error (port {port}, attempt {attempt+1}): {e}. Retrying...{Colors.END}")
                    import time
                    time.sleep(2.0)
                except Exception as e:
                    print(f"{Colors.RED}Error connecting SMTP (port {port}, attempt {attempt+1}): {type(e).__name__}: {e}{Colors.END}")
                    if attempt == 1:
                        break
                    import time
                    time.sleep(2.0)
        return None

    def _send_with_reconnect(to_email: str, body_text: str, label: str, subject_prefix: str = "") -> bool:
        import time
        nonlocal server
        for send_attempt in range(3):
            try:
                if server is None:
                    server = _try_connect()
                    if server is None: return False
                
                msg = _build_msg(to_email, body_text, subject_prefix)
                server.sendmail(str(smtp_user), [to_email], msg.as_string())
                print(f"{Colors.GREEN}Direct email sent to {to_email} ({label}) for {clean_job_title} at {clean_company_name}!{Colors.END}")
                return True
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPSenderRefused) as e:
                print(f"{Colors.RED}SMTP disconnected or refused while sending {label} (attempt {send_attempt+1}/3): {e}. Reconnecting...{Colors.END}")
                time.sleep(2.0)
                try:
                    if server: server.quit()
                except Exception: pass
                server = _try_connect()
                if server is None:
                    return False
            except smtplib.SMTPAuthenticationError as e:
                print(f"{Colors.RED}SMTP authentication failed ({label}): {e}. Check your Google App Password.{Colors.END}")
                return False
            except Exception as e:
                print(f"{Colors.RED}Error sending email ({label}) to {to_email}: {type(e).__name__}: {e}{Colors.END}")
                return False
        return False

    import time
    time.sleep(2.0)
    print(f"{Colors.BLUE}Connecting to SMTP {smtp_host}:{smtp_port}...{Colors.END}")
    server = _try_connect()
    if server is None:
        return False

    try:
        ok = _send_with_reconnect(recipient_email, anschreiben_text, "primary")
        if not ok:
            return False

        candidate_email = candidate_profile.get("personal_info", {}).get("email")
        if candidate_email and recipient_email != candidate_email:
            recruiter = contact.get("recruiter_name")
            if recruiter:
                recruiter = recruiter.split('\n')[0].strip()
            cc_info = f"[KOPIE / COPY]\n\n"
            cc_info += f"Bewerbung wurde von Ihrem JobAgent gesendet:\n"
            cc_info += f"  • Unternehmen: {clean_company_name}\n"
            cc_info += f"  • Position:    {clean_job_title}\n"
            if recruiter:
                cc_info += f"  • Ansprechpartner: {recruiter}\n"
            cc_info += f"  • Email:       {recipient_email}\n"
            if url:
                cc_info += f"  • URL:         {url}\n"
            cc_info += f"\n---\n\n{anschreiben_text}"
            _send_with_reconnect(candidate_email, cc_info, "CC candidate", "[KOPIE]")
        return True
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

