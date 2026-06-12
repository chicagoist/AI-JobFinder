# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime
import re

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "applications.db")
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applied_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT,
            job_title TEXT,
            url TEXT UNIQUE,
            score REAL,
            applied_date TEXT,
            status TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT,
            job_title TEXT,
            url TEXT UNIQUE,
            reason TEXT,
            date TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candidate_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            file_size INTEGER,
            mtime REAL,
            classification TEXT,
            parsed_json TEXT
        )
    """)
    # Migrations for email sender feature
    try:
        cursor.execute("ALTER TABLE applied_jobs ADD COLUMN email_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE applied_jobs ADD COLUMN terminal_output TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE applied_jobs ADD COLUMN pdf_path TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn

def log_user_rejection(conn, company_name, job_title, url, reason):
    cursor = conn.cursor()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR REPLACE INTO user_rejections (company_name, job_title, url, reason, date)
        VALUES (?, ?, ?, ?, ?)
    """, (company_name, job_title, url, reason, date_str))
    conn.commit()

def get_past_rejections(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT reason FROM user_rejections")
        rows = cursor.fetchall()
        return [row[0] for row in rows if row[0]]
    except Exception:
        return []

def clean_string_for_matching(s):
    if not s:
        return ""
    s = s.lower()
    # Remove common suffixes in parentheses
    s = re.sub(r'\((m/w/d|w/m/d|f/m/d|m/f/d|remote|hybrid|onsite|m/w|w/m)\)', '', s)
    # Remove words outside parentheses too
    s = re.sub(r'\b(remote|hybrid|onsite)\b', '', s)
    # Remove extra spaces and special characters
    s = re.sub(r'[^a-z0-9]', '', s)
    return s.strip()

def is_already_applied(conn, company_name, job_title, url):
    cursor = conn.cursor()
    # Check exact URL
    cursor.execute("SELECT id FROM applied_jobs WHERE url = ?", (url,))
    if cursor.fetchone():
        return True
        
    # Retrieve all applied jobs and compare cleaned versions
    cursor.execute("SELECT company_name, job_title FROM applied_jobs")
    rows = cursor.fetchall()
    
    clean_company = clean_string_for_matching(company_name)
    clean_title = clean_string_for_matching(job_title)
    
    for db_company, db_job_title in rows:
        if clean_string_for_matching(db_company) == clean_company and clean_string_for_matching(db_job_title) == clean_title:
            return True
            
    return False

def log_application(conn, company_name, job_title, url, score, status, terminal_output=None, pdf_path=None):
    cursor = conn.cursor()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT id, email_sent, terminal_output, pdf_path FROM applied_jobs WHERE url = ?", (url,))
    row = cursor.fetchone()
    if row:
        db_id, existing_email_sent, existing_output, existing_pdf = row
        final_output = terminal_output if terminal_output is not None else existing_output
        final_pdf = pdf_path if pdf_path is not None else existing_pdf
        cursor.execute("""
            UPDATE applied_jobs 
            SET company_name = ?, job_title = ?, score = ?, applied_date = ?, status = ?, terminal_output = ?, pdf_path = ?
            WHERE id = ?
        """, (company_name, job_title, score, date_str, status, final_output, final_pdf, db_id))
    else:
        cursor.execute("""
            INSERT INTO applied_jobs (company_name, job_title, url, score, applied_date, status, terminal_output, pdf_path, email_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (company_name, job_title, url, score, date_str, status, terminal_output, pdf_path))
    conn.commit()
