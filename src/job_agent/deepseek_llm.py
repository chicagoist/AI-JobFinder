import os
import json
import time
import urllib.request
import urllib.error

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = None

class DeepSeekResponse:
    def __init__(self, text):
        self.text = text

def _get_api_key():
    for var in ["DEEPSEEK_API_KEY", "DEEPSEEK_KEY", "DS_API_KEY"]:
        key = os.environ.get(var)
        if key:
            return key.strip()
    return None

def _get_model():
    global DEEPSEEK_MODEL
    if DEEPSEEK_MODEL:
        return DEEPSEEK_MODEL
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    DEEPSEEK_MODEL = model
    return model

def call_deepseek(prompt, max_retries=3, initial_delay=3.0, **kwargs):
    api_key = _get_api_key()
    if not api_key:
        print("[DeepSeek] No API key found in environment variables (DEEPSEEK_API_KEY).")
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
    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"

    delay = initial_delay
    for attempt in range(max_retries):
        try:
            time.sleep(2.0)
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                return DeepSeekResponse(content)

        except urllib.error.HTTPError as e:
            status = e.code
            error_body = e.read().decode("utf-8", errors="replace")[:300]
            if status == 429:
                print(f"[DeepSeek] Rate limited (429). Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            elif status == 401:
                print(f"[DeepSeek] Authentication failed (401): {error_body}")
                return None
            elif status == 402:
                print(f"[DeepSeek] Insufficient balance (402): {error_body}")
                return None
            else:
                print(f"[DeepSeek] HTTP {status}: {error_body}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(delay)
                delay *= 2

        except urllib.error.URLError as e:
            print(f"[DeepSeek] Connection error: {e.reason}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2

        except json.JSONDecodeError as e:
            print(f"[DeepSeek] Invalid JSON response: {e}")
            return None

        except Exception as e:
            print(f"[DeepSeek] Request failed: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2

    return None
