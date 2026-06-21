"""Local LLM client via compiled llama-server (llama.cpp) — OpenAI-compatible API.

Uses a pre-compiled llama-server binary to serve a GGUF model directly,
bypassing Ollama entirely. This is useful when Ollama's bundled llama-server
binary is broken or missing.

The llama-server exposes an OpenAI-compatible API on port 8080 by default.
This module provides the same interface as ollama_llm.py so it can be used
as a drop-in replacement.

**Cross-platform:** The binary path is configurable via config.yaml at
`llm.llama_server_path`. Platform defaults:
  - Linux:   /tmp/llama.cpp/build-cpu/bin/llama-server
  - Windows: C:\\llama.cpp\\build\\bin\\Release\\llama-server.exe
  - macOS:   /tmp/llama.cpp/build-cpu/bin/llama-server
"""

import os
import requests
from typing import Optional
from job_agent.utils import Colors, IS_WINDOWS

LLAMA_SERVER_BASE_URL = "http://localhost:8080"
TIMEOUT_SECONDS = 180

# Platform-appropriate default paths for the llama-server binary
def _default_llama_server_path() -> str:
    """Return the default llama-server path for the current platform."""
    if IS_WINDOWS:
        return r"C:\llama.cpp\build\bin\Release\llama-server.exe"
    # Linux / macOS
    return "/tmp/llama.cpp/build-cpu/bin/llama-server"


# Read path from config.yaml if available, else fall back to platform default
def _get_llama_server_path() -> str:
    """Load llama-server binary path from config.yaml, or use platform default."""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml"
        )
        if os.path.exists(config_path):
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            path = config.get("llm", {}).get("llama_server_path", "") or ""
            if path:
                return path.strip()
    except Exception:
        pass
    return _default_llama_server_path()


LLAMA_SERVER_BINARY = _get_llama_server_path()


def call_llama_server(
    prompt: str,
    model: str = "",  # Not used by llama-server, kept for interface compatibility
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> Optional[str]:
    """Send a prompt to the local llama-server instance.

    Converts the raw prompt to an OpenAI-compatible chat completion request.
    Returns the response text as a string, or None on failure.
    No data leaves the machine — all inference is local.
    """
    try:
        resp = requests.post(
            f"{LLAMA_SERVER_BASE_URL}/v1/chat/completions",
            json={
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code == 200:
            result: dict = resp.json()
            choices: list = result.get("choices", [])
            if choices:
                message: dict = choices[0].get("message", {})
                response_text: str = message.get("content", "") or ""
                return response_text
            return ""
        else:
            print(
                f"{Colors.YELLOW}[llama-server] HTTP {resp.status_code}: {resp.text[:200]}{Colors.END}"
            )
            return None
    except requests.ConnectionError:
        print(
            f"{Colors.RED}[llama-server] Connection refused. "
            f"Is llama-server running on port 8080?{Colors.END}"
        )
        print(
            f"{Colors.CYAN}  Start with: {LLAMA_SERVER_BINARY} --model <gguf-path> "
            f"--port 8080 --host 127.0.0.1{Colors.END}"
        )
        return None
    except requests.Timeout:
        print(
            f"{Colors.YELLOW}[llama-server] Request timed out after {TIMEOUT_SECONDS}s. "
            f"The model may still be loading.{Colors.END}"
        )
        return None
    except Exception as e:
        print(f"{Colors.YELLOW}[llama-server] Error: {type(e).__name__}: {e}{Colors.END}")
        return None


def llama_server_available() -> bool:
    """Check if llama-server is running on port 8080 and responding to requests."""
    try:
        resp = requests.get(f"{LLAMA_SERVER_BASE_URL}/health", timeout=2)
        if resp.status_code == 200:
            return True
        # Some versions use /v1/models instead of /health
        resp2 = requests.get(f"{LLAMA_SERVER_BASE_URL}/v1/models", timeout=2)
        return bool(resp2.status_code == 200)
    except requests.ConnectionError:
        return False
    except Exception:
        return False


def start_llama_server_command(gguf_path: str, port: int = 8080, host: str = "127.0.0.1") -> str:
    """Return the shell command to start llama-server with the given GGUF model."""
    return (
        f"{LLAMA_SERVER_BINARY} "
        f"--model {gguf_path} "
        f"--port {port} "
        f"--host {host} "
        f"--ctx-size 4096 "
        f"--n-gpu-layers 0 "
        f"--batch-size 512"
    )
