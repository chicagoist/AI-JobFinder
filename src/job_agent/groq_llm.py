import os
import json
import time
import urllib.request
import urllib.error

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = None

class GroqResponse:
    def __init__(self, text):
        self.text = text

def _get_api_key():
    for var in ["GROQ_API_KEY", "GROQ_KEY"]:
        key = os.environ.get(var)
        if key:
            return key.strip()
    return None

def _get_model():
    global GROQ_MODEL
    if GROQ_MODEL:
        return GROQ_MODEL
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_MODEL = model
    return model

def call_groq(prompt, max_retries=3, initial_delay=2.0, **kwargs):
    api_key = _get_api_key()
    if not api_key:
        print("[Groq] No API key found in environment variables (GROQ_API_KEY).")
        return None

    model = _get_model()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 8192
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{GROQ_BASE_URL}/chat/completions"

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(1.5)
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                return GroqResponse(content)

        except urllib.error.HTTPError as e:
            status = e.code
            error_body = e.read().decode("utf-8", errors="replace")[:300]
            if status == 429:
                print(f"[Groq] Rate limited (429). Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            elif status == 401:
                print(f"[Groq] Authentication failed (401): {error_body}")
                return None
            elif status == 402:
                print(f"[Groq] Insufficient balance (402): {error_body}")
                return None
            else:
                print(f"[Groq] HTTP {status}: {error_body}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(delay)
                delay *= 2

        except urllib.error.URLError as e:
            print(f"[Groq] Connection error: {e.reason}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2

        except json.JSONDecodeError as e:
            print(f"[Groq] Invalid JSON response: {e}")
            return None

        except Exception as e:
            print(f"[Groq] Request failed: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2

    return None
