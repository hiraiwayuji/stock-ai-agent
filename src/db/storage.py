"""
Supabase Storage へのチャート画像アップロード
charts バケット (public) に PNG を保存し、公開 URL を返す
"""
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from src.db.supabase_client import get_client

JST    = timezone(timedelta(hours=9))
BUCKET = "charts"


def upload_chart(filename: str, image_bytes: bytes) -> str:
    """
    PNG bytes を Supabase Storage にアップし、公開 URL を返す。
    同名ファイルは上書き (upsert=True)。
    """
    client  = get_client()
    path    = f"{datetime.now(JST).strftime('%Y%m')}/{filename}"

    client.storage.from_(BUCKET).upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )

    url_res = client.storage.from_(BUCKET).get_public_url(path)
    return url_res   # str


def chart_filename(user_id: str, chart_type: str) -> str:
    ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    uid_short = user_id[-8:]
    return f"{chart_type}_{uid_short}_{ts}.png"
