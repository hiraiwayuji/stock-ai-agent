import os
import logging
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    ImageMessage,
)
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def _clean_env(name: str) -> str:
    value = os.environ.get(name, "")
    cleaned = value.strip()
    if value != cleaned:
        log.warning("%s had surrounding whitespace; using stripped value", name)
    return cleaned


def _fingerprint(value: str) -> str:
    if not value:
        return "missing"
    return f"len={len(value)} first5={value[:5]} last5={value[-5:]} has_equal={'=' in value}"


_line_access_token = _clean_env("LINE_CHANNEL_ACCESS_TOKEN")
log.info("LINE_CHANNEL_ACCESS_TOKEN fingerprint: %s", _fingerprint(_line_access_token))
_config = Configuration(access_token=_line_access_token)


def _get_api() -> MessagingApi:
    return MessagingApi(ApiClient(_config))


def push_text(user_id: str, text: str) -> None:
    """テキストをLINEプッシュ送信"""
    api = _get_api()
    api.push_message(PushMessageRequest(
        to=user_id,
        messages=[TextMessage(type="text", text=text)],
    ))


def push_flex(user_id: str, alt_text: str, flex_contents: dict) -> None:
    """Flexメッセージを送信（リッチUI用）"""
    api = _get_api()
    api.push_message(PushMessageRequest(
        to=user_id,
        messages=[FlexMessage(type="flex", altText=alt_text, contents=flex_contents)],
    ))


def push_image(user_id: str, image_url: str, preview_url: str | None = None) -> None:
    """画像をLINEプッシュ送信（Supabase Storage の公開URL を渡す）"""
    api = _get_api()
    api.push_message(PushMessageRequest(
        to=user_id,
        messages=[ImageMessage(
            type="image",
            original_content_url=image_url,
            preview_image_url=preview_url or image_url,
        )],
    ))
