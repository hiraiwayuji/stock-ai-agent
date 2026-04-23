import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = """あなたは世界最高水準の株式投資アナリストです。
テクニカル指標・ニュースセンチメント・マクロ環境を統合的に分析し、
具体的かつ実行可能な投資戦略を簡潔に提供してください。
回答はLINEで読みやすいよう300字以内にまとめてください。"""


def analyze(context: str, user_question: str = "") -> str:
    """コンテキスト（指標+ニュース）＋ユーザー質問 → AI分析テキスト"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【市場コンテキスト】\n{context}\n\n【質問】\n{user_question or '総合的な見解を教えてください'}"},
    ]
    res = _client.chat.completions.create(model=MODEL, messages=messages, max_tokens=600)
    return res.choices[0].message.content.strip()
