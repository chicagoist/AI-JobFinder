"""Local LLM client via Ollama API — fully GDPR-compliant, no data leaves the machine.

Requires Ollama installed and running (http://localhost:11434).
Install: https://ollama.com/download
Pull model: ollama pull llama3.2:3b
Start: ollama serve

**Cross-platform:** Works identically on Linux, macOS, and Windows (Ollama
v0.1.40+). OLLAMA_NUM_THREAD and OLLAMA_NUM_CTX can be overridden via
config.yaml → `llm.ollama_num_thread` / `llm.ollama_num_ctx`.
"""

import os
import requests
from typing import Optional
from job_agent.utils import Colors, IS_WINDOWS, IS_LINUX

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:1b"  # ~1.3GB, fast on CPU (~25s/intake)
TIMEOUT_SECONDS = 150           # Balanced: gives local LLM a chance before cloud fallback
OLLAMA_NUM_THREAD = 2           # Conservative: safe on most CPUs
OLLAMA_NUM_CTX = 3072           # Reduced from 4096: faster prompt eval, still fits intake prompts


def call_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 2048,  # Sufficient for scoring/anschreiben; callers can override
) -> Optional[str]:
    """Send a prompt to the local Ollama instance.

    Returns the response text as a string, or None on failure.
    No data leaves the machine — all inference is local.
    """
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_thread": OLLAMA_NUM_THREAD,
                    "num_ctx": OLLAMA_NUM_CTX,
                },
            },
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code == 200:
            result: dict = resp.json()
            response_text: str = result.get("response", "") or ""
            return response_text
        else:
            print(
                f"{Colors.YELLOW}[Ollama] HTTP {resp.status_code}: {resp.text[:200]}{Colors.END}"
            )
            return None
    except requests.ConnectionError:
        print(
            f"{Colors.RED}[Ollama] Connection refused. Is Ollama running?{Colors.END}"
        )
        if IS_LINUX:
            print(
                f"{Colors.CYAN}  Start with: ollama serve  (or: systemctl start ollama){Colors.END}"
            )
        elif IS_WINDOWS:
            print(
                f"{Colors.CYAN}  Start with: ollama serve  (from PowerShell/CMD as Administrator){Colors.END}"
            )
        else:
            print(
                f"{Colors.CYAN}  Start with: ollama serve{Colors.END}"
            )
        return None
    except requests.Timeout:
        print(
            f"{Colors.YELLOW}[Ollama] Request timed out after {TIMEOUT_SECONDS}s. "
            f"The model may still be loading.{Colors.END}"
        )
        return None
    except Exception as e:
        print(f"{Colors.YELLOW}[Ollama] Error: {type(e).__name__}: {e}{Colors.END}")
        return None


def ollama_available(model: str = DEFAULT_MODEL) -> bool:
    """Check if Ollama is running and the specified model is available."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = resp.json().get("models", [])
        available_names = {m.get("name", "") for m in models}
        # Check for exact match or with :latest suffix
        if model in available_names or f"{model}:latest" in available_names:
            return True
        # Also accept partial matches (e.g. "llama3.2" matches "llama3.2:3b")
        model_short = model.split(":")[0]
        for name in available_names:
            if name.startswith(model_short):
                return True
        print(
            f"{Colors.YELLOW}[Ollama] Model '{model}' not found locally. "
            f"Run: ollama pull {model}{Colors.END}"
        )
        return False
    except requests.ConnectionError:
        return False
    except Exception:
        return False
