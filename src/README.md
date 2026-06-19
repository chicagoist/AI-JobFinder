<!-- PROJECT LOGO / TITLE -->
<div align="center">
  <h1>🤖 AI-JobFinder</h1>
  <p><strong>Automatisierte Bewerbungen auf dem deutschen Arbeitsmarkt — KI-gestützt, lokal, datenschutzkonform.</strong></p>
  <br>
</div>

---

## ⚖️ Rechtliche Hinweise

Dieses Projekt ist auf **vollständig lokale Verarbeitung** ausgelegt:
- **Keine automatischen E-Mails** — nur `.eml`-Entwürfe zum manuellen Versand
- **Kein Cloud-LLM** — Default ist lokales Ollama (Qwen/Llama)
- **Kein Session-Scraping** — offizielle Job-APIs statt Browser-Automation

➡️ Siehe `LEGAL_COMPLIANCE_PLAN.md` (en) für den vollständigen Compliance-Plan.

---

## 🔑 API-Schlüssel — Übersicht

| Dienst | Verwendung | GDPR-Sicher? |
|--------|------------|-------------|
| **Ollama** (Default-LLM) | Lokales Scoring, Anschreiben, CV-Parsing | ✅ Ja — keine Daten verlassen den Rechner |
| **Gemini** (Fallback) | Optionaler Cloud-Fallback | ❌ PII wird in die USA gesendet |
| **OpenRouter** (Fallback) | Optionaler kostenloser Fallback | ❌ PII wird in die USA gesendet |

> **Default: `llm.priority: local`** — Cloud-LLMs sind standardmässig deaktiviert.

---

## 📢 Einladung an die Community

**Dieses Projekt lebt von der Gemeinschaft!**  
Egal, ob du ein erfahrener Python-Entwickler oder KI-Enthusiast bist — **du bist herzlich eingeladen, dieses Repository zu forken, zu verbessern oder zu erweitern**.

Roadmap:
- ➕ **Weitere Job-APIs** (StepStone, XING)
- ➕ **Weitere lokale LLMs** (via Ollama Model Library)
- ➕ **Docker-Containerisierung**
- ➕ **Web-UI / Dashboard**

---

## 📋 Inhaltsverzeichnis

- [Rechtliche Compliance](#%EF%B8%8F-rechtliche-compliance)
- [Über das Projekt](#-über-das-projekt)
- [Für wen ist dieses Tool?](#-für-wen-ist-dieses-tool)
- [Wie funktioniert es?](#-wie-funktioniert-es)
- [Architektur-Übersicht](#-architektur-übersicht)
- [Modulübersicht (UML-Tabelle)](#-modulübersicht-uml-tabelle)
- [Abhängigkeiten](#-abhängigkeiten)
- [Konfigurationsdateien](#-konfigurationsdateien)
- [CLI-Argumente](#-cli-argumente)
- [Argument-Kompatibilitätsmatrix](#-argument-kompatibilitätsmatrix)
- [Erste Schritte](#-erste-schritte)
- [Anwendungsbeispiele](#-anwendungsbeispiele)
- [Fehlerbehebung & Bekannte Probleme](#-fehlerbehebung--bekannte-probleme)
- [Lizenz](#-lizenz)

---

## ⚖️ Rechtliche Compliance

| Risiko | Massnahme |
|--------|-----------|
| **GDPR Art. 22** — Automatisierte Profiling-Entscheidungen | Scoring ist eine **Empfehlung**. Der Nutzer entscheidet final. Alle Ausgaben sind Entwürfe. |
| **GDPR Art. 5-6** — Verarbeitung von Recruiter-Daten ohne Einwilligung | **Keine automatischen E-Mails.** Nur `.eml`-Entwürfe zum manuellen Versand. |
| **Schrems II** — PII-Transfer in die USA | **Default-LLM ist lokal** (Ollama). Cloud-LLMs sind optionale Opt-In-Fallbacks. |
| **ToS-Verletzung** — Web-Scraping von Jobportalen | **Offizielle Job-APIs** (Bundesagentur, Arbeitnow) statt Scraping. |
| **UrhG Datenbankrechte** — Massen-Extraktion | API-basierter Zugriff respektiert Urheberrecht. |

### 2. `config/job_criteria.yaml` — Bewertungskriterien

```yaml
scoring:
  min_score_to_apply: 5.0                     # Mindest-Score für Bewerbung (0–10)

ko_filters:
  salary:
    min_annual_eur: 36000                     # Mindestgehalt (K.O. bei Unterschreitung)
  languages:
    min_required_english: "A2"                # K.O. bei "fließend" oder "C1"
    min_required_german: "B1"                 # K.O. bei C1/C2 oder "verhandlungssicher"
  clearances:
    forbidden_keywords:                       # K.O. bei Sicherheitsfreigaben
      - "U.S. citizenship"
      - "security clearance"
  certifications:
    mandatory_if_specified:                   # K.O. wenn Zertifikat gefordert & fehlt
      - "RHCSA"
      - "CCNA"
  education:
    require_it_degree_strictly: true          # K.O. bei striktem IT-Studium
    block_degree_only_roles: true             # Kein "oder vergleichbare Erfahrung"
  datacenter_physical_work:
    forbidden: true
  spam_providers:
    blocked_keywords:                         # Bildungsanbieter (keine echten Stellen)
      - "GFN"
      - "WBS"
    allow_internship: true                    # Praktika bei Anbietern erlaubt
  companies_blacklist: []
  forbidden_titles:                           # Titel, die ignoriert werden
    - "Full Stack Developer"
    - "Senior"
    - "Consultant"
    - "Support"
  user_rejected_reasons: []                   # Vom User abgelehnte Kriterien

cover_letter:
  career_start_year: 2010                     # Start der IT-Karriere
  mandatory_skills:                           # Fähigkeiten, die im Anschreiben vorkommen MÜSSEN
    - "Java"
    - "Perl"
    - "Kommandozeile (Console)"
```

### 3. `config/candidate_profile.json` — Kandidatenprofil

Wird automatisch via `--parse-cv` aus dem CV-PDF generiert. Enthält:

```json
{
  "personal_info": {
    "first_name": "Max",
    "last_name": "Mustermann",
    "email": "max@example.com",
    "phone": "+49 176 12345678",
    "address": "Hauptstr. 1",
    "city": "60311 Frankfurt am Main",
    "country": "Deutschland"
  },
  "languages": { "Deutsch": "B2", "Englisch": "A2" },
  "skills": ["Linux", "Python", "Java", "Docker", ...],
  "experience_years": 10.0,
  "certifications": ["Cisco CCST", "AZ-900"],
  "education": [...]
}
```

### 4. `config/prompts.yaml` — KI-Prompt-Vorlagen

Enthält die deutschsprachigen Prompts für:
- `scoring_prompt` — Bewertung einer Stellenanzeige (0–10 Score)
- `cover_letter_prompt` — Anschreiben-Generierung (DIN 5008)
- `form_filler_prompt` — Intelligentes Ausfüllen von Webformularen
- `classification_prompt` — Dokumentenklassifikation (CV, Zertifikat, etc.)
- `extract_recruiter_prompt` — Extraktion von HR-Kontaktnamen

---

## 🚀 CLI-Argumente

### Übersicht aller Flags

| Argument | Typ | Standard | Beschreibung |
|---|---|---|---|
| `--generate-dummy-cv` | Flag | – | Generiert ein Dummy-CV-PDF zum Testen |
| `--parse-cv` | Flag | – | Parst das CV-PDF und erzeugt `candidate_profile.json` |
| `--test-score PATH` | String | – | Testet das Scoring anhand einer lokalen JD-Textdatei |
| `--test-anschreiben COMPANY FILE` | 2 Strings | – | Testet die Anschreiben-Generierung |
| `--url URL` | String | – | Einzelne Stellen-URL verarbeiten |
| `--interactive` | Flag | – | Interaktiver Modus (URL-Eingabe) |
| `--search-jobs [KEYWORDS]` | String | `None` | Stellensuche auf Indeed & LinkedIn |
| `--location TEXT` | String | `"Deutschland"` | Ort für die Stellensuche |
| `--radius KM` | Integer | `25` | Suchradius um den Ort (km) |
| `--chrome-data-dir PATH` | String | aus Config | Chrome-Profil-Pfad überschreiben |
| `--headless` | Flag | – | Headless-Modus (unsichtbarer Browser). **Aktiviert automatisch `--auto-approve`** — da kein sichtbares Fenster zur manuellen Überprüfung vorhanden ist. |
| `--auto-approve` | Flag | – | Automatisches Absenden ohne Rückfrage |
| `--config PATH` | String | `config/config.yaml` | Pfad zur Konfigurationsdatei |
| `--profile PATH` | String | `config/candidate_profile.json` | Pfad zum Kandidatenprofil |
| `--criteria PATH` | String | `config/job_criteria.yaml` | Pfad zur Kriteriendatei |
| `--reset-candidate` | Flag | – | Setzt Kandidatendaten zurück (Löscht DB, PDFs) |
| `--send-email` | Flag | – | Sendet ausstehende Bewerbungen als E-Mail-ZIP |

### Detaillierte Beschreibung

#### `--generate-dummy-cv`
Generiert ein Dummy-CV-PDF mit Playwright für erste Tests, falls kein echtes CV vorhanden ist.

#### `--parse-cv`
Analysiert das im `config.yaml` unter `user_profile.cv_path` angegebene CV-PDF mittels Gemini und schreibt das strukturierte Profil in `config/candidate_profile.json`.

#### `--test-score <pfad_zur_jd.txt>`
Lädt eine lokale Textdatei mit einer Stellenbeschreibung, führt das KI-Scoring aus und gibt das Ergebnis (0–10) aus — ohne Browser zu starten.

#### `--test-anschreiben <Firma> <pfad_zur_jd.txt>`
Generiert ein Anschreiben für die angegebene Firma basierend auf einer lokalen JD-Textdatei und erzeugt ein PDF.

#### `--url "<url>"`
Öffnet die angegebene Stellen-URL im Browser, führt Scoring, Anschreiben-Generierung und Formularausfüllung aus.

#### `--interactive`
Startet den interaktiven Modus: Fragt wiederholt nach URLs, bis der Benutzer `exit` eingibt.

#### `--search-jobs [Keywords]` + `--location` + `--radius`
Führt eine automatische Stellensuche auf Indeed und LinkedIn durch. Die Keywords können direkt angegeben werden:
```bash
python agent.py --search-jobs "Linux Administrator" --location "Frankfurt am Main" --radius 25
```

#### `--headless`
Startet Chrome ohne sichtbares Fenster. Im Headless-Modus wird automatisch auch `--auto-approve` aktiviert, da es kein Browserfenster zum manuellen Überprüfen gibt.

#### `--auto-approve`
Bestätigt Bewerbungen automatisch, ohne auf eine manuelle Eingabe zu warten. Wenn das Formular nicht ausgefüllt werden kann, wird das Anschreiben per E-Mail an die Kandidaten-E-Mail gesendet (Fallback).

#### `--reset-candidate`
Erstellt einen Git-Backup-Commit (`RESTORE`), löscht dann:
- Alle generierten PDFs, HTMLs und PNGs
- Die SQLite-Datenbank (`applications.db`)
- Alle aktiven Konfigurationsdateien
Stellt dann `.sample`-Dateien als saubere Vorlagen wieder her.

#### `--send-email`
Durchsucht die Datenbank nach Bewerbungen mit `email_sent = 0`, packt sie in ZIP-Dateien (Job-Info, Terminal-Log, PDF) und sendet sie per SMTP an die Kandidaten-E-Mail.

---

## ✅ Argument-Kompatibilitätsmatrix

| Flag | `--generate-dummy-cv` | `--parse-cv` | `--test-score` | `--test-anschreiben` | `--url` | `--interactive` | `--search-jobs` | `--reset-candidate` | `--send-email` |
|---|---|---|---|---|---|---|---|---|---|
| **`--generate-dummy-cv`** | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--parse-cv`** | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--test-score`** | ❌ | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--test-anschreiben`** | ❌ | ❌ | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--url`** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **`--interactive`** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **`--search-jobs`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ + `--location`, `--radius` | ❌ | ❌ |
| **`--reset-candidate`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Alleinstehend | ❌ |
| **`--send-email`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Alleinstehend |
| **`--headless`** | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ✅ Empfohlen | ❌ | ❌ |
| **`--auto-approve`** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ Empfohlen | ❌ | ❌ |
| **`--config`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--profile`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--criteria`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--chrome-data-dir`** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |

**Legende:**
- ✅ = Kombination möglich oder empfohlen
- ❌ = Sinnlose oder blockierende Kombination
- ⚠️ = Möglich, aber nicht empfohlen (ohne `--auto-approve` wird auf Benutzereingabe gewartet)

**Wichtige Kombinationsregeln:**
1. **`--headless` aktiviert automatisch `--auto-approve`** — da kein Browserfenster sichtbar ist.
2. **`--send-email` aktiviert automatisch `--auto-approve`** — um alle ausstehenden Bewerbungen zu verarbeiten.
3. **`--url` kann mit `--config`/`--profile`/`--criteria`** kombiniert werden, um andere Konfigurationen zu laden.
4. **`--search-jobs` kann mit `--location` und `--radius`** kombiniert werden.
5. **Test-Flags (`--test-score`, `--test-anschreiben`) laufen alleinstehend** — sie starten keinen Browser.
6. **`--reset-candidate` ist ein Reinigungsbefehl** — alle anderen Flags werden ignoriert.

---

## 🚦 Erste Schritte

### 1. Installation

```bash
# Repository klonen (oder fork-en)
git clone <your-repo-url>
cd <project-directory>

# Abhängigkeiten installieren
pip install playwright pyyaml google-genai PyMuPDF openai
playwright install chromium

# Optional: Tkinter für Konfigurations-GUI
# Ubuntu/Debian: sudo apt install python3-tk
```

### 2. Konfiguration

```bash
# Konfigurations-GUI starten (Tkinter) — oder Dateien manuell bearbeiten
python agent.py

# Oder: Schnellstart mit Reset (erstellt .sample → aktive Configs)
python agent.py --reset-candidate

# Dann: Config-Dateien in config/ anpassen:
# - config.yaml: API-Keys, SMTP, Chrome-Pfad
# - job_criteria.yaml: K.O.-Filter, Score
# - candidate_profile.json: Persönliche Daten
```

### 3. Kandidatenprofil erstellen

```bash
# Option A: CV parsen (PDF muss in documents/ liegen)
python agent.py --parse-cv

# Option B: Dummy-CV generieren
python agent.py --generate-dummy-cv

# Option C: Manuell bearbeiten
# → config/candidate_profile.json editieren
```

### 4. Erste Bewerbung testen

```bash
# Einzelne URL verarbeiten (manuelle Freigabe)
python agent.py --url "https://de.indeed.com/viewjob?jk=12345"

# Oder: Vollautomatisch
python agent.py --url "https://de.indeed.com/viewjob?jk=12345" --headless --auto-approve
```

---

## 💡 Anwendungsbeispiele

### 🔍 Stellen suchen & automatisch bewerben

```bash
python agent.py --search-jobs "Remote Hybrid" \
                --location "Frankfurt am Main" \
                --radius 25 \
                --headless \
                --auto-approve
```

### 📨 Ausstehende Bewerbungen per E-Mail versenden

```bash
python agent.py --send-email
```

(Voraussetzung: SMTP-Zugangsdaten in `config.yaml`)

### 🔄 Arbeitsbereich zurücksetzen

```bash
python agent.py --reset-candidate
```

(Erstellt zuerst einen Git-Commit `RESTORE`, löscht dann alle generierten Daten)

### 🧪 Scoring testen (ohne Browser)

```bash
python agent.py --test-score pfad/zur/stellenbeschreibung.txt
```

### ✉️ Anschreiben testen (ohne Browser)

```bash
python agent.py --test-anschreiben "Musterfirma GmbH" pfad/zur/stellenbeschreibung.txt
```

### 🖥️ GUI starten (Konfiguration bearbeiten)

```bash
python agent.py
```

(Ohne Argumente geöffnet: Tkinter-GUI zum Bearbeiten von Config, Profil, Prompts und K.O.-Filtern)

---

## ⚠️ Fehlerbehebung & Bekannte Probleme

### 🔒 Chrome-Profil gesperrt

**Problem:** `FAILED TO LAUNCH PERSISTENT CONTEXT` / "lock" error  
**Lösung:**
- Schließe alle Chrome-Fenster vollständig
- Oder verwende `--headless` (dann wird automatisch ein temporäres Profil verwendet)
- Oder starte Chrome mit Remote-Debugging: `google-chrome --remote-debugging-port=9222`

### 🔑 Gemini-API-Key erschöpft

**Problem:** Alle API-Keys haben ihr tägliches Limit erreicht  
**Lösung:**
- Füge weitere Keys in `config.yaml` unter `gemini.api_keys` hinzu
- Das Tool rotiert automatisch durch alle Keys
- Fallback: OpenRouter (kostenlose Modelle) wird automatisch probiert
- Oder setze `llm.priority: openrouter` in `config.yaml`

### 🌐 Windows-Pfade auf Linux

**Problem:** `config.yaml` enthält `C:\Users\...`-Pfade  
**Lösung:**
- Aktualisiere `chrome_data_dir` auf Linux-Pfad (`~/.config/google-chrome`)
- Oder verwende `--headless` (ignoriert den Chrome-Pfad)

### 🐍 Tkinter nicht installiert

**Problem:** `tkinter`-Import-Fehler  
**Lösung:**
- Ubuntu/Debian: `sudo apt install python3-tk`
- Oder verwende CLI-Flags statt der GUI (`--url`, `--search-jobs`, etc.)

### 📄 Kein Abhängigkeits-Manifest

**Problem:** Keine `requirements.txt` / `pyproject.toml` vorhanden  
**Lösung:** Alle Pakete manuell installieren (siehe [Abhängigkeiten](#-abhängigkeiten)). Bei neuen Importen bitte in der `knowledge.md` dokumentieren.

---

## 🗺️ Roadmap

- [ ] **StepStone / Monster / XING** — Neue Job-Plattform-Module
- [ ] **Claude / Ollama** — Zusätzliche LLM-Provider
- [ ] **Docker-Image** — Containerisierte Ausführung
- [ ] **CI/CD-Pipeline** — Headless-Betrieb in GitHub Actions
- [ ] **Web-Dashboard** — Bewerbungsstatus im Browser einsehen
- [ ] **Unittests** — Formelle Testabdeckung (pytest)
- [ ] **i18n** — Unterstützung für weitere Länder/Sprachen

---

## 📄 Lizenz

Dieses Projekt ist Open Source. Siehe die `LICENSE`-Datei für Details.

---

<div align="center">
  <p>
    <strong>Gemini JobAgent</strong> — gemacht mit ❤️ für den deutschen Arbeitsmarkt.<br>
    <sub>Verbessere das Projekt — erstelle einen Fork und einen Pull Request!</sub>
  </p>
</div>
