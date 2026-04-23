import os
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

_config = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""))


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
