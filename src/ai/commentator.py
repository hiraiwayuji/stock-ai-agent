import json
import os
import unicodedata
from typing import TypedDict

SYSTEM_PROMPT = """あなたは「ぼーるくん」（ボール接骨院の公式キャラクター、投資初心者〜中級者）の隣にいる敏腕トレーナーです。
株価データ（JSON配列）を受け取ったら、ぼーるくんに横から短く状況を共有してください。

口調: 親しみやすく、かつ鋭い視点。ユーザー本人として話すのではなく、ぼーるくんに話しかける立場を保つ。
形式: 全文で3行、合計80〜150文字。
話しかけ方: 「ぼーるくん、今〇〇が動いてるよ！」のように隣から教える体裁で始める。
内容: 騰落率の事実 + トレーナー視点の観察（なぜ動いたか/注目ポイント/次に見るべき指標）を1つ。

禁止事項:
- 「今すぐ買い」「ここは売り」など、売買を断定・誘導する表現
- 過度な専門用語、長文解説
- 材料が不明なときに憶測で理由を断定すること（代わりに事実と次に見るべき指標を優先）

出力は解説文のみ。前置き・メタコメント・コードブロックは一切不要。"""


class Quote(TypedDict):
    ticker: str
    name: str
    price: float
    prev_close: float
    change: float
    change_pct: float
    currency: str


def validate_comment(text: str) -> tuple[bool, str]:
    """
    OK かどうかと NG 理由を返す。
    チェック項目:
    - 行数が 3 行
    - 全角文字数が 80〜150
    - 禁止語: 「今すぐ買い」「すぐ買え」「絶対売り」「今売れ」「売るべき」「買うべき」
    - 「ぼーるくん」の呼びかけが含まれる（任意: WARN のみ、NG にはしない）
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) != 3:
        return False, f"行数が3行ではありません（現在{len(lines)}行）"
    
    def get_char_width(c: str) -> int:
        return 2 if unicodedata.east_asian_width(c) in 'FWA' else 1
    
    total_width = sum(get_char_width(c) for c in text.replace('\n', ''))
    zenkaku_count = total_width / 2
    
    if not (80 <= zenkaku_count <= 150):
        return False, f"文字数が80〜150文字の範囲外です（現在約{zenkaku_count:.1f}文字）"
    
    forbidden_words = ["今すぐ買い", "すぐ買え", "絶対売り", "今売れ", "売るべき", "買うべき"]
    for word in forbidden_words:
        if word in text:
            return False, f"禁止表現「{word}」が含まれています"
            
    if "ぼーるくん" not in text:
        # WARN のみ、NG にはしない
        pass
        
    return True, ""


def comment(quotes: list[Quote], model: str | None = None) -> str:
    """
    quotes を元に3行80〜150字のトレーナー解説を返す。
    - model が None のとき os.environ.get("OPENAI_MODEL", "gpt-4o-mini") を使う
    - OpenAI API を呼び、SYSTEM_PROMPT + JSON.dumps(quotes) を送信
    - temperature=0.7
    - レスポンスを validate_comment() に通す
    - バリデーション失敗時は最大1回だけリトライ（system prompt の末尾に
      「前回の出力が形式違反でした。3行80〜150字・禁止表現なしで再生成してください」を追加）
    - 2回目も失敗したら、最後に返ってきた文字列をそのまま返す（フォールバック）
    """
    if model is None:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    try:
        from openai import OpenAI
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"OpenAI クライアントの読み込みに失敗しました: {exc}") from exc

    client = OpenAI()
    
    payload = json.dumps(quotes, ensure_ascii=False)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": payload},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore
        temperature=0.7,
    )
    result_text = response.choices[0].message.content or ""

    is_valid, _ = validate_comment(result_text)
    if is_valid:
        return result_text

    retry_system_prompt = (
        SYSTEM_PROMPT
        + "\n\n前回の出力が形式違反でした。3行80〜150字・禁止表現なしで再生成してください。"
    )
    messages_retry = [
        {"role": "system", "content": retry_system_prompt},
        {"role": "user", "content": payload},
    ]

    response_retry = client.chat.completions.create(
        model=model,
        messages=messages_retry,  # type: ignore
        temperature=0.7,
    )
    result_text_retry = response_retry.choices[0].message.content or ""

    validate_comment(result_text_retry)
    return result_text_retry
