import re
with open('job_agent/llm.py', 'r') as f:
    content = f.read()

content = content.replace("time.sleep(delay)", "print(f'SLEEPING FOR {delay} SECONDS...'); sys.stdout.flush(); time.sleep(delay)")

with open('job_agent/llm.py', 'w') as f:
    f.write(content)