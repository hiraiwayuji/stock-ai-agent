import argparse
import os
import sys

# プロジェクトルートを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

from linebot.v3.messaging.exceptions import ApiException
from src.line.client import push_text


def main() -> int:
    parser = argparse.ArgumentParser(description="LINE Push 疎通テストスクリプト")
    parser.add_argument(
        "message",
        nargs="?",
        default="疎通テスト from 株ボールシステム",
        help="送信するテキストメッセージ",
    )
    parser.add_argument(
        "--to",
        dest="to_id",
        type=str,
        help="送信先を .env の LINE_USER_ID から上書き（グループIDもOK）",
    )
    parser.add_argument(
        "--who",
        action="store_true",
        help="LINE_USER_ID に短い hello を送るショートカット（message/--to を無視）",
    )
    args = parser.parse_args()

    # 1. load_dotenv()
    load_dotenv()

    # 2. access_token 確認
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not access_token:
        print(
            "❌ エラー: LINE_CHANNEL_ACCESS_TOKEN が未設定です。.env を確認してください",
            file=sys.stderr,
        )
        return 2

    # 3. target 確認
    target = args.to_id or os.environ.get("LINE_USER_ID")
    if not target:
        print(
            "❌ エラー: 送信先が未指定です。.env の LINE_USER_ID を設定するか --to を指定してください",
            file=sys.stderr,
        )
        return 2

    # 4. メッセージ決定
    message = "Hello from 株ボールシステム 👋" if args.who else args.message

    # 5. 送信前ログ
    # IDは先頭10文字だけマスク、メッセージは30文字
    masked_target = target[:10] + "..."
    masked_message = message[:30] + "..."
    print(f"送信中: to={masked_target} / body={masked_message}")

    # 6. 送信実行とエラーハンドリング
    try:
        push_text(target, message)
        print("✅ 送信成功")
    except ApiException as e:
        status = getattr(e, "status", None)
        if status == 401:
            reason = "アクセストークンが無効です。LINE Developers Console で再発行し .env を更新してください"
        elif status == 403:
            reason = "送信先がBotを友だち登録していません。株ボールシステムのQRコードで友だち追加してください"
        elif status == 400:
            reason = "送信先IDが不正です。LINE_USER_ID が株ボールシステムチャネルのuser_idであることを確認してください（他Botのuser_idは使えません）"
        elif status == 429:
            reason = "LINE側のレート制限に達しました。時間を置いて再試行してください"
        else:
            api_reason = getattr(e, "reason", "不明なエラー")
            reason = f"LINE APIエラー (status={status}): {api_reason}"
            
        print(f"❌ エラー: {reason}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ エラー: 想定外エラー: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
