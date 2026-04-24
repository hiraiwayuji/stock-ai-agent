"""
Minimal LINE Webhook for Phase B (group registration).

起動方法:
    uvicorn scripts.minimal_webhook:app --port 8000
"""

import logging
import os

from dotenv import load_dotenv

# .env は最初にロード
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src.db.groups import create_group, get_group_by_line_id

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Minimal LINE Webhook (Phase B: group registration)")
_config = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""))
_parser = WebhookParser(os.environ.get("LINE_CHANNEL_SECRET", ""))


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(type="text", text=text[:5000])],
            )
        )


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        events = _parser.parse(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            continue

        user_id = getattr(event.source, "user_id", "")
        text = event.message.text.strip()
        src_type = getattr(event.source, "type", "user")
        line_group_id = getattr(event.source, "group_id", None)

        log.info(f"[LINE] src={src_type} group_id={line_group_id!r} user={user_id!r} text={text!r}")

        # ケース1: グループで /register
        if src_type == "group" and line_group_id and text.startswith("/register"):
            parts = text.split(maxsplit=1)
            name = parts[1].strip() if len(parts) > 1 else "LINEグループ"

            existing = get_group_by_line_id(line_group_id)
            if existing:
                _reply(
                    event.reply_token,
                    f"✅ このグループは既に「{existing.name}」として登録済みです\n"
                    f"招待コード: {existing.invite_code}",
                )
            else:
                try:
                    g = create_group(name=name, owner_id=user_id, line_group_id=line_group_id)
                    _reply(
                        event.reply_token,
                        f"✅ このLINEグループを「{g.name}」として登録しました\n"
                        f"招待コード: {g.invite_code}\n"
                        f"Supabase に line_group_id を保存しました",
                    )
                except Exception as e:
                    log.error(f"create_group failed: {e}")
                    _reply(event.reply_token, f"⚠️ 登録エラー: {e}")

        # ケース2: 個人チャットで /myid
        elif src_type == "user" and text == "/myid":
            _reply(event.reply_token, f"あなたのuser_id:\n{user_id}")

        # ケース3: それ以外は無応答（ノイズ削減）

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "minimal-webhook"}
