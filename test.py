from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

# 测试通用 LLM
client = OpenAI(
    base_url="https://www.erisai.online/v1/",
    api_key="sk-gm7UcjYTBrkGZ7ze0nrechMWatbfQVaF0hRwn6KTrX0l0gs1",
)

client2 = OpenAI(
    base_url="https://www.erisai.online/v1/",
    api_key="sk-gm7UcjYTBrkGZ7ze0nrechMWatbfQVaF0hRwn6KTrX0l0gs1",
)
resp = client.chat.completions.create(
    model='gpt-5.4',
    messages=[{'role': 'user', 'content': 'Hello, reply with just OK'}],
    max_tokens=10
)
print(f'[OK] General LLM: {resp.choices[0].message.content}')

# 测试专用 LLM

resp2 = client2.chat.completions.create(
    model='gpt-5.4',
    messages=[{'role': 'user', 'content': [{'type': 'text', 'text': 'Reply OK'}]}],
    max_tokens=10
)
print(f'[OK] Specialized LLM: {resp2.choices[0].message.content}')
