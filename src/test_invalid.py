from google import genai
from google.genai import types
from google.genai import errors as genai_errors
import sys

client = genai.Client(api_key="INVALID_KEY_123", http_options=types.HttpOptions(timeout=10.0))
try:
    response = client.models.generate_content(model="gemini-2.5-flash", contents="hello")
    print(response.text)
except genai_errors.ClientError as e:
    print(f"ClientError: code={e.code}, message={e.message}")
except Exception as e:
    print(f"Exception: {type(e).__name__} - {e}")
