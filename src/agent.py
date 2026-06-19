import os
import sys
import argparse
import json
import yaml
import datetime
import sqlite3
import urllib.request
import urllib.parse
import re
import warnings
import time

# Import common utilities and configuration loaders from the package
import job_agent.utils
from job_agent.utils import Colors, clean_and_repair_json, TeeStdout
from job_agent.config import load_config, load_criteria, load_prompts, restore_active_configs_from_samples, DEFAULT_PROMPTS, PROMPTS
from job_agent.db import init_db, log_application, log_user_rejection, get_past_rejections, is_already_applied
from job_agent.llm import init_gemini, generate_content_with_retry, llm_request_with_fallback
from job_agent.pipeline import run_pipeline_mode
from playwright.sync_api import sync_playwright

# API Keys and client configuration are managed in job_agent/llm.py
GEMINI_MODEL = "gemini-2.5-flash"

# Debug mode — enabled via --debug CLI flag
DEBUG = False
def debug_print(*args, **kwargs):
    """Print timestamped debug messages when DEBUG is True. Pass prefix='...' to label the subsystem."""
    if not DEBUG:
        return
    prefix = kwargs.pop("prefix", "DEBUG")
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{Colors.GREY}[{prefix} {ts}]{Colors.END}", *args, **kwargs)

def run_config_gui(config_path, criteria_path, profile_path, prompts_path):
    print(f"{Colors.CYAN}Launching Configuration GUI...{Colors.END}")
    
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext, messagebox
    except ImportError as e:
        print(f"{Colors.YELLOW}Warning: Tkinter could not be imported: {e}. Running without GUI.{Colors.END}")
        return
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception:
        config_data = {}
        
    try:
        with open(criteria_path, "r", encoding="utf-8") as f:
            criteria_data = yaml.safe_load(f) or {}
    except Exception:
        criteria_data = {}
        
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f) or {}
    except Exception:
        profile_data = {}
        
    try:
        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts_data = yaml.safe_load(f) or {}
    except Exception:
        prompts_data = {}
        
    if "user_profile" not in config_data:
        config_data["user_profile"] = {}
    if "defaults" not in config_data:
        config_data["defaults"] = {}
    if "gemini" not in config_data:
        config_data["gemini"] = {}
    if "criteria" not in config_data:
        config_data["criteria"] = {}
        
    if "scoring" not in criteria_data:
        criteria_data["scoring"] = {}
    if "ko_filters" not in criteria_data:
        criteria_data["ko_filters"] = {}
    if "cover_letter" not in criteria_data:
        criteria_data["cover_letter"] = {}
        
    ko = criteria_data["ko_filters"]
    if "salary" not in ko:
        ko["salary"] = {}
    if "clearances" not in ko:
        ko["clearances"] = {}
    if "certifications" not in ko:
        ko["certifications"] = {}
    if "education" not in ko:
        ko["education"] = {}
    if "languages" not in ko:
        ko["languages"] = {}
    if "datacenter_physical_work" not in ko:
        ko["datacenter_physical_work"] = {}
    if "spam_providers" not in ko:
        ko["spam_providers"] = {}
        
    if "user_rejected_reasons" not in ko:
        ko["user_rejected_reasons"] = []
        
    # Sync and merge user rejections from SQLite database into criteria yaml
    try:
        db_path = os.path.join(os.path.dirname(os.path.dirname(criteria_path)), "output", "applications.db")
        if os.path.exists(db_path):
            db_conn = sqlite3.connect(db_path)
            db_cursor = db_conn.cursor()
            db_cursor.execute("SELECT reason FROM user_rejections")
            db_rejections = [row[0] for row in db_cursor.fetchall() if row[0]]
            db_conn.close()
            
            yaml_rejections = ko.get("user_rejected_reasons", [])
            if not isinstance(yaml_rejections, list):
                yaml_rejections = []
            
            for r in db_rejections:
                if r not in yaml_rejections:
                    yaml_rejections.append(r)
            ko["user_rejected_reasons"] = yaml_rejections
    except Exception as e:
        print(f"Warning: Could not sync rejections from database: {e}")
        
    if "personal_info" not in profile_data:
        profile_data["personal_info"] = {}
    if "languages" not in profile_data:
        profile_data["languages"] = {}
    if "skills" not in profile_data:
        profile_data["skills"] = []
    if "certifications" not in profile_data:
        profile_data["certifications"] = []
    # Normalize certifications: dict {name, date} → plain string
    certs = profile_data.get("certifications", [])
    if isinstance(certs, list):
        profile_data["certifications"] = [
            c["name"] if isinstance(c, dict) and "name" in c else str(c)
            for c in certs
        ]
    if "education" not in profile_data:
        profile_data["education"] = []
        
    for k, v in DEFAULT_PROMPTS.items():
        if k not in prompts_data:
            prompts_data[k] = v

    try:
        root = tk.Tk()
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not initialize Tkinter root window: {e}. Running without GUI.{Colors.END}")
        return
        
    root.title("Gemini JobAgent Configuration")
    root.geometry("820x720")
    root.resizable(True, True)
    
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('.', background='#f0f4f8', foreground='#333333')
    style.configure('TLabel', background='#f0f4f8', foreground='#333333', font=('Segoe UI', 9))
    style.configure('TEntry', fieldbackground='#ffffff', font=('Segoe UI', 9))
    style.configure('TButton', background='#2b6cb0', foreground='#ffffff', font=('Segoe UI', 9, 'bold'))
    style.map('TButton', background=[('active', '#1a365d')])
    style.configure('TCheckbutton', background='#f0f4f8', font=('Segoe UI', 9))
    
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)
    
    def create_tab_frame(notebook_widget):
        frame = ttk.Frame(notebook_widget)
        canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0, background='#f0f4f8')
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta/120)), "units"))
        return frame, scrollable_frame
        
    # --- TAB 1: API & System ---
    tab1_container, tab1 = create_tab_frame(notebook)
    notebook.add(tab1_container, text="API & System")
    
    ttk.Label(tab1, text="Gemini Model:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky="w", padx=10, pady=5)
    model_combo = ttk.Combobox(tab1, values=["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest"], width=30)
    model_combo.set(config_data["gemini"].get("model", "gemini-2.5-flash"))
    model_combo.grid(row=0, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="Gemini API Keys (One per line):", font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    api_keys_text = scrolledtext.ScrolledText(tab1, width=70, height=8, font=('Consolas', 9))
    api_keys_text.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
    keys_list = config_data["gemini"].get("api_keys")
    if not keys_list:
        keys_list = API_KEYS
    api_keys_text.insert("1.0", "\n".join(keys_list))
    
    ttk.Label(tab1, text="Chrome User Data Dir:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, sticky="w", padx=10, pady=5)
    chrome_dir_entry = ttk.Entry(tab1, width=60)
    chrome_dir_entry.insert(0, config_data["user_profile"].get("chrome_data_dir", ""))
    chrome_dir_entry.grid(row=3, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="Chrome Profile Name:", font=('Segoe UI', 9, 'bold')).grid(row=4, column=0, sticky="w", padx=10, pady=5)
    chrome_profile_entry = ttk.Entry(tab1, width=30)
    chrome_profile_entry.insert(0, config_data["user_profile"].get("chrome_profile", "Default"))
    chrome_profile_entry.grid(row=4, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="CV Path (PDF File):", font=('Segoe UI', 9, 'bold')).grid(row=5, column=0, sticky="w", padx=10, pady=5)
    cv_path_entry = ttk.Entry(tab1, width=40)
    cv_path_entry.insert(0, config_data["user_profile"].get("cv_path", ""))
    cv_path_entry.grid(row=5, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="Documents Directory:", font=('Segoe UI', 9, 'bold')).grid(row=6, column=0, sticky="w", padx=10, pady=5)
    doc_dir_entry = ttk.Entry(tab1, width=40)
    doc_dir_entry.insert(0, config_data["user_profile"].get("documents_dir", "documents"))
    doc_dir_entry.grid(row=6, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="Priority LLM:", font=('Segoe UI', 9, 'bold')).grid(row=7, column=0, sticky="w", padx=10, pady=5)
    priority_llm_combo = ttk.Combobox(tab1, values=["gemini", "openrouter"], state="readonly", width=30)
    priority_llm_combo.set(config_data.get("llm", {}).get("priority", "gemini"))
    priority_llm_combo.grid(row=7, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Separator(tab1, orient="horizontal").grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
    
    smtp_section = config_data.get("smtp", {})
    ttk.Label(tab1, text="SMTP Email (Sender):", font=('Segoe UI', 9, 'bold')).grid(row=9, column=0, sticky="w", padx=10, pady=5)
    smtp_username_entry = ttk.Entry(tab1, width=40)
    smtp_username_entry.insert(0, smtp_section.get("username", ""))
    smtp_username_entry.grid(row=9, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab1, text="Google App Password:", font=('Segoe UI', 9, 'bold')).grid(row=10, column=0, sticky="w", padx=10, pady=5)
    smtp_password_entry = ttk.Entry(tab1, width=40, show="*")
    smtp_password_entry.insert(0, smtp_section.get("password", ""))
    smtp_password_entry.grid(row=10, column=1, sticky="w", padx=10, pady=5)
    
    # --- TAB 2: Candidate Profile & Defaults ---
    tab2_container, tab2 = create_tab_frame(notebook)
    notebook.add(tab2_container, text="Candidate Profile")
    
    ttk.Label(tab2, text="Personal Info", font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=10)
    
    pi_fields = [
        ("first_name", "Vorname:"),
        ("last_name", "Nachname:"),
        ("email", "E-Mail:"),
        ("phone", "Telefon:"),
        ("address", "Adresse:"),
        ("city", "Stadt / PLZ:"),
        ("country", "Land:")
    ]
    pi_entries = {}
    r_idx = 1
    for k, label_text in pi_fields:
        ttk.Label(tab2, text=label_text).grid(row=r_idx, column=0, sticky="w", padx=10, pady=3)
        ent = ttk.Entry(tab2, width=40)
        ent.insert(0, profile_data["personal_info"].get(k, ""))
        ent.grid(row=r_idx, column=1, sticky="w", padx=10, pady=3)
        pi_entries[k] = ent
        r_idx += 1
        
    ttk.Label(tab2, text="Application Defaults", font=('Segoe UI', 10, 'bold')).grid(row=r_idx, column=0, columnspan=2, sticky="w", padx=10, pady=10)
    r_idx += 1
    
    def_fields = [
        ("salary_expectation", "salary_expectation (z.B. 36.000 €):", config_data["defaults"]),
        ("availability", "availability (z.B. zwei Monate nach Zusage):", config_data["defaults"]),
        ("work_permit", "work_permit (z.B. Germany):", config_data["defaults"]),
        ("notice_period", "notice_period (z.B. 3 Monate zum Quartalsende):", config_data["defaults"]),
        ("german_level", "german_level (in config.yaml, z.B. B2):", config_data["criteria"])
    ]
    def_entries = {}
    for k, label_text, source_dict in def_fields:
        ttk.Label(tab2, text=label_text).grid(row=r_idx, column=0, sticky="w", padx=10, pady=3)
        ent = ttk.Entry(tab2, width=40)
        ent.insert(0, source_dict.get(k, ""))
        ent.grid(row=r_idx, column=1, sticky="w", padx=10, pady=3)
        def_entries[k] = ent
        r_idx += 1
        
    ttk.Label(tab2, text="Experience Years:", font=('Segoe UI', 9, 'bold')).grid(row=r_idx, column=0, sticky="w", padx=10, pady=5)
    exp_years_entry = ttk.Entry(tab2, width=15)
    exp_years_entry.insert(0, str(profile_data.get("experience_years", 0.0)))
    exp_years_entry.grid(row=r_idx, column=1, sticky="w", padx=10, pady=5)
    r_idx += 1
    
    ttk.Label(tab2, text="Skills (One per line):", font=('Segoe UI', 9, 'bold')).grid(row=r_idx, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    skills_text = scrolledtext.ScrolledText(tab2, width=50, height=8, font=('Segoe UI', 9))
    skills_text.grid(row=r_idx+1, column=0, columnspan=2, padx=10, pady=5, sticky="w")
    skills_text.insert("1.0", "\n".join(profile_data.get("skills", [])))
    r_idx += 2
    
    ttk.Label(tab2, text="Certifications (One per line):", font=('Segoe UI', 9, 'bold')).grid(row=r_idx, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    certs_text = scrolledtext.ScrolledText(tab2, width=50, height=6, font=('Segoe UI', 9))
    certs_text.grid(row=r_idx+1, column=0, columnspan=2, padx=10, pady=5, sticky="w")
    certs_text.insert("1.0", "\n".join(profile_data.get("certifications", [])))
    r_idx += 2
    
    # --- TAB 3: Prompts Editor ---
    tab3 = ttk.Frame(notebook)
    notebook.add(tab3, text="Prompts Editor")
    
    ttk.Label(tab3, text="Select Prompt to Edit:", font=('Segoe UI', 9, 'bold')).pack(anchor="w", padx=10, pady=5)
    prompt_keys = ["scoring_prompt", "scoring_prompt_IT", "cover_letter_prompt", "form_filler_prompt",
                   "classification_prompt", "classify_document_prompt",
                   "job_intake_prompt", "extract_recruiter_prompt"]
    prompt_combo = ttk.Combobox(tab3, values=prompt_keys, state="readonly", width=30)
    prompt_combo.set("scoring_prompt")
    prompt_combo.pack(anchor="w", padx=10, pady=5)
    
    edited_prompts = prompts_data.copy()
    last_selected = "scoring_prompt"
    
    prompt_text_widget = scrolledtext.ScrolledText(tab3, font=('Consolas', 10), wrap="word")
    prompt_text_widget.pack(fill="both", expand=True, padx=10, pady=10)
    prompt_text_widget.insert("1.0", edited_prompts.get(last_selected, ""))
    
    def switch_prompt(*args):
        nonlocal last_selected
        edited_prompts[last_selected] = prompt_text_widget.get("1.0", tk.END).strip()
        new_selected = prompt_combo.get()
        prompt_text_widget.delete("1.0", tk.END)
        prompt_text_widget.insert("1.0", edited_prompts.get(new_selected, ""))
        last_selected = new_selected
        
    prompt_combo.bind("<<ComboboxSelected>>", switch_prompt)
    
    # --- TAB 4: K.O. Filters ---
    tab4_container, tab4 = create_tab_frame(notebook)
    notebook.add(tab4_container, text="K.O. Filters")
    
    ttk.Label(tab4, text="Min Score to Apply:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
    min_score_entry = ttk.Entry(tab4, width=15)
    min_score_entry.insert(0, str(criteria_data["scoring"].get("min_score_to_apply", 8.0)))
    min_score_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab4, text="Min Annual Salary EUR:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
    min_salary_entry = ttk.Entry(tab4, width=15)
    min_salary_entry.insert(0, str(ko["salary"].get("min_annual_eur", 50000)))
    min_salary_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)
    
    req_degree_var = tk.BooleanVar(value=ko["education"].get("require_it_degree_strictly", False))
    block_degree_only_var = tk.BooleanVar(value=ko["education"].get("block_degree_only_roles", True))
    ttk.Checkbutton(tab4, text="Require IT Degree Strictly", variable=req_degree_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    ttk.Checkbutton(tab4, text="Block Degree-Only Roles (No equivalent experience)", variable=block_degree_only_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    
    ttk.Label(tab4, text="Min Required English Level:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
    min_english_entry = ttk.Entry(tab4, width=15)
    min_english_entry.insert(0, ko["languages"].get("min_required_english", "A2"))
    min_english_entry.grid(row=4, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab4, text="Min Required German Level:").grid(row=5, column=0, sticky="w", padx=10, pady=5)
    min_german_entry = ttk.Entry(tab4, width=15)
    min_german_entry.insert(0, ko["languages"].get("min_required_german", "B1"))
    min_german_entry.grid(row=5, column=1, sticky="w", padx=10, pady=5)
    
    dc_forbidden_var = tk.BooleanVar(value=ko["datacenter_physical_work"].get("forbidden", True))
    ttk.Checkbutton(tab4, text="Datacenter Physical Work Forbidden", variable=dc_forbidden_var).grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    
    ttk.Label(tab4, text="Datacenter Keywords (One per line):").grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    dc_keywords_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    dc_keywords_text.grid(row=8, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    dc_keywords_text.insert("1.0", "\n".join(ko["datacenter_physical_work"].get("keywords", [])))
    
    spam_internship_var = tk.BooleanVar(value=ko["spam_providers"].get("allow_internship", True))
    ttk.Checkbutton(tab4, text="Allow Internship for Spam Providers", variable=spam_internship_var).grid(row=9, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    
    ttk.Label(tab4, text="Spam Providers Keywords (One per line):").grid(row=10, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    spam_keywords_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    spam_keywords_text.grid(row=11, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    spam_keywords_text.insert("1.0", "\n".join(ko["spam_providers"].get("blocked_keywords", [])))
    
    ttk.Label(tab4, text="Company Blacklist (One per line):").grid(row=12, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    blacklist_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    blacklist_text.grid(row=13, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    blacklist_text.insert("1.0", "\n".join(ko.get("companies_blacklist", [])))
    
    ttk.Label(tab4, text="Forbidden Clearances/Citizenship Keywords (One per line):").grid(row=14, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    clearance_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    clearance_text.grid(row=15, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    clearance_text.insert("1.0", "\n".join(ko["clearances"].get("forbidden_keywords", [])))
    
    ttk.Label(tab4, text="Mandatory Certifications (One per line):").grid(row=16, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    mand_certs_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    mand_certs_text.grid(row=17, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    mand_certs_text.insert("1.0", "\n".join(ko["certifications"].get("mandatory_if_specified", [])))
    
    ttk.Label(tab4, text="Career Start Year:").grid(row=18, column=0, sticky="w", padx=10, pady=5)
    career_start_entry = ttk.Entry(tab4, width=15)
    career_start_entry.insert(0, str(criteria_data["cover_letter"].get("career_start_year", 2010)))
    career_start_entry.grid(row=18, column=1, sticky="w", padx=10, pady=5)
    
    ttk.Label(tab4, text="Mandatory Skills in Cover Letter (One per line):").grid(row=19, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    mand_skills_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    mand_skills_text.grid(row=20, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    mand_skills_text.insert("1.0", "\n".join(criteria_data["cover_letter"].get("mandatory_skills", [])))

    ttk.Label(tab4, text="Forbidden Job Titles (One per line):").grid(row=21, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    forbidden_titles_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    forbidden_titles_text.grid(row=22, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    forbidden_titles_text.insert("1.0", "\n".join(ko.get("forbidden_titles", [])))

    ttk.Label(tab4, text="User Rejection Reasons (One per line):").grid(row=23, column=0, columnspan=2, sticky="w", padx=10, pady=3)
    user_rejected_reasons_text = scrolledtext.ScrolledText(tab4, width=50, height=4, font=('Segoe UI', 9))
    user_rejected_reasons_text.grid(row=24, column=0, columnspan=2, padx=10, pady=3, sticky="w")
    user_rejected_reasons_text.insert("1.0", "\n".join(ko.get("user_rejected_reasons", [])))
    
    search_cfg = criteria_data.get("search", {})
    ttk.Label(tab4, text="Search Industry:").grid(row=25, column=0, sticky="w", padx=10, pady=5)
    industry_var = tk.StringVar(value=search_cfg.get("industry", "IT"))
    industry_combo = ttk.Combobox(tab4, textvariable=industry_var, values=["IT", "Handwerk", "Allgemein"], state="readonly", width=15)
    industry_combo.grid(row=25, column=1, sticky="w", padx=10, pady=5)

    def save_and_close():
        edited_prompts[last_selected] = prompt_text_widget.get("1.0", tk.END).strip()
        
        config_data["gemini"]["model"] = model_combo.get()
        keys_raw = api_keys_text.get("1.0", tk.END).strip()
        config_data["gemini"]["api_keys"] = [k.strip() for k in keys_raw.split("\n") if k.strip()]
        if "llm" not in config_data:
            config_data["llm"] = {}
        config_data["llm"]["priority"] = priority_llm_combo.get()
        
        if "smtp" not in config_data:
            config_data["smtp"] = {}
        config_data["smtp"]["username"] = smtp_username_entry.get().strip()
        config_data["smtp"]["password"] = smtp_password_entry.get().strip()
        
        config_data["user_profile"]["chrome_data_dir"] = chrome_dir_entry.get().strip()
        config_data["user_profile"]["chrome_profile"] = chrome_profile_entry.get().strip()
        config_data["user_profile"]["cv_path"] = cv_path_entry.get().strip()
        config_data["user_profile"]["documents_dir"] = doc_dir_entry.get().strip()
        
        config_data["defaults"]["salary_expectation"] = def_entries["salary_expectation"].get().strip()
        config_data["defaults"]["availability"] = def_entries["availability"].get().strip()
        config_data["defaults"]["work_permit"] = def_entries["work_permit"].get().strip()
        config_data["defaults"]["notice_period"] = def_entries["notice_period"].get().strip()
        config_data["criteria"]["german_level"] = def_entries["german_level"].get().strip()
        
        for k, ent in pi_entries.items():
            profile_data["personal_info"][k] = ent.get().strip()
            
        try:
            profile_data["experience_years"] = float(exp_years_entry.get().strip())
        except ValueError:
            profile_data["experience_years"] = 0.0
            
        skills_raw = skills_text.get("1.0", tk.END).strip()
        profile_data["skills"] = [s.strip() for s in skills_raw.split("\n") if s.strip()]
        
        certs_raw = certs_text.get("1.0", tk.END).strip()
        profile_data["certifications"] = [c.strip() for c in certs_raw.split("\n") if c.strip()]
        
        profile_data["languages"]["Deutsch"] = def_entries["german_level"].get().strip()
        profile_data["languages"]["Englisch"] = min_english_entry.get().strip()
        
        try:
            criteria_data["scoring"]["min_score_to_apply"] = float(min_score_entry.get().strip())
        except ValueError:
            criteria_data["scoring"]["min_score_to_apply"] = 8.0
            
        try:
            criteria_data["ko_filters"]["salary"]["min_annual_eur"] = int(min_salary_entry.get().strip())
        except ValueError:
            criteria_data["ko_filters"]["salary"]["min_annual_eur"] = 40000
            
        criteria_data["ko_filters"]["education"]["require_it_degree_strictly"] = req_degree_var.get()
        criteria_data["ko_filters"]["education"]["block_degree_only_roles"] = block_degree_only_var.get()
        criteria_data["ko_filters"]["languages"]["min_required_english"] = min_english_entry.get().strip()
        criteria_data["ko_filters"]["languages"]["min_required_german"] = min_german_entry.get().strip()
        
        criteria_data["ko_filters"]["datacenter_physical_work"]["forbidden"] = dc_forbidden_var.get()
        dc_keys_raw = dc_keywords_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["datacenter_physical_work"]["keywords"] = [k.strip() for k in dc_keys_raw.split("\n") if k.strip()]
        
        criteria_data["ko_filters"]["spam_providers"]["allow_internship"] = spam_internship_var.get()
        spam_keys_raw = spam_keywords_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["spam_providers"]["blocked_keywords"] = [k.strip() for k in spam_keys_raw.split("\n") if k.strip()]
        
        blacklist_raw = blacklist_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["companies_blacklist"] = [c.strip() for c in blacklist_raw.split("\n") if c.strip()]
        
        clearance_raw = clearance_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["clearances"]["forbidden_keywords"] = [c.strip() for c in clearance_raw.split("\n") if c.strip()]
        
        mand_certs_raw = mand_certs_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["certifications"]["mandatory_if_specified"] = [c.strip() for c in mand_certs_raw.split("\n") if c.strip()]
        
        forbidden_titles_raw = forbidden_titles_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["forbidden_titles"] = [t.strip() for t in forbidden_titles_raw.split("\n") if t.strip()]
        
        user_reasons_raw = user_rejected_reasons_text.get("1.0", tk.END).strip()
        criteria_data["ko_filters"]["user_rejected_reasons"] = [r.strip() for r in user_reasons_raw.split("\n") if r.strip()]
        
        try:
            criteria_data["cover_letter"]["career_start_year"] = int(career_start_entry.get().strip())
        except ValueError:
            criteria_data["cover_letter"]["career_start_year"] = 2010
        
        if "search" not in criteria_data:
            criteria_data["search"] = {}
        criteria_data["search"]["industry"] = industry_var.get()
        
        mand_skills_raw = mand_skills_text.get("1.0", tk.END).strip()
        criteria_data["cover_letter"]["mandatory_skills"] = [s.strip() for s in mand_skills_raw.split("\n") if s.strip()]
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config_data, f, allow_unicode=True)
            with open(criteria_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(criteria_data, f, allow_unicode=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, ensure_ascii=False, indent=2)
            with open(prompts_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(edited_prompts, f, allow_unicode=True)
            print(f"{Colors.GREEN}Successfully saved configuration updates.{Colors.END}")
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to save configurations:\n{ex}")
            return
            
        root.destroy()

    save_frame = ttk.Frame(root, padding=10)
    save_frame.pack(fill="x", side="bottom")
    
    save_btn = ttk.Button(save_frame, text="Save & Launch", command=save_and_close)
    save_btn.pack(side="right", padx=5)
    
    cancel_btn = ttk.Button(save_frame, text="Cancel (Use current configurations)", command=root.destroy)
    cancel_btn.pack(side="right", padx=5)
    
    root.mainloop()

# Initialize Gemini API client
# and automatic model fallback on daily/minute quota exhaustion.
GEMINI_MODEL = "gemini-2.5-flash"

# generate_content_with_retry has been migrated to job_agent/llm.py

# Database functions (init_db, log_user_rejection, get_past_rejections, is_already_applied, log_application) have been migrated to job_agent/db.py

# Generate a dummy CV PDF for testing purposes
def generate_dummy_cv(output_path):
    print(f"Generating dummy CV at '{output_path}'...")
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Lebenslauf - Max Mustermann</title>
      <style>
        body { font-family: Arial, sans-serif; margin: 20mm; line-height: 1.5; color: #333; }
        h1 { margin-bottom: 2px; }
        .subtitle { color: #666; margin-bottom: 20px; }
        h2 { border-bottom: 1px solid #ccc; padding-bottom: 5px; margin-top: 25px; }
        .section-item { margin-bottom: 15px; }
        .date { float: right; color: #666; }
      </style>
    </head>
    <body>
      <h1>Max Mustermann</h1>
      <div class="subtitle">Cloud Engineer | Berlin, Deutschland | max.mustermann@example.com | +49 176 12345678</div>
      
      <h2>Sprachkenntnisse</h2>
      <p>Deutsch: B2, Englisch: A2, Russisch: Muttersprache, Ukrainisch: Muttersprache</p>
      
      <h2>Core Skills</h2>
      <p>Azure, Azure CLI, Linux, Windows Server, Python, Java, Git, Terraform, CI/CD, Docker</p>
      
      <h2>Berufserfahrung</h2>
      <div class="section-item">
        <span class="date">01/2024 - Heute</span>
        <strong>Cloud Engineer</strong> @ Musterfirma GmbH, Berlin
        <p>Orchestrierung von Cloud-Plattformen, Erstellung von CI/CD-Pipelines in GitLab, Automatisierung von IT-Prozessen mit Python und Terraform.</p>
      </div>
    </body>
    </html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content)
        page.pdf(path=output_path, format="A4")
        browser.close()
    print(f"Dummy CV PDF successfully generated at '{output_path}'!")

# Parse CV PDF into structured JSON candidate profile
def parse_cv(cv_path, output_json_path, criteria_path=None):
    if not os.path.exists(cv_path):
        print(f"Error: CV file '{cv_path}' not found.")
        print("Creating a dummy CV for testing since none exists...")
        generate_dummy_cv(cv_path)
        
    print(f"Extracting text from '{cv_path}'...")
    import fitz
    try:
        doc = fitz.open(cv_path)
        cv_text = ""
        for page in doc:
            cv_text += page.get_text()
        doc.close()
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        sys.exit(1)

    print(f"Parsing CV via LLM...")
    init_gemini()

    prompt = f"""
    Du bist ein erfahrener Senior HR-Spezialist in Deutschland. Analysiere diesen Lebenslauf (CV) und erstelle ein konsolidiertes Profil.
    
    WICHTIG: Extrahiere zu jedem Ausbildungseintrag (education) ein 'curriculum'-Feld mit den detaillierten Kursinhalten/Modulen, falls im Dokument beschrieben. Dies hilft später beim Scoring gegen Stellenanforderungen.
    
    WICHTIG: STRENGE TRENNUNG VON EDUCATION UND EXPERIENCE. Extrahiere NUR explizite Arbeitsverhältnisse mit Firmenname als 'experience'. Ein Studium, eine Umschulung oder ein Kurs ist Bildung (education), NICHT Berufserfahrung. Inferiere NIEMALS Berufserfahrung aus Bildung.
    
    WICHTIG: Leite die 'job_search_directions' und 'target_vacancies' AUSSCHLIESSLICH aus den tatsächlich im Lebenslauf genannten Stationen, Fähigkeiten und Qualifikationen ab. Erfinde KEINE Karrierepfade. Wenn der Lebenslauf nur einen Bereich abdeckt, nenne NUR diesen Bereich.
    
    Hier ist der extrahierte Text des Lebenslaufs:
    --- START LEBENSLAUF ---
    {cv_text}
    --- ENDE LEBENSLAUF ---
    
    Struktur des erwarteten JSON:
    {{
      "personal_info": {{
        "first_name": "...",
        "last_name": "...",
        "email": "...",
        "phone": "...",
        "address": "...",
        "city": "...",
        "country": "Deutschland",
        "location": "Stadt, Land, Straße",
        "availability": "Datum oder 'sofort'"
      }},
      "languages": {{ "deutsch": "B2", "englisch": "A2", "ukrainisch": "Muttersprache", "russisch": "Muttersprache" }},
      "skills": [...],
      "experience_years": 0.0,
      "seniority_level": "...",
      "hr_assessment": {{
        "job_search_directions": ["..."],
        "target_vacancies": ["..."],
        "apply_to_learning_roles": true,
        "strategic_advice": "..."
      }},
      "experience": [{{ "title": "...", "company": "...", "years": "..." }}],
      "education": [...],
      "certifications": [...]
    }}
    """
    
    response = llm_request_with_fallback(prompt)
    
    if response is None:
        print(f"{Colors.RED}Warning: LLM returned None for CV parsing. Returning empty profile.{Colors.END}")
        return {"error": "LLM returned None"}
    
    # Extract text and clean it up
    text = clean_and_repair_json(response.text)
    
    try:
        profile_data = json.loads(text)
        
        # Normalize profile: fill first_name, last_name, address, city from name/location
        profile_data = normalize_profile(profile_data)
        
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)
        print(f"Successfully created candidate profile at '{output_json_path}'")
        return profile_data
    except Exception as e:
        print(f"Failed to parse JSON response from LLM. Raw response was:\n{text}")
        print(f"Error: {e}")
        sys.exit(1)

# Normalize candidate profile: fill missing first_name/last_name/address/city from name/location
def normalize_profile(profile_data):
    pi = profile_data.get("personal_info", {})
    if not pi.get("first_name") and not pi.get("last_name") and pi.get("name"):
        name_parts = pi["name"].strip().rsplit(" ", 1)
        if len(name_parts) == 2:
            if not pi.get("first_name"):
                pi["first_name"] = name_parts[0]
            if not pi.get("last_name"):
                pi["last_name"] = name_parts[1]
        else:
            pi["first_name"] = pi.get("first_name") or pi["name"]
            pi["last_name"] = pi.get("last_name") or pi["name"]
    loc = pi.get("location", "")
    if not pi.get("address") and not pi.get("city"):
        if loc and "," in loc:
            parts = [p.strip() for p in loc.split(",")]
            pi["address"] = parts[0]
            pi["city"] = parts[1] if len(parts) > 1 else loc
        else:
            pi["address"] = pi.get("address") or loc
            pi["city"] = pi.get("city") or loc
    elif not pi.get("city") and pi.get("address"):
        pi["city"] = pi["address"].rsplit(" ", 1)[-1] if " " in pi["address"] else pi["address"]
    pi["country"] = pi.get("country") or "Deutschland"
    pi["first_name"] = pi.get("first_name") or ""
    pi["last_name"] = pi.get("last_name") or ""
    pi["address"] = pi.get("address") or ""
    pi["city"] = pi.get("city") or ""
    # Normalize certifications: convert dict {name, date} to plain strings
    certs = profile_data.get("certifications", [])
    if certs and isinstance(certs, list):
        profile_data["certifications"] = [
            c["name"] if isinstance(c, dict) and "name" in c else str(c)
            for c in certs
        ]
    return profile_data

# Parse Cover Letter PDF
def parse_anschreiben_pdf(file_path):
    import fitz
    print(f"   Parsing Cover Letter '{file_path}' via Gemini Flash...")
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    init_gemini()
    prompt = f"""
    Analysiere dieses Anschreiben (Cover Letter) und extrahiere die folgenden Informationen im JSON-Format.
    Gib NUR das reine JSON-Dokument zurück, ohne zusätzliche Erklärung, Markdown-Tags (wie ```json) oder Formatierung.
    
    Struktur des erwarteten JSON:
    {{
      "company_name": "Name des Zielunternehmens (falls vorhanden)",
      "job_title": "Bewerbungs-Position/Rolle",
      "salary_expectation": "Gehaltsvorstellung (falls erwähnt)",
      "availability": "Verfügbarkeit / Eintrittstermin (falls erwähnt)",
      "content": "Vollständiger Text des Anschreibens"
    }}
    
    Text des Dokuments:
    {text[:5000]}
    """
    response = llm_request_with_fallback(prompt)
    if response is None:
        print(f"{Colors.RED}   Warning: LLM returned None for Anschreiben parsing.{Colors.END}")
        return {"content": text, "error": "LLM returned None"}
    try:
        return json.loads(clean_and_repair_json(response.text))
    except Exception as e:
        print(f"   Warning: could not parse Anschreiben JSON: {e}")
        return {"content": text, "error": str(e)}

# Parse Certificate PDF
def parse_zertifikat_pdf(file_path):
    import fitz
    print(f"   Parsing Certificate '{file_path}' via Gemini Flash...")
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    init_gemini()
    prompt = f"""
    Analysiere dieses Zertifikat (Certificate) und extrahiere die folgenden Informationen im JSON-Format.
    Gib NUR das reine JSON-Dokument zurück, ohne zusätzliche Erklärung, Markdown-Tags (wie ```json) oder Formatierung.
    
    Struktur des erwarteten JSON:
    {{
      "title": "Name/Bezeichnung des Zertifikats",
      "issuer": "Ausstellende Organisation (z.B. Google, Cisco, Red Hat, Coursera)",
      "issue_date": "Ausstellungsdatum (z.B. YYYY-MM-DD oder Monat/Jahr, falls vorhanden)",
      "skills": ["Zertifizierte Fähigkeit 1", "Zertifizierte Fähigkeit 2"]
    }}
    
    Text des Dokuments:
    {text[:5000]}
    """
    response = llm_request_with_fallback(prompt)
    if response is None:
        print(f"{Colors.RED}   Warning: LLM returned None for Certificate parsing.{Colors.END}")
        return {"title": os.path.basename(file_path), "error": "LLM returned None"}
    try:
        return json.loads(clean_and_repair_json(response.text))
    except Exception as e:
        print(f"   Warning: could not parse Certificate JSON: {e}")
        return {"title": os.path.basename(file_path), "error": str(e)}

# Parse Diploma PDF
def parse_diplom_pdf(file_path):
    import fitz
    print(f"   Parsing Diploma/Degree '{file_path}' via LLM...")
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    init_gemini()
    prompt = f"""
    Analysiere dieses Diplom/Zeugnis (Degree/Diploma/Transcript) und extrahiere die folgenden Informationen im JSON-Format.
    Gib NUR das reine JSON-Dokument zurück, ohne zusätzliche Erklärung, Markdown-Tags (wie ```json) oder Formatierung.
    
    Struktur des erwarteten JSON:
    {{
      "degree": "Art des Abschlusses (z.B. Abitur, Bachelor, Master, Ausbildung)",
      "field": "Fachrichtung / Spezialisierung",
      "institution": "Name der Schule/Hochschule/Ausbildungseinrichtung",
      "year": "Abschlussjahr (oder Abschlussdatum, falls vorhanden)",
      "grade": "Abschlussnote / Score (falls vorhanden)"
    }}
    
    Text des Dokuments:
    {text[:5000]}
    """
    response = llm_request_with_fallback(prompt)
    if response is None:
        print(f"{Colors.RED}   Warning: LLM returned None for Diploma parsing.{Colors.END}")
        return {"degree": "Unbekannt", "error": "LLM returned None"}
    try:
        return json.loads(clean_and_repair_json(response.text))
    except Exception as e:
        print(f"   Warning: could not parse Diploma JSON: {e}")
        return {"degree": "Unbekannt", "error": str(e)}

# Parse Other PDF
def parse_sonstiges_pdf(file_path):
    import fitz
    print(f"   Parsing Document '{file_path}' via LLM...")
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    init_gemini()
    prompt = f"""
    Analysiere dieses Dokument und extrahiere die folgenden Informationen im JSON-Format.
    Gib NUR das reine JSON-Dokument zurück, ohne zusätzliche Erklärung, Markdown-Tags (wie ```json) oder Formatierung.
    
    Struktur des erwarteten JSON:
    {{
      "title": "Kompakter Titel / Beschreibung des Dokuments",
      "topic": "Hauptthema / Kategorie des Dokuments",
      "content_summary": "Kurze Zusammenfassung des Inhalts",
      "extracted_text": "Gesamter extrahierter Text (gekürzt auf die ersten 3000 Zeichen)"
    }}
    
    Text des Dokuments:
    {text[:5000]}
    """
    response = llm_request_with_fallback(prompt)
    if response is None:
        print(f"{Colors.RED}   Warning: LLM returned None for Document parsing.{Colors.END}")
        return {"title": os.path.basename(file_path), "error": "LLM returned None"}
    try:
        return json.loads(clean_and_repair_json(response.text))
    except Exception as e:
        print(f"   Warning: could not parse Document JSON: {e}")
        return {"title": os.path.basename(file_path), "error": str(e)}

# Index workspace PDF files and update SQLite database
def index_candidate_files(workspace_dir, conn, criteria_path=None):
    import fitz
    import glob
    print(f"\n{Colors.MAGENTA}{Colors.BOLD}--- Indexing candidate PDF files ---{Colors.END}")
    
    # Scan documents/ and output/ for PDF files
    project_root = os.path.dirname(workspace_dir)
    doc_pattern = os.path.join(project_root, "documents", "*.pdf")
    out_pattern = os.path.join(workspace_dir, "output", "*.pdf")
    pdf_files = glob.glob(doc_pattern) + glob.glob(out_pattern)
    
    # Get current records in database and normalize stored paths to relative from workspace_dir
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, file_size, mtime, classification FROM candidate_files")
    rows = cursor.fetchall()
    
    def to_rel(p):
        return os.path.relpath(p, workspace_dir) if os.path.isabs(p) else p
    
    def to_abs(p):
        return os.path.normpath(os.path.join(workspace_dir, p)) if not os.path.isabs(p) else p
    
    db_records = {}
    for row in rows:
        old_path = row[0]
        rel_path = to_rel(old_path)
        abs_path = to_abs(rel_path)
        # Migrate old absolute paths to relative in DB
        if rel_path != old_path:
            cursor.execute("UPDATE candidate_files SET file_path = ? WHERE file_path = ?", (rel_path, old_path))
        db_records.setdefault(rel_path, {})["size"] = row[1]
        db_records[rel_path]["mtime"] = row[2]
        db_records[rel_path]["classification"] = row[3]
    conn.commit()
    
    detected_abs = set(pdf_files)
    detected_rel = {to_rel(f) for f in detected_abs}
    db_rel_files = set(db_records.keys())
    
    added_rel = detected_rel - db_rel_files
    deleted_files = db_rel_files - detected_rel
    modified_files = set()
    
    for f_rel in detected_rel & db_rel_files:
        f_abs = to_abs(f_rel)
        try:
            stats = os.stat(f_abs)
            if stats.st_size != db_records[f_rel]["size"] or abs(stats.st_mtime - db_records[f_rel]["mtime"]) > 1e-3:
                modified_files.add(f_abs)
        except Exception:
            pass
            
    # Process deletions
    for f in deleted_files:
        print(f" {Colors.RED}- Detected deleted candidate file: {f}{Colors.END}")
        cursor.execute("DELETE FROM candidate_files WHERE file_path = ?", (f,))
    if deleted_files:
        conn.commit()
        
    # Process additions and modifications
    files_to_process = {to_abs(f_rel) for f_rel in added_rel} | modified_files
    for f in files_to_process:
        f_rel = to_rel(f)
        print(f" {Colors.CYAN}- Found new/modified candidate file: {f_rel}{Colors.END}")
        doc_text = ""
        try:
            doc = fitz.open(f)
            if len(doc) > 0:
                doc_text = doc[0].get_text()[:1000]
            doc.close()
        except Exception as e:
            print(f"   Warning: could not read text from {f}: {e}")
            
        # Classify document using LLM — with filename fast-path for obvious names
        classification = "Sonstiges"
        filename_lower = os.path.basename(f).lower()
        
        # Fast-path: use filename for obvious cases (free, instant)
        if "lebenslauf" in filename_lower or "cv" in filename_lower:
            classification = "Lebenslauf"
        elif "anschreiben" in filename_lower or "cover_letter" in filename_lower:
            classification = "Anschreiben"
        elif "zertifikat" in filename_lower or "certificate" in filename_lower:
            classification = "Zertifikat"
        elif "zeugnis" in filename_lower or "diplom" in filename_lower or "degree" in filename_lower:
            classification = "Diplom"
        
        # For ambiguous filenames or if we have text, use LLM
        if classification == "Sonstiges" and doc_text:
            init_gemini()
            prompt = PROMPTS.get("classify_document_prompt").format(
                filename=os.path.basename(f),
                doc_text=doc_text[:1500]
            )
            try:
                resp = llm_request_with_fallback(prompt)
                if resp:
                    resp_text = resp.text.strip()
                    if resp_text.startswith("```json"): resp_text = resp_text[7:]
                    if resp_text.startswith("```"): resp_text = resp_text[3:]
                    if resp_text.endswith("```"): resp_text = resp_text[:-3]
                    result = json.loads(clean_and_repair_json(resp_text.strip()))
                    classification = result.get("classification", "Sonstiges")
                    conf = result.get("confidence", 0)
                    reason = result.get("reasoning", "")
                    print(f"   {Colors.GREY}LLM classified:{Colors.END} {classification} (confidence: {conf:.0%}) — {reason}")
            except Exception as e:
                print(f"   {Colors.YELLOW}Warning: LLM classification failed for {f}: {e}. Defaulting to 'Sonstiges'.{Colors.END}")
        
        print(f"   Classified as: {Colors.YELLOW}{Colors.BOLD}{classification}{Colors.END}")
        
        # Parse based on classification
        parsed_data = {}
        try:
            if classification == "Lebenslauf":
                profile_json_path = os.path.join(workspace_dir, "config", "candidate_profile.json")
                parsed_data = parse_cv(f, profile_json_path, criteria_path)
            elif classification == "Anschreiben":
                parsed_data = parse_anschreiben_pdf(f)
            elif classification == "Zertifikat":
                parsed_data = parse_zertifikat_pdf(f)
            elif classification == "Diplom":
                parsed_data = parse_diplom_pdf(f)
            else:
                parsed_data = parse_sonstiges_pdf(f)
        except Exception as e:
            print(f"   Error parsing {classification} data: {e}")
            parsed_data = {"error": str(e)}
            
        # Insert or replace in database (store path relative to workspace_dir)
        try:
            stats = os.stat(f)
            parsed_json_str = json.dumps(parsed_data, ensure_ascii=False)
            cursor.execute("""
                INSERT OR REPLACE INTO candidate_files (file_path, file_size, mtime, classification, parsed_json)
                VALUES (?, ?, ?, ?, ?)
            """, (f_rel, stats.st_size, stats.st_mtime, classification, parsed_json_str))
            conn.commit()
        except Exception as e:
            print(f"   Error saving document metadata to database: {e}")
            
    print(f"{Colors.GREEN}Candidate file index is up to date.{Colors.END}\n")

def create_git_restore_commit(workspace_dir):
    import subprocess
    # Git repo root is the parent of src/
    git_dir = os.path.dirname(workspace_dir) if os.path.basename(workspace_dir) == "src" else workspace_dir
    print(f" {Colors.BLUE}- Staging changes and creating backup commit ('RESTORE')...{Colors.END}")
    try:
        if not os.path.exists(os.path.join(git_dir, ".git")):
            print(f"   {Colors.YELLOW}No Git repository (.git) found in '{git_dir}'. Skipping backup commit.{Colors.END}")
            return
            
        subprocess.run(["git", "add", "."], cwd=git_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=git_dir, capture_output=True, text=True, check=True)
        if status_res.stdout.strip():
            subprocess.run(["git", "commit", "-m", "RESTORE"], cwd=git_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f" {Colors.GREEN}- Created backup commit 'RESTORE'.{Colors.END}")
        else:
            print(f" {Colors.GREEN}- Working tree is clean. No changes to commit.{Colors.END}")
    except Exception as e:
        print(f"   {Colors.RED}Warning: Failed to create backup commit: {e}{Colors.END}")

# Reset candidate data, delete database and generated files, restore default stubs
def reset_candidate_data(workspace_dir, config_path, criteria_path, profile_path):
    import glob
    print(f"\n{Colors.RED}{Colors.BOLD}--- Resetting Candidate Data and Cleaning Workspace ---{Colors.END}")
    
    # 1. First action: Create git backup commit "RESTORE"
    create_git_restore_commit(workspace_dir)
    
    # 2. Delete all PDF, HTML, and PNG files in workspace (src), output, and documents folder
    project_root = os.path.dirname(workspace_dir)
    cleanup_patterns = [
        os.path.join(workspace_dir, "*.pdf"),
        os.path.join(workspace_dir, "output", "*.pdf"),
        os.path.join(project_root, "documents", "*.pdf"),
        os.path.join(workspace_dir, "*.html"),
        os.path.join(workspace_dir, "output", "*.html"),
        os.path.join(workspace_dir, "*.png"),
        os.path.join(workspace_dir, "output", "*.png")
    ]
    for pattern in cleanup_patterns:
        for f in glob.glob(pattern):
            if f.endswith(".sample"):
                continue
            try:
                os.remove(f)
                print(f" {Colors.RED}- Deleted file: {f}{Colors.END}")
            except Exception as e:
                print(f"   {Colors.RED}Error deleting file {f}: {e}{Colors.END}")
                
    # 3. Delete SQLite database and any other databases
    db_patterns = [
        os.path.join(workspace_dir, "output", "*.db"),
        os.path.join(workspace_dir, "output", "*.sqlite"),
        os.path.join(workspace_dir, "*.db"),
        os.path.join(workspace_dir, "*.sqlite")
    ]
    for pattern in db_patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f" {Colors.RED}- Deleted database file: {f}{Colors.END}")
            except Exception as e:
                print(f"   {Colors.RED}Error deleting database {f}: {e}{Colors.END}")

                
    # 3. Define default stubs for fallback recreation of .sample files if they are missing
    default_config = """user_profile:
  chrome_data_dir: "C:\\\\Users\\\\<Username>\\\\AppData\\\\Local\\\\Google\\\\Chrome\\\\User Data"
  chrome_profile: "Default"
  cv_path: "Lebenslauf_UserName.pdf"
  documents_dir: "documents"

defaults:
  salary_expectation: "nach Vereinbarung"
  availability: "sofort"
  work_permit: "Germany"
  notice_period: "3 Monate"

criteria:
  min_score: 8.0
  min_salary_eur: 40000
  remote_allowed: true
  german_level: "B1"
  excluded_companies: []

gemini:
  model: "gemini-2.5-flash"
  api_keys:
    - "<YOUR_GEMINI_API_KEY_1>"
    - "<YOUR_GEMINI_API_KEY_2>"
    - "<YOUR_GEMINI_API_KEY_3>"
    - "<YOUR_GEMINI_API_KEY_4>"
"""

    default_criteria = """scoring:
  min_score_to_apply: 8.0

ko_filters:
  salary:
    min_annual_eur: 40000

  clearances:
    forbidden_keywords: []

  certifications:
    mandatory_if_specified: []

  education:
    require_it_degree_strictly: false
    block_degree_only_roles: false

  languages:
    min_required_english: "A2"
    min_required_german: "B1"

  datacenter_physical_work:
    forbidden: false
    keywords: []

  spam_providers:
    blocked_keywords: []
    allow_internship: true

  companies_blacklist: []
  forbidden_titles: []

cover_letter:
  mandatory_skills: []
  career_start_year: 2020
"""

    default_profile_dict = {
        "personal_info": {
            "first_name": "<Vorname>",
            "last_name": "<Nachname>",
            "email": "candidate.email@example.com",
            "phone": "01521 1234567",
            "address": "Hauptstr. 1",
            "city": "60311 Frankfurt am Main",
            "country": "Deutschland"
        },
        "languages": {
            "Deutsch": "B2",
            "Englisch": "A2"
        },
        "skills": [
            "Linux",
            "Python",
            "Bash",
            "PowerShell",
            "Java",
            "Git",
            "Docker",
            "Kommandozeile (Console)",
            "Künstliche Intelligenz (AI / LLM)"
        ],
        "experience_years": 10.0,
        "education": [
            {
                "degree": "Abschluss als Industriemechaniker",
                "field": "Industriemechanik",
                "institution": "Technische Schule",
                "year": 2010
            }
        ],
        "certifications": [
            "AWS Certified Cloud Practitioner",
            "Cisco CCST Networking"
        ]
    }
    
    prompts_path = os.path.join(workspace_dir, "config", "prompts.yaml")
    
    # 4. Delete active configuration files
    active_files = [
        (config_path, "config.yaml"),
        (criteria_path, "job_criteria.yaml"),
        (profile_path, "candidate_profile.json"),
        (prompts_path, "prompts.yaml")
    ]
    for path, name in active_files:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f" {Colors.RED}- Deleted active config file: {path}{Colors.END}")
            except Exception as e:
                print(f"   {Colors.RED}Error deleting {name}: {e}{Colors.END}")
                
    # 5. Ensure the .sample files are left intact or created if missing
    sample_files = [
        (config_path + ".sample", "config.yaml.sample", default_config),
        (criteria_path + ".sample", "job_criteria.yaml.sample", default_criteria),
        (profile_path + ".sample", "candidate_profile.json.sample", json.dumps(default_profile_dict, ensure_ascii=False, indent=2)),
        (prompts_path + ".sample", "prompts.yaml.sample", yaml.safe_dump(DEFAULT_PROMPTS, allow_unicode=True))
    ]
    for path, name, default_content in sample_files:
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(default_content)
                print(f" {Colors.YELLOW}- Created missing template stub: {name}{Colors.END}")
            except Exception as e:
                print(f"   {Colors.RED}Error creating sample file {name}: {e}{Colors.END}")
        else:
            print(f" {Colors.GREEN}- Kept existing template stub: {name}{Colors.END}")
            
    print(f"{Colors.GREEN}{Colors.BOLD}Workspace reset completed successfully.{Colors.END}\n")

# Unified LLM-based job intake: validates job, extracts metadata, detects industry,
# checks forbidden titles, KO filters, and duplicates — all in one prompt.
def job_intake_check(page_title, job_text, url, candidate_profile, criteria, conn):
    """
    Replaces: detect_industry(), compute_forbidden_titles(), check_local_ko_filters(),
    rule-based metadata extraction, and dead-link keyword lists.
    Uses job_intake_prompt to get a structured JSON with all intake decisions.
    """
    init_gemini()
    # Load KO filter data from criteria for the prompt
    ko = criteria.get("ko_filters", {})
    excluded_companies = ", ".join(ko.get("companies_blacklist", []))
    forbidden_titles = ", ".join(ko.get("forbidden_titles", []))
    clearance_keywords = ", ".join(ko.get("clearances", {}).get("forbidden_keywords", []))
    mandatory_certifications = ", ".join(ko.get("certifications", {}).get("mandatory_if_specified", []))
    spam_keywords = ", ".join(ko.get("spam_providers", {}).get("blocked_keywords", []))
    datacenter_keywords = ", ".join(ko.get("datacenter_physical_work", {}).get("keywords", []))
    min_salary = ko.get("salary", {}).get("min_annual_eur", 36000)
    candidate_german = ko.get("languages", {}).get("min_required_german", "B1")
    candidate_english = ko.get("languages", {}).get("min_required_english", "A2")

    # Get recent applications for duplicate checking
    cursor = conn.cursor()
    cursor.execute("SELECT company_name, job_title FROM applied_jobs ORDER BY id DESC LIMIT 30")
    previous_applications = "\n".join([f"- {r[0]} | {r[1]}" for r in cursor.fetchall()])
    if not previous_applications:
        previous_applications = "Keine bisherigen Bewerbungen"

    prompt = PROMPTS.get("job_intake_prompt").format(
        page_title=page_title,
        page_text=job_text[:3000] if job_text else "",
        url=url,
        candidate_profile=json.dumps(candidate_profile, ensure_ascii=False, indent=2),
        excluded_companies=excluded_companies or "Keine",
        forbidden_titles=forbidden_titles or "Keine",
        clearance_keywords=clearance_keywords or "Keine",
        mandatory_certifications=mandatory_certifications or "Keine",
        spam_keywords=spam_keywords or "Keine",
        datacenter_keywords=datacenter_keywords or "Keine",
        min_salary=min_salary,
        candidate_german=candidate_german,
        candidate_english=candidate_english,
        previous_applications=previous_applications
    )
    try:
        t0 = time.time()  # DEBUG: LLM timing
        response = llm_request_with_fallback(prompt)
        if response is None:
            return {"is_valid_job": True, "company_name": "Unbekannt", "job_title": "Unbekannt",
                    "industry": "Allgemein", "forbidden_title_detected": False,
                    "is_duplicate": False, "ko_triggered": False}
        text = clean_and_repair_json(response.text)
        result = json.loads(text)
        debug_print(f"job_intake_check done in {time.time()-t0:.1f}s", prefix="INTAKE")
        return result
    except Exception as e:
        debug_print(f"job_intake_check FAILED: {e}", prefix="INTAKE")
        print(f"{Colors.YELLOW}Warning: job_intake LLM call failed: {e}. Falling back to allow.{Colors.END}")
        return {"is_valid_job": True, "company_name": "Unbekannt", "job_title": "Unbekannt",
                "industry": "Allgemein", "forbidden_title_detected": False,
                "is_duplicate": False, "ko_triggered": False}

# Score job description against the candidate profile
def score_job(candidate_profile, job_description, config, criteria, past_rejections=None, industry="Allgemein", mandatory_skills=None):
    init_gemini()
    if criteria is None:
        criteria = load_criteria()
    min_salary = criteria.get("ko_filters", {}).get("salary", {}).get("min_annual_eur", 50000)
    candidate_german = criteria.get("ko_filters", {}).get("languages", {}).get("min_required_german", "B1")
    candidate_english = criteria.get("ko_filters", {}).get("languages", {}).get("min_required_english", "A2")
    clearance_keywords = criteria.get("ko_filters", {}).get("clearances", {}).get("forbidden_keywords", [])
    certifications = criteria.get("ko_filters", {}).get("certifications", {}).get("mandatory_if_specified", [])
    datacenter_keywords = criteria.get("ko_filters", {}).get("datacenter_physical_work", {}).get("keywords", [])
    spam_keywords = criteria.get("ko_filters", {}).get("spam_providers", {}).get("blocked_keywords", [])
    career_start_year = criteria.get("cover_letter", {}).get("career_start_year", 2010)
    
    rejections_str = ""
    if past_rejections:
        rejections_str = "\nBisherige Ablehnungsgründe des Kandidaten (vermeide Stellen mit ähnlichen Kriterien/Ausschlusskriterien):\n"
        for r in set(past_rejections):
            rejections_str += f"- {r}\n"
            
    print(f"{Colors.BLUE}Evaluating job description with Gemini Flash...{Colors.END}")
    prompt_key = f"scoring_prompt_{industry}"
    if prompt_key not in PROMPTS:
        prompt_key = "scoring_prompt"
    industry_skills_str = ", ".join(mandatory_skills) if mandatory_skills else "Keine"
    print(f"  {Colors.GREY}Industry:{Colors.END} {Colors.CYAN}{industry}{Colors.END}  {Colors.GREY}Scoring prompt:{Colors.END} {Colors.CYAN}{prompt_key}{Colors.END}")
    prompt = PROMPTS.get(prompt_key).format(
        candidate_profile=json.dumps(candidate_profile, ensure_ascii=False, indent=2),
        job_description=job_description,
        rejections_str=rejections_str,
        career_start_year=career_start_year,
        candidate_german=candidate_german,
        candidate_english=candidate_english,
        clearance_keywords=", ".join(clearance_keywords),
        certifications=", ".join(certifications),
        min_salary=min_salary,
        spam_keywords=", ".join(spam_keywords),
        datacenter_keywords=", ".join(datacenter_keywords),
        mandatory_skills=industry_skills_str
    )
    t0 = time.time()  # DEBUG: LLM timing
    try:
        response = llm_request_with_fallback(prompt)
        if response is None:
            print(f"{Colors.RED}Warning: LLM returned None response. Skipping this job.{Colors.END}")
            return {"total_score": 0.0, "ko_criterion_triggered": True, "reasoning": "LLM returned None"}
        text = clean_and_repair_json(response.text)
        debug_print(f"score_job done in {time.time()-t0:.1f}s", prefix="SCORE")
        result = json.loads(text)
        if not isinstance(result, dict):
            print(f"{Colors.RED}Warning: Scoring response is not a JSON object: {text[:200]}. Skipping this job.{Colors.END}")
            return {"total_score": 0.0, "ko_criterion_triggered": True, "reasoning": "Non-dict response"}
        return result
    except Exception as e:
        debug_print(f"score_job FAILED: {e}", prefix="SCORE")
        print(f"{Colors.RED}Warning: Could not parse scoring JSON: {e}. Skipping this job.{Colors.END}")
        return {"total_score": 0.0, "ko_criterion_triggered": True, "reasoning": "JSON parse error"}

# Generate cover letter text
def generate_anschreiben(candidate_profile, job_description, config, criteria=None, cv_text=None, industry="Allgemein", mandatory_skills=None):
    print(f"{Colors.BLUE}Drafting Anschreiben with Gemini Flash...{Colors.END}")
    init_gemini()

    if criteria is None:
        criteria = load_criteria()
    career_start_year = criteria.get("cover_letter", {}).get("career_start_year", 2010)
    
    if mandatory_skills is None:
        industry_cfg = criteria.get("industries", {}).get(industry, {})
        mandatory_skills = industry_cfg.get("cover_letter", {}).get("mandatory_skills", [])
    
    prompt_key = f"cover_letter_prompt_{industry}"
    if prompt_key not in PROMPTS:
        prompt_key = "cover_letter_prompt"
    print(f"  {Colors.GREY}Industry:{Colors.END} {Colors.CYAN}{industry}{Colors.END}  {Colors.GREY}Cover letter prompt:{Colors.END} {Colors.CYAN}{prompt_key}{Colors.END}")
    
    salary_exp = config["defaults"].get("salary_expectation", "nach Vereinbarung")
    availability = config["defaults"].get("availability", "sofort")
    candidate_german = config["criteria"].get("german_level", "B1")
    
    prompt = PROMPTS.get(prompt_key).format(
        candidate_profile=json.dumps(candidate_profile, ensure_ascii=False, indent=2),
        job_description=job_description,
        cv_text=cv_text or "Nicht verfügbar",
        salary_exp=salary_exp,
        availability=availability,
        candidate_german=candidate_german,
        career_start_year=career_start_year,
        mandatory_skills=", ".join(mandatory_skills)
    )
    t0 = time.time()  # DEBUG: LLM timing
    response = llm_request_with_fallback(prompt)
    if response is None:
        print(f"{Colors.RED}Warning: LLM returned None for cover letter generation. Returning empty.{Colors.END}")
        return {"subject": "Bewerbung", "salutation": "Sehr geehrte Damen und Herren,",
                "body": "Leider konnte kein Anschreiben generiert werden.",
                "closing": "Mit freundlichen Grüßen",
                "full_text": "Leider konnte kein Anschreiben generiert werden."}
    debug_print(f"generate_anschreiben done in {time.time()-t0:.1f}s", prefix="ANSCHREIBEN")
    raw_text = response.text.strip()
    # Try to parse structured JSON from LLM
    try:
        data = json.loads(clean_and_repair_json(raw_text))
        if isinstance(data, dict) and "body" in data:
            full_text = f"{data.get('subject', 'Bewerbung')}\n\n{data.get('salutation', 'Sehr geehrte Damen und Herren,')}\n\n{data.get('body', '')}\n\n{data.get('closing', 'Mit freundlichen Grüßen')}"
            data["full_text"] = full_text
            return data
    except Exception:
        pass
    # Fallback: treat as plain text
    return {"subject": "Bewerbung", "salutation": "Sehr geehrte Damen und Herren,",
            "body": "", "closing": "Mit freundlichen Grüßen", "full_text": raw_text}

# Render Anschreiben text as a beautiful DIN 5008 PDF using Playwright
# Accepts either a dict (from generate_anschreiben) or a plain string (backward compat)
def save_anschreiben_pdf(anschreiben_text, company_name, candidate_profile, output_path, browser_context=None):
    print(f"{Colors.CYAN}Rendering Anschreiben PDF to '{output_path}'...{Colors.END}")
    pi = candidate_profile.get('personal_info', {})
    raw_name = pi.get('name', pi.get('first_name', '') + ' ' + pi.get('last_name', '')).strip()
    sender_name = raw_name if raw_name else 'Bewerber'
    raw_loc = pi.get('location', '')
    if raw_loc and ',' in raw_loc:
        loc_parts = [p.strip() for p in raw_loc.split(',')]
        sender_address = loc_parts[0]
        city = loc_parts[-1]
    else:
        sender_address = pi.get('address', '')
        city = pi.get('city', raw_loc or 'Berlin')
    sender_email = pi.get('email', '')
    sender_phone = pi.get('phone', '')
    date_str = datetime.date.today().strftime("%d.%m.%Y")
    
    # Extract structured fields from dict (Phase 8) or fallback to plain text
    if isinstance(anschreiben_text, dict):
        subject = anschreiben_text.get("subject", "Bewerbung")
        salutation = anschreiben_text.get("salutation", "Sehr geehrte Damen und Herren,")
        raw_body = anschreiben_text.get("body", "")
        body_html = "".join([f"<p>{p.strip()}</p>" for p in raw_body.split("\n") if p.strip()])
        if not body_html:
            body_html = "<p>" + anschreiben_text.get("full_text", "").replace("\n", "</p><p>") + "</p>"
    else:
        # Backward compat: plain string
        subject = "Bewerbung"
        salutation = "Sehr geehrte Damen und Herren,"
        body_html = "<p>" + anschreiben_text.replace("\n", "</p><p>") + "</p>"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
      @page {{
        size: A4;
        margin: 25mm 20mm 20mm 20mm;
      }}
      body {{
        font-family: Arial, sans-serif;
        font-size: 11pt;
        line-height: 1.5;
        color: #333333;
      }}
      .sender {{
        text-align: right;
        margin-bottom: 10mm;
        font-size: 9.5pt;
        color: #666666;
      }}
      .recipient {{
        margin-bottom: 15mm;
        font-size: 10.5pt;
      }}
      .date {{
        text-align: right;
        margin-bottom: 10mm;
      }}
      .subject {{
        font-weight: bold;
        font-size: 12pt;
        margin-bottom: 8mm;
      }}
      .salutation {{
        margin-bottom: 6mm;
      }}
      .content {{
        text-align: justify;
      }}
      .content p {{
        margin-bottom: 4mm;
      }}
      .closing {{
        margin-top: 8mm;
      }}
    </style>
    </head>
    <body>
      <div class="sender">
        <strong>{sender_name}</strong><br>
        {sender_address}<br>
        {sender_email} | {sender_phone}
      </div>
      
      <div class="recipient">
        <strong>{company_name} GmbH</strong><br>
        Ansprechpartner für Bewerbungen<br>
        Deutschland
      </div>
      
      <div class="date">
        {city}, {date_str}
      </div>
      
      <div class="subject">
        {subject}
      </div>
      
      <div class="salutation">
        {salutation}
      </div>
      
      <div class="content">
        {body_html}
      </div>
      
      <div class="closing">
        Mit freundlichen Grüßen<br><br><br>
        <strong>{sender_name}</strong>
      </div>
    </body>
    </html>
    """
    
    pdf_done = False
    if browser_context:
        try:
            pdf_page = browser_context.new_page()
            pdf_page.set_content(html_content)
            pdf_page.pdf(path=output_path, format="A4")
            pdf_page.close()
            pdf_done = True
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: Direct PDF generation via active context failed: {e}{Colors.END}")
            
    if not pdf_done:
        try:
            from concurrent.futures import ThreadPoolExecutor
            from playwright.sync_api import sync_playwright
            def _render_pdf():
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    pdf_page = browser.new_page()
                    pdf_page.set_content(html_content)
                    pdf_page.pdf(path=output_path, format="A4")
                    pdf_page.close()
                    browser.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_render_pdf).result(timeout=90)
            pdf_done = True
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: Could not generate PDF even with separate thread: {e}{Colors.END}")
        
    if pdf_done:
        print(f"{Colors.GREEN}Successfully generated PDF Cover Letter at '{output_path}'{Colors.END}")
    else:
        print(f"{Colors.YELLOW}Warning: Continuing without PDF for this application.{Colors.END}")

def get_browser_info():
    """Find installed Chrome/Chromium and return (executable_path, channel, user_data_dir_default)."""
    import shutil
    import platform
    system = platform.system()
    
    # 1. Detect Executable and Channel
    # Priority: google-chrome -> chromium -> brave -> etc.
    found_cmd = None
    channel = None
    
    # List of commands to check in PATH
    cmds = ["google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser", "brave-browser", "msedge"]
    for cmd in cmds:
        if shutil.which(cmd):
            found_cmd = cmd
            if "chrome" in cmd: channel = "chrome"
            elif "msedge" in cmd: channel = "msedge"
            else: channel = None # Default for chromium
            break
            
    # System specific paths if not in PATH
    if not found_cmd:
        if system == "Windows":
            # Windows common locations
            prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
            prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            
            search_paths = [
                (os.path.join(prog_files, "Google\\Chrome\\Application\\chrome.exe"), "chrome"),
                (os.path.join(prog_files_x86, "Google\\Chrome\\Application\\chrome.exe"), "chrome"),
                (os.path.join(local_appdata, "Google\\Chrome\\Application\\chrome.exe"), "chrome"),
                (os.path.join(local_appdata, "Chromium\\Application\\chrome.exe"), None),
                (os.path.join(prog_files, "Microsoft\\Edge\\Application\\msedge.exe"), "msedge"),
            ]
            for p, c in search_paths:
                if os.path.exists(p):
                    found_cmd = p
                    channel = c
                    break
        elif system == "Linux":
            linux_paths = [
                ("/usr/bin/google-chrome", "chrome"),
                ("/usr/bin/google-chrome-stable", "chrome"),
                ("/usr/bin/chromium", None),
                ("/usr/bin/chromium-browser", None),
                ("/usr/bin/brave-browser", None),
            ]
            for p, c in linux_paths:
                if os.path.exists(p):
                    found_cmd = p
                    channel = c
                    break

    # 2. Detect Default User Data Directory
    data_dir = None
    if system == "Windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            if channel == "chrome":
                data_dir = os.path.join(local_appdata, "Google", "Chrome", "User Data")
            elif channel == "msedge":
                data_dir = os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
            else:
                # Check for Chromium, then fallback to Chrome
                chromium_dir = os.path.join(local_appdata, "Chromium", "User Data")
                if os.path.exists(chromium_dir):
                    data_dir = chromium_dir
                else:
                    data_dir = os.path.join(local_appdata, "Google", "Chrome", "User Data")
    elif system == "Linux":
        # Priority: google-chrome -> chromium
        chrome_dir = os.path.expanduser("~/.config/google-chrome")
        chromium_dir = os.path.expanduser("~/.config/chromium")
        if channel == "chrome":
            data_dir = chrome_dir
        elif os.path.exists(chromium_dir):
            data_dir = chromium_dir
        else:
            data_dir = chrome_dir
    elif system == "Darwin":
        data_dir = os.path.expanduser("~/Library/Application Support/Google/Chrome")

    return found_cmd, channel, data_dir

def check_chrome_installed():
    cmd, _, _ = get_browser_info()
    return cmd is not None

def detect_chrome_user_data_dir():
    _, _, data_dir = get_browser_info()
    return data_dir

# Playwright Browser session setup
def get_browser_context(playwright_instance, config, headless=False):
    """
    Acquire a browser context. 
    Attempts to:
    1. Connect to an existing session on port 9222.
    2. Launch a persistent context using the configured or detected profile.
    3. Fallback only if absolutely necessary, with loud warnings.
    """
    found_cmd, channel, default_data_dir = get_browser_info()
    
    if not found_cmd:
        print(f"\n{Colors.RED}{Colors.BOLD}No Chrome/Chromium browser found!{Colors.END}")
        print("Please install a compatible browser (Chrome, Chromium, Edge, Brave) to use this agent.")
        sys.exit(1)

    # Try connecting to an existing debugging session first
    try:
        debug_print("Attempting CDP connection on port 9222...", prefix="BROWSER")
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1)
        print(f"{Colors.GREEN}Found active browser session on port 9222. Connecting...{Colors.END}")
        browser = playwright_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if browser.contexts:
            return browser.contexts[0], browser, True
        else:
            return browser.new_context(), browser, True
    except Exception:
        pass # Proceed to launch if no CDP session found


    # Determine User Data Directory
    data_dir = config["user_profile"].get("chrome_data_dir")
    if not data_dir or "<username>" in data_dir.lower() or not os.path.exists(data_dir):
        data_dir = default_data_dir
        if data_dir:
            print(f"{Colors.GREEN}Using detected browser data directory: {data_dir}{Colors.END}")
            config["user_profile"]["chrome_data_dir"] = data_dir
        else:
            print(f"{Colors.RED}Could not detect browser data directory. Please configure 'chrome_data_dir' in config.yaml.{Colors.END}")
            sys.exit(1)

    profile = config["user_profile"].get("chrome_profile", "Default")
    print(f"{Colors.CYAN}Launching persistent context: '{data_dir}' (Profile: '{profile}')...{Colors.END}")
    
    try:
        debug_print("Launching persistent context...", prefix="BROWSER")
        context = playwright_instance.chromium.launch_persistent_context(
            user_data_dir=data_dir,
            channel=channel,
            headless=headless,
            ignore_default_args=["--enable-automation"],
            args=[
                f"--profile-directory={profile}",
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=9222"
            ],
            timeout=60000
        )
        return context, None, False
    except Exception as e:
        print(f"\n{Colors.RED}FAILED TO LAUNCH PERSISTENT CONTEXT: {e}{Colors.END}")
        
        # If the error is likely a lock error
        if "lock" in str(e).lower() or "used by another process" in str(e).lower() or "Target page, context or browser has been closed" in str(e):
            print(f"{Colors.YELLOW}{'!'*60}")
            print(f"THE BROWSER PROFILE IS CURRENTLY IN USE.")
            print(f"To use your existing session (and avoid re-logging), please:")
            print(f"1. CLOSE ALL Windows of your browser completely.")
            print(f"2. OR: Restart your browser with remote debugging enabled:")
            print(f"   Windows: chrome.exe --remote-debugging-port=9222")
            print(f"   Linux: google-chrome --remote-debugging-port=9222")
            print(f"{'!'*60}{Colors.END}")
            
            print(f"{Colors.YELLOW}Auto-fallback to temporary profile...{Colors.END}")
        
        # Final fallback: temp profile in current directory
        print(f"{Colors.YELLOW}Falling back to temporary profile...{Colors.END}")
        # Auto-clean stale Singleton locks from temp_profile (prevents
        # "Failed to create a ProcessSingleton" errors on repeated runs)
        import glob
        for lockfile in glob.glob("temp_profile/Singleton*"):
            try:
                os.remove(lockfile)
                print(f"  {Colors.GREY}Removed stale lock: {lockfile}{Colors.END}")
            except OSError:
                pass
        try:
            debug_print("Launching temp_profile fallback...", prefix="BROWSER")
            context = playwright_instance.chromium.launch_persistent_context(
                user_data_dir="temp_profile",
                channel=channel,
                headless=headless,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
                timeout=30000
            )
            return context, None, False
        except Exception as final_e:
            print(f"{Colors.RED}Critical: All browser launch attempts failed. {final_e}{Colors.END}")
            sys.exit(1)



def try_linkedin_easy_apply(page, candidate_profile, config, anschreiben_path, cv_path):
    current_url = page.url.lower()
    if "linkedin.com" not in current_url:
        print(f"{Colors.YELLOW}LinkedIn Easy Apply: not a LinkedIn page (url={current_url[:80]}){Colors.END}")
        return False
    try:
        easy_apply_btn = page.locator("button:has-text('Easy Apply'), button:has-text('Bewerben'), button:has-text('Apply Now'), button.jobs-apply-button")
        is_visible = easy_apply_btn.is_visible(timeout=3000)
        if not is_visible:
            print(f"{Colors.YELLOW}LinkedIn Easy Apply: button not visible on page (url={current_url[:80]}){Colors.END}")
            return False
        print(f"{Colors.CYAN}LinkedIn Easy Apply button detected. Clicking...{Colors.END}")
        easy_apply_btn.click()
        page.wait_for_timeout(2000)
        try:
            page.wait_for_selector(".jobs-easy-apply-content, .jobs-easy-apply-modal, [data-test-modal-box], .artdeco-modal", timeout=5000)
        except Exception:
            print(f"{Colors.YELLOW}Warning: Could not detect Easy Apply modal. Proceeding anyway...{Colors.END}")
        return fill_page_form(page, candidate_profile, config, anschreiben_path, cv_path)
    except Exception as e:
        print(f"{Colors.YELLOW}LinkedIn Easy Apply detection failed: {e}{Colors.END}")
        return False

# Fill page form fields using Gemini guidance
def fill_page_form(page, candidate_profile, config, anschreiben_path, cv_path):
    js_script = """
    () => {
        const elements = Array.from(document.querySelectorAll('input, textarea, select, button, [role="button"], [role="checkbox"]'));
        return elements.map((el, idx) => {
            el.setAttribute('data-agent-ref', 'agent_ref_' + idx);
            
            let labelText = "";
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${el.id}"]`);
                if (labelEl) labelText = labelEl.innerText;
            }
            if (!labelText) {
                const parentLabel = el.closest('label');
                if (parentLabel) labelText = parentLabel.innerText;
            }
            
            return {
                ref_id: 'agent_ref_' + idx,
                tag: el.tagName.toLowerCase(),
                type: el.type || "",
                name: el.name || "",
                placeholder: el.placeholder || "",
                aria_label: el.getAttribute('aria-label') || "",
                text: el.innerText || "",
                label: labelText,
                is_visible: el.offsetWidth > 0 && el.offsetHeight > 0
            };
        }).filter(item => item.is_visible && (item.tag !== 'button' || item.text || item.aria_label));
    }
    """
    try:
        elements = page.evaluate(js_script)
    except AttributeError as ae:
        print(f"{Colors.YELLOW}Form filler: page.evaluate() failed ({ae}). Trying main_frame.evaluate() fallback...{Colors.END}")
        try:
            elements = page.main_frame.evaluate(js_script)
        except Exception as fe:
            print(f"{Colors.YELLOW}Form filler: main_frame.evaluate() also failed: {fe}{Colors.END}")
            return False
    
    init_gemini()
    
    prompt = PROMPTS.get("form_filler_prompt").format(
        candidate_profile=json.dumps(candidate_profile, ensure_ascii=False, indent=2),
        salary_expectation=config["defaults"].get("salary_expectation", "60.000 €"),
        availability=config["defaults"].get("availability", "sofort"),
        work_permit=config["defaults"].get("work_permit", "EU Blue Card"),
        elements=json.dumps(elements, ensure_ascii=False, indent=2)
    )
    response = llm_request_with_fallback(prompt)
    text = response.text.strip() if hasattr(response, 'text') else str(response).strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    actions = []
    actions_succeeded = 0
    try:
        actions = json.loads(text)
        print(f"{Colors.CYAN}Gemini proposed {len(actions)} actions to fill the form:{Colors.END}")
        for act in actions:
            ref = act["ref_id"]
            action_type = act["action"]
            locator = page.locator(f"[data-agent-ref='{ref}']")
            
            try:
                if action_type == "fill":
                    val = act["value"]
                    print(f" {Colors.CYAN}- Filling {ref} with '{val}'{Colors.END}")
                    locator.fill("")
                    locator.fill(val)
                elif action_type == "click":
                    print(f" {Colors.CYAN}- Clicking {ref}{Colors.END}")
                    locator.click()
                elif action_type == "upload_cv":
                    print(f" {Colors.GREEN}- Uploading CV to {ref} ({cv_path}){Colors.END}")
                    locator.set_input_files(cv_path)
                elif action_type == "upload_cover_letter":
                    print(f" {Colors.GREEN}- Uploading Cover Letter to {ref} ({anschreiben_path}){Colors.END}")
                    locator.set_input_files(anschreiben_path)
                actions_succeeded += 1
            except Exception as act_e:
                print(f"{Colors.RED}- Action '{action_type}' on {ref} FAILED: {act_e}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}Error parsing form filling output: {e}\nRaw output was:\n{text}{Colors.END}")
    print(f"{Colors.CYAN}Form filler: {len(actions)} actions proposed, {actions_succeeded} succeeded.{Colors.END}")
    return actions_succeeded > 0

# Process a job application URL
def process_job_url(page, url, candidate_profile, config, criteria, conn, auto_approve=False, criteria_path=None, tee=None, workspace_dir=None, no_email=False, force_generate=False):
    if criteria_path is None:
        criteria_path = os.path.join(os.path.dirname(__file__), "config", "job_criteria.yaml")
    print(f"\n{Colors.GREY}{'='*80}{Colors.END}")
    debug_print("Navigating to URL...", prefix="GOTO")
    print(f"{Colors.CYAN}{Colors.BOLD}Processing vacancy: {Colors.END}{Colors.BLUE}{Colors.UNDERLINE}{url}{Colors.END}")
    print(f"{Colors.GREY}{'-'*80}{Colors.END}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"{Colors.RED}Warning: page.goto to job URL took too long or failed: {e}. Trying to proceed anyway...{Colors.END}")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        page.wait_for_timeout(2000)
    except Exception:
        pass
    
    page_title = page.title()
    print(f"  {Colors.GREY}Page title:{Colors.END} {Colors.CYAN}{page_title}{Colors.END}")
    
    # Extract body text for matching
    job_text = page.locator("body").inner_text()
    
    # Exact URL dedup (fast, no LLM)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM applied_jobs WHERE url = ?", (url,))
    if cursor.fetchone():
        print(f"{Colors.YELLOW}Skipping: URL already processed.{Colors.END}")
        debug_print("Skipping: URL already in DB", prefix="INTAKE")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
    debug_print("Calling job_intake_check (LLM)...", prefix="INTAKE")

    # Unified LLM intake: validates job, extracts metadata, detects industry,
    # checks forbidden titles, KO filters, and duplicates — all in one prompt
    print(f"  {Colors.GREY}Running unified job intake (LLM)...{Colors.END}")
    debug_print("Calling job_intake_check (LLM)...", prefix="INTAKE")
    intake = job_intake_check(page_title, job_text, url, candidate_profile, criteria, conn)
    
    if not intake.get("is_valid_job", True):
        reason = intake.get("invalid_reason", "Unknown")
        print(f"{Colors.YELLOW}Skipping: Invalid job page — {reason}{Colors.END}")
        debug_print(f"Skipping: invalid job ({reason})", prefix="INTAKE")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
        
    if intake.get("is_duplicate", False):
        dup = intake.get("duplicate_of", "unknown")
        print(f"{Colors.YELLOW}Skipping: Duplicate of {dup}{Colors.END}")
        debug_print(f"Skipping: duplicate ({dup})", prefix="INTAKE")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
        
    if intake.get("ko_triggered", False):
        ko_reason = intake.get("ko_reason", "KO filter")
        print(f"{Colors.YELLOW}Skipping: KO filter triggered — {ko_reason}{Colors.END}")
        debug_print(f"Skipping: KO filter ({ko_reason})", prefix="INTAKE")
        log_application(conn, intake.get("company_name", "Unbekannt"),
                       intake.get("job_title", "Unbekannt"), url, 0.0, "Skipped (KO)")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
        
    if intake.get("forbidden_title_detected", False):
        reason = intake.get("forbidden_title_reason", "Forbidden title")
        print(f"{Colors.YELLOW}Skipping: {reason}{Colors.END}")
        debug_print(f"Skipping: forbidden title ({reason})", prefix="INTAKE")
        log_application(conn, intake.get("company_name", "Unbekannt"),
                       intake.get("job_title", "Unbekannt"), url, 0.0, "Skipped (Low Score)")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
    
    company_name = intake.get("company_name", "Unbekannt")
    job_title = intake.get("job_title", "Unbekannt")
    industry = intake.get("industry", "Allgemein")
    
    print(f"  {Colors.GREY}Company:{Colors.END} {Colors.CYAN}{company_name}{Colors.END}")
    print(f"  {Colors.GREY}Job Title:{Colors.END} {Colors.CYAN}{job_title}{Colors.END}")
    print(f"  {Colors.GREY}Industry:{Colors.END} {Colors.CYAN}{industry}{Colors.END}")
    if intake.get("industry_reasoning"):
        print(f"    {Colors.GREY}→ {intake['industry_reasoning']}{Colors.END}")
    
    # Secondary dedup check (company+title cleanup)
    if is_already_applied(conn, company_name, job_title, url):
        print(f"{Colors.YELLOW}Skipping: Duplicate by company/title match.{Colors.END}")
        debug_print("Skipping: duplicate by company/title", prefix="INTAKE")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
    
    # Get mandatory skills from industry config
    industry_cfg = criteria.get("industries", {}).get(industry, {})
    mandatory_skills = industry_cfg.get("cover_letter", {}).get("mandatory_skills", [])
    
    # Score job (skip if --force-generate)
    if force_generate:
        print(f"  {Colors.YELLOW}{Colors.BOLD}[FORCE-GENERATE] Skipping scoring, generating Anschreiben directly...{Colors.END}")
        debug_print("FORCE-GENERATE mode — skipping scoring, generating directly", prefix="SCORE")
        total_score = 10.0
        debug_print(f"Calling score_job (LLM) for {industry}...", prefix="SCORE")
        is_ko = False
    else:
        past_rejections = get_past_rejections(conn)
        yaml_rejections = criteria.get("ko_filters", {}).get("user_rejected_reasons", [])
        if yaml_rejections:
            past_rejections = list(set(past_rejections + yaml_rejections))
        debug_print(f"Calling score_job (LLM) for {industry}...", prefix="SCORE")
        score_data = score_job(candidate_profile, job_text, config, criteria, past_rejections, industry=industry, mandatory_skills=mandatory_skills)
        total_score = score_data.get("total_score", 0.0)
        is_ko = score_data.get("ko_criterion_triggered", False)
    
    min_score = industry_cfg.get("scoring", {}).get("min_score_to_apply", 8.0) if not force_generate else 0.0
    if total_score >= min_score and not is_ko:
        print(f"  {Colors.GREY}Match Score:{Colors.END} {Colors.GREEN}{Colors.BOLD}{total_score}/10 (PASSED){Colors.END}")
    else:
        print(f"  {Colors.GREY}Match Score:{Colors.END} {Colors.RED}{Colors.BOLD}{total_score}/10 (FAILED){Colors.END}")
        
    if not force_generate and total_score < min_score:
        reason = score_data.get("reasoning", "Below minimum matching score threshold.")
        debug_print(f"Skipping: low score {total_score}/{min_score} ({reason})", prefix="SCORE")
        print(f"{Colors.RED}Skipping job: {reason}{Colors.END}")
        log_application(conn, company_name, job_title, url, total_score, "Skipped (Low Score)")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
        return
        
    # Generate Cover Letter
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
    debug_print("Calling generate_anschreiben (LLM)...", prefix="ANSCHREIBEN")
    anschreiben_data = generate_anschreiben(candidate_profile, job_text, config, criteria, cv_text=cv_text_raw, industry=industry, mandatory_skills=mandatory_skills)
    
    debug_print("Calling save_anschreiben_pdf...", prefix="PDF")
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    safe_company_name = "".join([c for c in company_name if c.isalnum() or c in (" ", "_")]).strip().replace(" ", "_")
    anschreiben_pdf_path = os.path.join(output_dir, f"Anschreiben_{safe_company_name}.pdf")
    
    try:
        pdf_context = page.context
    except Exception:
        pdf_context = None
    save_anschreiben_pdf(anschreiben_data, company_name, candidate_profile, anschreiben_pdf_path, browser_context=pdf_context)
    
    # Try direct email application if job text contains contact email
    from job_agent.direct_email_applier import extract_contact_info, collect_relevant_attachments, send_direct_email, personalize_anschreiben
    if auto_approve and not no_email:
        
        contact = extract_contact_info(job_text)
        if contact and contact.get("email"):
            print(f"{Colors.BLUE}Found contact email in job: {contact['email']}{Colors.END}")
            if contact.get("recruiter_name"):
                print(f"{Colors.BLUE}Found recruiter name: {contact['recruiter_name']}. Personalizing Anschreiben...{Colors.END}")
                # Personalize salutation in full_text and update dict for PDF
                name = contact["recruiter_name"].strip().split('\n')[0].strip()
                anschreiben_data["full_text"] = personalize_anschreiben(anschreiben_data.get("full_text", ""), name)
                # Also update salutation for PDF rendering
                nl = name.lower()
                if nl.startswith("herr "):
                    anschreiben_data["salutation"] = f"Sehr geehrter {name[5:]},"
                elif nl.startswith("frau "):
                    anschreiben_data["salutation"] = f"Sehr geehrte {name[5:]},"
                else:
                    anschreiben_data["salutation"] = f"Guten Tag {name},"
                try:
                    pdf_context = page.context
                except Exception:
                    pdf_context = None
                save_anschreiben_pdf(anschreiben_data, company_name, candidate_profile, anschreiben_pdf_path, browser_context=pdf_context)
            
            anschreiben_full_text = anschreiben_data.get("full_text", "") if isinstance(anschreiben_data, dict) else anschreiben_data
            attachments = collect_relevant_attachments(conn, job_text, anschreiben_pdf_path, workspace_dir)
            success = send_direct_email(
                config.get("smtp", {}),
                candidate_profile,
                contact,
                anschreiben_full_text,
                attachments,
                job_title,
                company_name,
                url=url
            )
            if success:
                log_application(conn, company_name, job_title, url, total_score, "Applied (Direct Email)",
                              terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                # Mark email_sent=1 since direct email was already delivered
                db_cursor = conn.cursor()
                db_cursor.execute("UPDATE applied_jobs SET email_sent = 1 WHERE url = ?", (url,))
                conn.commit()
                print(f"{Colors.GREEN}Direct email sent to {contact['email']} for {job_title} at {company_name}!{Colors.END}")
                print(f"{Colors.GREEN}Direct email application logged as 'Applied (Direct Email)'.{Colors.END}")
            else:
                log_application(conn, company_name, job_title, url, total_score, "Applied (Direct Email Failed)",
                              terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                print(f"{Colors.YELLOW}Direct email sending failed, but logged as 'Applied (Direct Email Failed)'.{Colors.END}")
            print(f"\n{Colors.GREY}{'='*80}{Colors.END}\n")
            return
    
    # Fill form
    print(f"{Colors.YELLOW}Initiating form filler...{Colors.END}")
    cv_name = config["user_profile"].get("cv_path", "Lebenslauf_UserName.pdf")
    cv_path = os.path.join(os.path.dirname(__file__), cv_name)
    
    try:
        form_filled = fill_page_form(page, candidate_profile, config, anschreiben_pdf_path, cv_path)
    except Exception as e:
        print(f"{Colors.YELLOW}Form filler failed: {e}{Colors.END}")
        form_filled = False
    
    if not form_filled:
        try:
            is_linkedin = "linkedin.com" in page.url.lower()
        except Exception:
            is_linkedin = False
        if is_linkedin:
            print(f"{Colors.YELLOW}Form filler got 0 actions on LinkedIn. Trying Easy Apply...{Colors.END}")
            try:
                form_filled = try_linkedin_easy_apply(page, candidate_profile, config, anschreiben_pdf_path, cv_path)
            except Exception as e:
                print(f"{Colors.YELLOW}LinkedIn Easy Apply failed: {e}{Colors.END}")
                form_filled = False
    
    if auto_approve:
        if form_filled:
            print(f"{Colors.GREEN}[Auto-Approve] Automatically logging application as Applied.{Colors.END}")
            log_application(conn, company_name, job_title, url, total_score, "Applied", terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
        else:
            print(f"{Colors.YELLOW}[Auto-Approve] Form filler returned 0 actions. Generating fallback draft to candidate email...{Colors.END}")
            candidate_email = candidate_profile.get("personal_info", {}).get("email")
            if candidate_email:
                fallback_contact = {"email": candidate_email, "recruiter_name": None}
                anschreiben_full_text = anschreiben_data.get("full_text", "") if isinstance(anschreiben_data, dict) else anschreiben_data
                attachments = collect_relevant_attachments(conn, job_text, anschreiben_pdf_path, workspace_dir)
                draft_ok = generate_direct_email_draft(
                    config.get("smtp", {}),
                    candidate_profile,
                    fallback_contact,
                    anschreiben_full_text,
                    attachments,
                    job_title,
                    company_name,
                    url=url,
                    terminal_output=tee.getvalue() if tee else None
                )
                if draft_ok:
                    log_application(conn, company_name, job_title, url, total_score, "Applied (Draft Generated)",
                                    terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                    db_cursor = conn.cursor()
                    db_cursor.execute("UPDATE applied_jobs SET email_sent = 1 WHERE url = ?", (url,))
                    conn.commit()
                    print(f"{Colors.GREEN}[Auto-Approve] Anschreiben sent to {candidate_email} as fallback. Logged as 'Applied (Email)'.{Colors.END}")
                else:
                    log_application(conn, company_name, job_title, url, total_score, "Applied (Email Failed)",
                                    terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                    print(f"{Colors.YELLOW}[Auto-Approve] Fallback email failed. Logged as 'Applied (Email Failed)'.{Colors.END}")
            else:
                log_application(conn, company_name, job_title, url, total_score, "Skipped (No Form Actions)",
                                terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                print(f"{Colors.YELLOW}[Auto-Approve] No candidate email and form filler returned 0 actions. Logged as 'Skipped (No Form Actions)'.{Colors.END}")
    else:
        print(f"\n{Colors.GREEN}{Colors.BOLD}" + "="*50)
        print("HUMAN-IN-THE-LOOP APPROVAL REQUIRED")
        print(f"Job: {job_title} at {company_name}")
        print(f"Cover letter saved to: {anschreiben_pdf_path}")
        print("The form fields have been filled. Please check the browser window.")
        print("Review the form, upload any other required files, and click 'Submit' yourself.")
        print("="*50 + f"{Colors.END}")
        try:
            choice = input("After submitting the form in the browser, press Enter to log as 'Applied'. Type 'cancel' to skip: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "cancel"
            print()
        if choice != "cancel":
            log_application(conn, company_name, job_title, url, total_score, "Applied", terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
            print(f"{Colors.GREEN}Logged as Applied!{Colors.END}")
        else:
            print(f"{Colors.YELLOW}Self-rejection{Colors.END}")
            reason = ""
            try:
                reason = input("Please specify the reason why you chose not to apply to this vacancy (e.g., location, travel, specific technology): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
            if reason:
                log_user_rejection(conn, company_name, job_title, url, reason)
                log_application(conn, company_name, job_title, url, total_score, "Self-rejection", terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)
                print(f"{Colors.YELLOW}Logged rejection reason: '{reason}'{Colors.END}")
                # Save reason to job_criteria.yaml under ko_filters -> user_rejected_reasons
                try:
                    with open(criteria_path, "r", encoding="utf-8") as f:
                        criteria_data = yaml.safe_load(f) or {}
                    if "ko_filters" not in criteria_data:
                        criteria_data["ko_filters"] = {}
                    if "user_rejected_reasons" not in criteria_data["ko_filters"]:
                        criteria_data["ko_filters"]["user_rejected_reasons"] = []
                    if reason not in criteria_data["ko_filters"]["user_rejected_reasons"]:
                        criteria_data["ko_filters"]["user_rejected_reasons"].append(reason)
                        with open(criteria_path, "w", encoding="utf-8") as f:
                            yaml.safe_dump(criteria_data, f, allow_unicode=True)
                        print(f"   {Colors.GREEN}Successfully added rejection reason to K.O. filters in '{os.path.basename(criteria_path)}'{Colors.END}")
                except Exception as e:
                    print(f"   {Colors.RED}Warning: Could not save rejection reason to YAML: {e}{Colors.END}")
            else:
                log_application(conn, company_name, job_title, url, total_score, "Self-rejection", terminal_output=tee.getvalue() if tee else "", pdf_path=anschreiben_pdf_path)

    print(f"\n{Colors.GREY}{'='*80}{Colors.END}\n")

# Search Indeed for job listings matching the query
def search_indeed(page, keywords, location="Deutschland", radius=25):
    print(f"{Colors.BLUE}Searching Indeed for '{keywords}' in '{location}' with radius {radius}km...{Colors.END}")
    query = "+".join(keywords.split())
    loc_encoded = urllib.parse.quote(location)
    url = f"https://de.indeed.com/jobs?q={query}&l={loc_encoded}&radius={radius}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: page.goto to Indeed took too long or failed: {e}. Trying to proceed anyway...{Colors.END}")
    
    # Fill the "Was?" search field explicitly so it's visible to the user
    try:
        page.wait_for_timeout(1000)
        what_input = page.locator("#text-input-what")
        if what_input.is_visible():
            current_val = what_input.input_value()
            if not current_val or current_val.strip() == "":
                what_input.fill(keywords)
    except Exception:
        pass
    
    try:
        page.wait_for_selector(".job_seen_beacon", timeout=8000)
    except Exception:
        # Check if Cloudflare Turnstile or security verification page is visible
        is_cloudflare = False
        try:
            content_lower = page.content().lower()
            if "verifizierung" in content_lower or "cloudflare" in content_lower or page.locator("iframe[src*='challenges']").is_visible():
                is_cloudflare = True
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: Could not check for Cloudflare (page might be navigating): {e}{Colors.END}")
            page.wait_for_timeout(2000)
            try:
                content_lower = page.content().lower()
                if "verifizierung" in content_lower or "cloudflare" in content_lower or page.locator("iframe[src*='challenges']").is_visible():
                    is_cloudflare = True
            except Exception:
                pass
                
        if is_cloudflare:
            print(f"\n{Colors.RED}{Colors.BOLD}" + "="*70)
            print("CLOUDFLARE SECURE VERIFICATION DETECTED ON INDEED!")
            print("Please open/check your Chrome browser window and solve the Cloudflare verification.")
            print("Waiting up to 45 seconds for verification to be completed...")
            print("="*70 + f"\n{Colors.END}")
            
            # Poll for the job cards to appear
            for _ in range(22):
                page.wait_for_timeout(2000)
                if page.locator(".job_seen_beacon").first.is_visible():
                    print(f"{Colors.GREEN}Verification solved! Re-navigating to search URL...{Colors.END}")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_selector(".job_seen_beacon", timeout=8000)
                    except Exception:
                        pass
                    break
            else:
                print(f"{Colors.YELLOW}Warning: Timeout waiting for Indeed job cards after Cloudflare prompt. The page might be blocked or empty.{Colors.END}")
                output_dir = os.path.join(os.path.dirname(__file__), "output")
                os.makedirs(output_dir, exist_ok=True)
                try:
                    page.screenshot(path=os.path.join(output_dir, "indeed_search_error.png"))
                except Exception:
                    pass
                return []
        else:
            print(f"{Colors.YELLOW}Warning: Timeout waiting for Indeed job cards. The page might be blocked or empty.{Colors.END}")
            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            try:
                page.screenshot(path=os.path.join(output_dir, "indeed_search_error.png"))
            except Exception:
                pass
            return []
    
    # Check if Indeed returned no results (shows suggested jobs instead)
    try:
        content = page.content().lower()
        if "keine jobs" in content or "keine treffer" in content or "0 ergebnisse" in content:
            print(f"{Colors.YELLOW}Indeed returned no results for '{keywords}' in '{location}'. Skipping Indeed.{Colors.END}")
            return []
    except Exception:
        pass
    
    try:
        links = page.eval_on_selector_all(".jcs-JobTitle", "els => els.map(el => el.href)")
        print(f"{Colors.GREEN}Found {len(links)} job listings on Indeed.{Colors.END}")
        return links
    except Exception as e:
        print(f"{Colors.RED}Error extracting Indeed links: {e}{Colors.END}")
        return []

# Search LinkedIn for job listings matching the query
def search_linkedin(page, keywords, location="Germany", radius=25):
    print(f"{Colors.BLUE}Searching LinkedIn for '{keywords}' in '{location}' with radius {radius}km...{Colors.END}")
    query = urllib.parse.quote(keywords)
    loc = urllib.parse.quote(location)
    # Convert km to miles for LinkedIn (default discrete choices: 10, 25, 50, 100 miles)
    miles = int(radius * 0.621371)
    if miles <= 10:
        distance = 10
    elif miles <= 25:
        distance = 25
    elif miles <= 50:
        distance = 50
    else:
        distance = 100
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}&distance={distance}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: page.goto to LinkedIn took too long or failed: {e}. Trying to proceed anyway...{Colors.END}")
    
    # Try to close guest login modal if it shows up
    try:
        page.wait_for_timeout(2000)
        dismiss_btn = page.locator("button.modal__dismiss, button[aria-label='Dismiss'], button[aria-label='Schließen'], button.modal__dismiss-btn")
        if dismiss_btn.is_visible():
            print(f"{Colors.YELLOW}Found guest login modal on LinkedIn. Dismissing...{Colors.END}")
            dismiss_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # Re-navigate after modal dismiss to ensure search params are preserved
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Re-navigation to LinkedIn search failed: {e}. Trying to proceed...{Colors.END}")

    try:
        page.wait_for_selector(".job-card-container, .job-card-list__title, .jobs-search__results-list li", timeout=8000)
    except Exception:
        is_login_wall = False
        try:
            content_lower = page.content().lower()
            if "einloggen" in content_lower or "sign in" in content_lower:
                is_login_wall = True
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: Could not check for LinkedIn login wall (page might be navigating): {e}{Colors.END}")
            page.wait_for_timeout(2000)
            try:
                content_lower = page.content().lower()
                if "einloggen" in content_lower or "sign in" in content_lower:
                    is_login_wall = True
            except Exception:
                pass
                
        if is_login_wall:
            print(f"\n{Colors.RED}{Colors.BOLD}" + "="*70)
            print("LINKEDIN LOGIN WALL DETECTED!")
            print("Please log in to LinkedIn in your Chrome browser window, or dismiss the popup.")
            print("Waiting up to 45 seconds...")
            print("="*70 + f"\n{Colors.END}")
            for _ in range(22):
                page.wait_for_timeout(2000)
                # Try to dismiss if popup keeps appearing
                try:
                    dismiss_btn = page.locator("button.modal__dismiss, button[aria-label='Dismiss'], button[aria-label='Schließen'], button.modal__dismiss-btn")
                    if dismiss_btn.is_visible():
                        dismiss_btn.click()
                except Exception:
                    pass
                if page.locator(".job-card-container, .job-card-list__title, .jobs-search__results-list li").first.is_visible():
                    print(f"{Colors.GREEN}Login wall cleared! Re-navigating to search URL...{Colors.END}")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    break
            else:
                print(f"{Colors.YELLOW}Warning: Timeout waiting for LinkedIn job cards.{Colors.END}")
                output_dir = os.path.join(os.path.dirname(__file__), "output")
                os.makedirs(output_dir, exist_ok=True)
                page.screenshot(path=os.path.join(output_dir, "linkedin_search_error.png"))
                return []
        else:
            print(f"{Colors.YELLOW}Warning: Timeout waiting for LinkedIn job cards.{Colors.END}")
            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            page.screenshot(path=os.path.join(output_dir, "linkedin_search_error.png"))
            return []
        
    try:
        links = page.evaluate(r"""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                const results = [];
                for (let el of links) {
                    let href = el.href;
                    if (!href) continue;
                    if (href.includes('/jobs/view/')) {
                        results.push(href);
                    } else if (href.includes('currentJobId=')) {
                        const match = href.match(/currentJobId=(\d+)/);
                        if (match) {
                            results.push(`https://www.linkedin.com/jobs/view/${match[1]}/`);
                        }
                    }
                }
                return results;
            }
        """)
        links = list(set(links))
        print(f"{Colors.GREEN}Found {len(links)} job listings on LinkedIn.{Colors.END}")
        return links
    except Exception as e:
        print(f"{Colors.RED}Error extracting LinkedIn links: {e}{Colors.END}")
        return []



def main():
    parser = argparse.ArgumentParser(description="JobAgent - Automate job applications in Germany")
    parser.add_argument("--generate-dummy-cv", action="store_true", help="Generate a mock CV PDF for testing")
    parser.add_argument("--parse-cv", action="store_true", help="Parse the CV PDF and generate candidate_profile.json")
    parser.add_argument("--test-score", type=str, help="Path to text file containing a job description to score")
    parser.add_argument("--test-anschreiben", nargs=2, metavar=('COMPANY', 'JOB_DESC_FILE'), help="Generate test Anschreiben HTML/PDF")
    parser.add_argument("--url", type=str, help="Single job listing URL to process")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode prompting for URLs")
    parser.add_argument("--search-jobs", type=str, nargs="?", const="", default=None, help="Keywords to search for job listings on Indeed and LinkedIn")
    parser.add_argument("--location", type=str, default="Deutschland", help="Location parameter for job search")
    parser.add_argument("--radius", type=int, default=25, help="Search radius/diameter around location in kilometers")
    parser.add_argument("--chrome-data-dir", type=str, help="Override Chrome user data directory path")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve applications without blocking for manual input")
    parser.add_argument("--config", type=str, default="config/config.yaml", help="Path to config.yaml configuration file (relative to src/ or absolute)")
    parser.add_argument("--profile", type=str, default="config/candidate_profile.json", help="Path to candidate_profile.json profile file (relative to src/ or absolute)")
    parser.add_argument("--criteria", type=str, default="config/job_criteria.yaml", help="Path to job_criteria.yaml criteria file (relative to src/ or absolute)")
    parser.add_argument("--reset-candidate", action="store_true", help="Clean candidate files and return settings to default stubs")
    parser.add_argument("--send-email", action="store_true", help="Send email summaries for all successfully applied jobs")
    parser.add_argument("--pipeline", action="store_true", help="Use GDPR-compliant pipeline: official APIs, local LLM, email drafts")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode (no visible browser window)")
    parser.add_argument("--no-email", action="store_true", help="Skip direct email sending to employers during testing")
    parser.add_argument("--debug", action="store_true", help="[DEBUG] Enable verbose debug output at bottleneck points")
    parser.add_argument("--force-generate", action="store_true", help="[DEBUG] Skip scoring, generate Anschreiben directly")
    
    args = parser.parse_args()
    if args.debug:
        global DEBUG
        DEBUG = True
        debug_print("Debug mode enabled — verbose bottleneck logging active", prefix="INIT")
    
    # If email sending is requested, enable auto-approve to process applications without interaction
    if args.send_email:
        args.auto_approve = True
    
    # Auto-approve implies sending email (need to log all results)
    if args.auto_approve:
        args.send_email = True
    
    # Headless mode implies auto-approve (no browser window to review)
    if args.headless:
        args.auto_approve = True
        print(f"{Colors.YELLOW}[Headless Mode] Automatically enabling --auto-approve (no browser window to review).{Colors.END}")
    
    # Resolve configuration paths
    config_path = args.config
    criteria_path = args.criteria
    profile_path = args.profile
    
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)
    if not os.path.isabs(criteria_path):
        criteria_path = os.path.join(os.path.dirname(__file__), criteria_path)
    if not os.path.isabs(profile_path):
        profile_path = os.path.join(os.path.dirname(__file__), profile_path)
        
    workspace_dir = os.path.dirname(__file__)
    
    if args.reset_candidate:
        reset_candidate_data(workspace_dir, config_path, criteria_path, profile_path)
        return
        
    prompts_path = os.path.join(workspace_dir, "config", "prompts.yaml")
    restore_active_configs_from_samples(workspace_dir, config_path, criteria_path, profile_path, prompts_path)
    
    # Bypassing the config GUI for CLI-only or testing operations
    is_cli_only = args.parse_cv or args.test_score or args.test_anschreiben or args.generate_dummy_cv or args.send_email or args.headless or args.url or args.interactive or args.pipeline
    # --search-jobs without --headless should still show the GUI before launching
    if not is_cli_only or (args.search_jobs is not None and not args.headless):
        run_config_gui(config_path, criteria_path, profile_path, prompts_path)
    
    global PROMPTS
    PROMPTS = load_prompts(prompts_path)
    config = load_config(config_path)
    criteria = load_criteria(criteria_path)
    init_gemini(config_path)
    
    if args.chrome_data_dir:
        config["user_profile"]["chrome_data_dir"] = args.chrome_data_dir
        
    # Create output directories if needed
    os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
    conn = init_db()
    
    # Automatically scan workspace and update file index database on startup
    index_candidate_files(workspace_dir, conn, criteria_path)
    
    # Locate candidate CV path and profile from index database
    cursor = conn.cursor()
    cursor.execute("""
        SELECT file_path, parsed_json FROM candidate_files 
        WHERE classification = 'Lebenslauf' 
        ORDER BY mtime DESC LIMIT 1
    """)
    cv_row = cursor.fetchone()
    
    if cv_row:
        cv_path = os.path.normpath(os.path.join(workspace_dir, cv_row[0]))
    else:
        # Fallback to config.yaml cv_path if not indexed
        cv_name = config["user_profile"].get("cv_path", "Lebenslauf_UserName.pdf")
        cv_path = os.path.join(workspace_dir, cv_name)

    if args.pipeline:
        run_pipeline_mode(workspace_dir, config, criteria_path, profile_path,
                          args.search_jobs, args.location, args.radius, args.force_generate,
                          args.auto_approve)
        return

    if args.parse_cv:
        parse_cv(cv_path, profile_path, criteria_path)
        # Update database index after re-parsing so db is in sync
        cursor = conn.cursor()
        try:
            # Read size and mtime
            import stat
            st = os.stat(cv_path)
            file_size = st.st_size
            mtime = st.st_mtime
            with open(profile_path, "r", encoding="utf-8") as pf:
                parsed_json = pf.read()
            rel_cv = os.path.relpath(cv_path, workspace_dir)
            cursor.execute("""
                INSERT OR REPLACE INTO candidate_files (file_path, file_size, mtime, classification, parsed_json)
                VALUES (?, ?, ?, 'Lebenslauf', ?)
            """, (rel_cv, file_size, mtime, parsed_json))
            conn.commit()
            print("Successfully updated database index with re-parsed CV profile.")
        except Exception as e:
            print(f"Warning: could not update database index after parsing: {e}")
        return
    
    if cv_row:
        profile = json.loads(cv_row[1])
        profile = normalize_profile(profile)
        # Sync candidate_profile.json with DB profile (ensure single source of truth)
        try:
            with open(profile_path, "w", encoding="utf-8") as pf:
                json.dump(profile, pf, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: could not sync candidate_profile.json: {e}{Colors.END}")
    else:
        if len(sys.argv) == 1 and not os.path.exists(profile_path):
            parse_cv(cv_path, profile_path, criteria_path)
            return
        
        if not os.path.exists(profile_path):
            print(f"Error: Candidate profile '{profile_path}' not found and no CV indexed. Please place a CV PDF in the folder or run --parse-cv first.")
            sys.exit(1)
            
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        profile = normalize_profile(profile)
        
    if args.test_score:
        with open(args.test_score, "r", encoding="utf-8") as f:
            job_desc = f.read()
        past_rejections = get_past_rejections(conn)
        yaml_rejections = criteria.get("ko_filters", {}).get("user_rejected_reasons", [])
        if yaml_rejections:
            past_rejections = list(set(past_rejections + yaml_rejections))
        score = score_job(profile, job_desc, config, criteria, past_rejections)
        print("\n--- Scoring Result ---")
        print(json.dumps(score, ensure_ascii=False, indent=2))
        
    elif args.test_anschreiben:
        company_name = args.test_anschreiben[0]
        job_desc_file = args.test_anschreiben[1]
        with open(job_desc_file, "r", encoding="utf-8") as f:
            job_desc = f.read()
        anschreiben = generate_anschreiben(profile, job_desc, config, criteria)
        print("\n--- Generated Anschreiben text ---")
        print(anschreiben)
        pdf_path = os.path.join(os.path.dirname(__file__), "output", f"Anschreiben_{company_name}.pdf")
        save_anschreiben_pdf(anschreiben, company_name, profile, pdf_path)
        
    elif args.send_email and not args.url and not args.interactive and args.search_jobs is None:
        # send-email only mode: no Playwright needed
        pass
        
    else:
        with sync_playwright() as p:
            context, browser, cdp_connected = get_browser_context(p, config, headless=args.headless)
            
            def with_new_page(page_fn, *args, **kwargs):
                """Create a fresh page, run fn, close page, return result."""
                wp = context.new_page()
                try:
                    return page_fn(wp, *args, **kwargs)
                finally:
                    try:
                        wp.close()
                    except Exception:
                        pass
            
            if args.url:
                with TeeStdout() as tee:
                    with_new_page(
                        lambda pg, **kw: process_job_url(pg, **kw),
                        url=args.url,
                        candidate_profile=profile,
                        config=config,
                        criteria=criteria,
                        conn=conn,
                        auto_approve=args.auto_approve,
                        criteria_path=criteria_path,
                        tee=tee,
                        workspace_dir=workspace_dir,
                        no_email=args.no_email,
                        force_generate=args.force_generate
                    )
            elif args.interactive:
                print(f"{Colors.MAGENTA}Interactive mode started. Type 'exit' to quit.{Colors.END}")
                while True:
                    url = input("\nEnter Job listing URL (or 'exit'): ").strip()
                    if url.lower() == 'exit':
                        break
                    if not url:
                        continue
                    try:
                        with TeeStdout() as tee:
                            with_new_page(
                                lambda pg, **kw: process_job_url(pg, **kw),
                                url=url,
                                candidate_profile=profile,
                                config=config,
                                criteria=criteria,
                                conn=conn,
                                auto_approve=args.auto_approve,
                                criteria_path=criteria_path,
                                tee=tee,
                                workspace_dir=workspace_dir,
                                no_email=args.no_email,
                                force_generate=args.force_generate
                            )
                    except Exception as e:
                        print(f"{Colors.RED}Error processing URL: {e}{Colors.END}")
            else:
                search_query = args.search_jobs if args.search_jobs is not None else ""
                # Use a dedicated search page
                search_page = context.new_page()
                try:
                    try:
                        indeed_links = search_indeed(search_page, search_query, args.location, args.radius)
                    except Exception as e:
                        print(f"{Colors.RED}Indeed search failed: {e}. Continuing with LinkedIn only...{Colors.END}")
                        indeed_links = []
                    raw_loc = args.location
                    if re.match(r'^\d{5}$', raw_loc):
                        linkedin_loc = f"{raw_loc}, Germany"
                    elif raw_loc.lower() in ("deutschland", "germany"):
                        linkedin_loc = "Germany"
                    else:
                        linkedin_loc = f"{raw_loc}, Germany"
                    try:
                        linkedin_links = search_linkedin(search_page, search_query, linkedin_loc, args.radius)
                    except Exception as e:
                        print(f"{Colors.RED}LinkedIn search failed: {e}. Continuing with Indeed only...{Colors.END}")
                        linkedin_links = []
                finally:
                    # Search page is closed only in headless/background mode
                    if args.headless:
                        try:
                            search_page.close()
                        except Exception:
                            pass
                
                # Combine all links without duplicates
                all_links = list(set(indeed_links + linkedin_links))
                MAX_LINKS = int(criteria.get("search", {}).get("max_results", 25))
                if len(all_links) > MAX_LINKS:
                    print(f"{Colors.YELLOW}Limiting to first {MAX_LINKS} links.{Colors.END}")
                    all_links = all_links[:MAX_LINKS]
                print(f"\n{Colors.MAGENTA}{Colors.BOLD}Combined search results: Found {len(all_links)} unique listings to process.{Colors.END}")
                if not args.headless:
                    print(f"{Colors.GREEN}{Colors.BOLD}>>> Browser pages will remain open — watch the agent work!{Colors.END}")
                
                # Create ONE persistent processing page (keep open if not headless)
                if args.headless:
                    # Headless mode: create + close per job (original behavior)
                    for idx, url in enumerate(all_links):
                        print(f"\n{Colors.MAGENTA}{Colors.BOLD}>>> Processing vacancy {idx+1}/{len(all_links)}...{Colors.END}")
                        try:
                            with TeeStdout() as tee:
                                with_new_page(
                                    lambda pg, **kw: process_job_url(pg, **kw),
                                    url=url,
                                    candidate_profile=profile,
                                    config=config,
                                    criteria=criteria,
                                    conn=conn,
                                    auto_approve=args.auto_approve,
                                    criteria_path=criteria_path,
                                    tee=tee,
                                    workspace_dir=workspace_dir,
                                    no_email=args.no_email,
                                    force_generate=args.force_generate
                                )
                        except Exception as e:
                            print(f"{Colors.RED}Error processing job at {url}: {e}{Colors.END}")
                else:
                    # Non-headless mode: reuse one page, keep it open
                    processing_page = context.new_page()
                    processing_page.set_default_timeout(120000)
                    browser_dead = False
                    for idx, url in enumerate(all_links):
                        if browser_dead:
                            print(f"{Colors.RED}Skipping remaining jobs — browser connection lost.{Colors.END}")
                            break
                        print(f"\n{Colors.MAGENTA}{Colors.BOLD}>>> Processing vacancy {idx+1}/{len(all_links)}...{Colors.END}")
                        try:
                            # Recreate page if it was closed by a previous error
                            try:
                                processing_page.title()
                            except Exception:
                                print(f"{Colors.YELLOW}Warning: Processing page was closed. Creating a new page...{Colors.END}")
                                try:
                                    processing_page = context.new_page()
                                    processing_page.set_default_timeout(120000)
                                except Exception:
                                    print(f"{Colors.RED}Fatal: Cannot create new page — browser connection lost.{Colors.END}")
                                    browser_dead = True
                                    break
                            with TeeStdout() as tee:
                                process_job_url(
                                    processing_page,
                                    url=url,
                                    candidate_profile=profile,
                                    config=config,
                                    criteria=criteria,
                                    conn=conn,
                                    auto_approve=args.auto_approve,
                                    criteria_path=criteria_path,
                                    tee=tee,
                                    workspace_dir=workspace_dir,
                                    no_email=args.no_email,
                                    force_generate=args.force_generate
                                )
                        except Exception as e:
                            estr = str(e)
                            print(f"{Colors.RED}Error processing job at {url}: {e}{Colors.END}")
                            # Detect browser disconnection — any further Playwright call will fail
                            if any(kw in estr.lower() for kw in ["epipe", "target page, context or browser has been closed", "connection", "browser has been closed", "protocol error", "socket"]):
                                print(f"{Colors.RED}{Colors.BOLD}Browser connection lost. Remaining jobs will be skipped.{Colors.END}")
                                browser_dead = True
                                break
            
            # Close browser context only if we launched it (not CDP)
            if not cdp_connected:
                try:
                    context.close()
                except Exception:
                    pass
                
    if args.send_email:
        from job_agent.email_sender import send_pending_emails
        send_pending_emails(config, profile, conn)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}{Colors.BOLD}>>> Execution cancelled by user (Ctrl+C). Exiting gracefully...{Colors.END}\n")
        try:
            sys.exit(0)
        except SystemExit:
            import os
            os._exit(0)
