from google import genai

print("Init client...")
client = genai.Client(api_key="AIzaSyAFpev6jaKgjW5PC2Nepc1575eqFi8oDrM")
print("Generating content...")
try:
    response = client.models.generate_content(model="gemini-2.5-flash", contents="hello")
    print("Done:", response.text)
except Exception as e:
    print("Error:", e)