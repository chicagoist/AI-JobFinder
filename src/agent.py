import os
import sys
import argparse
import json
import yaml
import datetime
import sqlite3

# Import common utilities and configuration loaders from the package
import job_agent.utils
from job_agent.utils import Colors, clean_and_repair_json, TeeStdout
from job_agent.config import load_config, load_criteria, load_prompts, restore_active_configs_from_samples, DEFAULT_PROMPTS, PROMPTS
from job_agent.db import init_db, log_application, get_past_rejections
from job_agent import llm as llm_module
from job_agent.llm import init_gemini, llm_request_with_fallback
from job_agent.ollama_llm import ollama_available
from job_agent.pipeline import run_pipeline_mode
# sync_playwright imported locally where needed (PDF rendering)


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
    priority_llm_combo = ttk.Combobox(tab1, values=["local", "gemini", "openrouter"], state="readonly", width=30)
    priority_llm_combo.set(config_data.get("llm", {}).get("priority", "local"))
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

# generate_content_with_retry has been migrated to job_agent/llm.py

# Database functions (init_db, log_user_rejection, get_past_rejections, is_already_applied, log_application) have been migrated to job_agent/db.py

# Generate a dummy CV PDF for testing purposes
def generate_dummy_cv(output_path):
    from playwright.sync_api import sync_playwright
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
# Score job description against the candidate profile
# Generate cover letter text
# Accepts either a dict (from generate_anschreiben) or a plain string (backward compat)
def save_anschreiben_pdf(anschreiben_text, company_name, candidate_profile, output_path, browser_context=None):
    from playwright.sync_api import sync_playwright
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
            # sync_playwright imported locally where needed (PDF rendering)
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


def main():
    parser = argparse.ArgumentParser(description="JobAgent CLI")
    parser.add_argument("--pipeline", action="store_true", help="Run the automated application pipeline")
    parser.add_argument("--parse-cv", action="store_true", help="Parse CV into structured JSON profile")
    parser.add_argument("--test-score", type=str, help="Score a given job description file")
    parser.add_argument("--test-anschreiben", nargs=2, help="Generate a cover letter for a given job and test it")
    parser.add_argument("--search-jobs", type=str, nargs="?", default=None, help="Search jobs (query)")
    parser.add_argument("--location", type=str, default="Frankfurt am Main", help="Location for job search")
    parser.add_argument("--radius", type=int, default=25, help="Radius for job search in km")
    parser.add_argument("--force-generate", action="store_true", help="Force generate documents unconditionally")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve suitable applications")
    parser.add_argument("--reset-candidate", action="store_true", help="Reset candidate database and workspace files")
    parser.add_argument("--generate-dummy-cv", action="store_true", help="Generate a basic dummy CV PDF")
    parser.add_argument("--config", type=str, default="config/config.yaml", help="Path to config file")
    parser.add_argument("--profile", type=str, default="config/candidate_profile.json", help="Path to candidate profile")
    parser.add_argument("--criteria", type=str, default="config/job_criteria.yaml", help="Path to job criteria config")
    parser.add_argument("--debug", action="store_true", help="Enable debugging mode")
    parser.add_argument("--ignore-ollama", action="store_true", help="Proceed even if Ollama is not running (demo/testing only)")

    args = parser.parse_args()

    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(workspace_dir, args.config) if not os.path.isabs(args.config) else args.config
    criteria_path = os.path.join(workspace_dir, args.criteria) if not os.path.isabs(args.criteria) else args.criteria
    profile_path = os.path.join(workspace_dir, args.profile) if not os.path.isabs(args.profile) else args.profile
    prompts_path = os.path.join(os.path.dirname(config_path), "prompts.yaml")

    if args.reset_candidate:
        reset_candidate_data(workspace_dir, config_path, criteria_path, profile_path)
        return

    # Ensure active configs exist (restore from .sample templates if missing)
    restore_active_configs_from_samples(workspace_dir, config_path, criteria_path, profile_path, prompts_path)
    # PROMPTS is already loaded at module level — do NOT shadow with local var

    # Launch GUI if no CLI mode specified (before loading configs)
    if not any([args.pipeline, args.parse_cv, args.reset_candidate,
                args.generate_dummy_cv, args.test_score, args.test_anschreiben]):
        run_config_gui(config_path, criteria_path, profile_path, prompts_path)
        return

    config = load_config(config_path)
    criteria = load_criteria(criteria_path)

    if args.generate_dummy_cv:
        generate_dummy_cv(os.path.join(workspace_dir, config.get("user_profile", {}).get("cv_path", "Lebenslauf_UserName.pdf")))
        return

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
                          args.auto_approve, args.ignore_ollama)
        return

    # --- Guard: Local LLM required but Ollama is not running ---
    # Covers --parse-cv, --test-score, --test-anschreiben (all call LLM)
    if args.parse_cv or args.test_score or args.test_anschreiben:
        init_gemini()  # Load globals from config
        if llm_module.PRIORITY_LLM == "local" and not llm_module.ALLOW_CLOUD_FALLBACK:
            if not ollama_available(llm_module.LOCAL_MODEL):
                if args.ignore_ollama:
                    print(f"\n{Colors.YELLOW}{Colors.BOLD}⚠ [1mLocal LLM required but Ollama is not running.{Colors.END}")
                    print(f"{Colors.YELLOW}  Proceeding due to --ignore-ollama flag. Jobs will score 0/10.{Colors.END}")
                    print(f"{Colors.YELLOW}  Start Ollama for real results: ollama serve{Colors.END}\n")
                else:
                    print(f"\n{Colors.RED}{Colors.BOLD}{'='*60}{Colors.END}")
                    print(f"{Colors.RED}{Colors.BOLD}  ❌ Local LLM required. Start Ollama:{Colors.END}")
                    print(f"{Colors.CYAN}     ollama serve{Colors.END}")
                    print(f"{Colors.GREY}     Or if already installed: ollama run {llm_module.LOCAL_MODEL}{Colors.END}")
                    print(f"{Colors.GREY}     Model needed: {llm_module.LOCAL_MODEL}{Colors.END}")
                    print(f"{Colors.RED}{Colors.BOLD}{'='*60}{Colors.END}\n")
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
        
    else:
        # No CLI arguments — launch config GUI
        run_config_gui(config_path, criteria_path, profile_path, prompts_path)

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
