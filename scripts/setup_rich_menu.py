"""
Step9: LINE リッチメニュー セットアップスクリプト
実行すると 6ボタンのリッチメニューを LINE に登録し、全ユーザーに適用する。

使い方:
  python scripts/setup_rich_menu.py          # 作成 & 適用
  python scripts/setup_rich_menu.py delete   # 既存メニューを全削除
"""
from __future__ import annotations
import os, sys, json, logging
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN    = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
HEADERS  = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
BASE_URL = "https://api.line.me/v2/bot"


# ------------------------------------------------------------------ #
# リッチメニュー定義（2行 × 3列 = 6ボタン）
# ------------------------------------------------------------------ #

RICH_MENU_DEF = {
    "size": {"width": 2500, "height": 1686},
    "selected": True,
    "name": "Stock AI Agent メニュー",
    "chatBarText": "メニューを開く",
    "areas": [
        # 上段左: 今日の相場
        {
            "bounds": {"x": 0,    "y": 0,   "width": 833, "height": 843},
            "action": {"type": "message", "label": "今日の相場",
                       "text": "/check ^N225"},
        },
        # 上段中: ポートフォリオ
        {
            "bounds": {"x": 833,  "y": 0,   "width": 834, "height": 843},
            "action": {"type": "message", "label": "ポートフォリオ",
                       "text": "/port"},
        },
        # 上段右: 目標進捗
        {
            "bounds": {"x": 1667, "y": 0,   "width": 833, "height": 843},
            "action": {"type": "message", "label": "目標進捗",
                       "text": "/goal"},
        },
        # 下段左: スクリーナー
        {
            "bounds": {"x": 0,    "y": 843, "width": 833, "height": 843},
            "action": {"type": "message", "label": "スクリーン",
                       "text": "/screen oversold"},
        },
        # 下段中: グラフ
        {
            "bounds": {"x": 833,  "y": 843, "width": 834, "height": 843},
            "action": {"type": "message", "label": "収支グラフ",
                       "text": "/chart monthly"},
        },
        # 下段右: ヘルプ
        {
            "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
            "action": {"type": "message", "label": "ヘルプ",
                       "text": "/help"},
        },
    ],
}


def _create_rich_menu() -> str:
    """リッチメニューを作成して ID を返す"""
    res = httpx.post(f"{BASE_URL}/richmenu",
                     headers=HEADERS,
                     json=RICH_MENU_DEF)
    res.raise_for_status()
    menu_id = res.json()["richMenuId"]
    log.info(f"リッチメニュー作成: {menu_id}")
    return menu_id


def _upload_image(menu_id: str, image_path: str | None = None) -> None:
    """
    リッチメニュー画像をアップロード。
    image_path が None の場合はプレースホルダー画像を生成してアップ。
    """
    if image_path and Path(image_path).exists():
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        content_type = "image/png" if image_path.endswith(".png") else "image/jpeg"
    else:
        img_bytes   = _generate_placeholder_image()
        content_type = "image/png"

    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": content_type}
    res = httpx.post(
        f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
        headers=headers,
        content=img_bytes,
    )
    res.raise_for_status()
    log.info("リッチメニュー画像アップロード完了")


def _generate_placeholder_image() -> bytes:
    """6ボタンのプレースホルダー画像を matplotlib で生成"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import io

    W, H = 2500, 1686
    fig  = plt.figure(figsize=(W/150, H/150), dpi=150)
    ax   = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("#1A1A2E")

    buttons = [
        (0,    H//2, W//3,   H//2, "📊 今日の相場",     "/check ^N225"),
        (W//3, H//2, W//3,   H//2, "💼 ポートフォリオ", "/port"),
        (2*W//3, H//2, W//3, H//2, "🎯 目標進捗",       "/goal"),
        (0,    0,    W//3,   H//2, "🔍 スクリーン",     "/screen oversold"),
        (W//3, 0,    W//3,   H//2, "📈 収支グラフ",     "/chart monthly"),
        (2*W//3, 0,  W//3,   H//2, "❓ ヘルプ",         "/help"),
    ]

    colors = ["#16213E", "#0F3460", "#1A1A2E",
              "#0F3460", "#16213E", "#1A1A2E"]
    accent = "#FFD700"

    for (x, y, w, h, label, cmd), bg in zip(buttons, colors):
        rect = mpatches.FancyBboxPatch(
            (x + 10, y + 10), w - 20, h - 20,
            boxstyle="round,pad=5", linewidth=2,
            edgecolor=accent, facecolor=bg,
        )
        ax.add_patch(rect)
        # 上: emoji + ラベル
        ax.text(x + w/2, y + h * 0.62, label,
                ha="center", va="center", fontsize=26,
                color="#E0E0E0", fontweight="bold")
        # 下: コマンド
        ax.text(x + w/2, y + h * 0.32, cmd,
                ha="center", va="center", fontsize=18,
                color=accent)

    # 境界線
    for xi in [W//3, 2*W//3]:
        ax.axvline(xi, color=accent, linewidth=2, alpha=0.3)
    ax.axhline(H//2, color=accent, linewidth=2, alpha=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _set_default_rich_menu(menu_id: str) -> None:
    res = httpx.post(f"{BASE_URL}/user/all/richmenu/{menu_id}",
                     headers={"Authorization": f"Bearer {TOKEN}"})
    res.raise_for_status()
    log.info(f"デフォルトリッチメニュー設定完了: {menu_id}")


def _delete_all_rich_menus() -> None:
    res = httpx.get(f"{BASE_URL}/richmenu/list",
                    headers={"Authorization": f"Bearer {TOKEN}"})
    res.raise_for_status()
    menus = res.json().get("richmenus", [])
    for m in menus:
        mid = m["richMenuId"]
        httpx.delete(f"{BASE_URL}/richmenu/{mid}",
                     headers={"Authorization": f"Bearer {TOKEN}"})
        log.info(f"削除: {mid}")
    log.info(f"{len(menus)}件のリッチメニューを削除しました")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "delete":
        _delete_all_rich_menus()
        return

    image_path = sys.argv[1] if len(sys.argv) > 1 else None

    menu_id = _create_rich_menu()
    _upload_image(menu_id, image_path)
    _set_default_rich_menu(menu_id)

    log.info("=" * 50)
    log.info(f"リッチメニュー設定完了！ ID: {menu_id}")
    log.info("LINEアプリを再起動して確認してください")


if __name__ == "__main__":
    main()
