"""
Step8: 収支グラフ生成
matplotlib で PNG を生成し bytes で返す。
Supabase Storage にアップロードして LINE に画像 URL を送る。
"""
from __future__ import annotations
import io
import warnings
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")   # GUI不要
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import numpy as np

from src.db.supabase_client import get_client

warnings.filterwarnings("ignore")
JST = timezone(timedelta(hours=9))

# ---- スタイル共通設定 ----
PALETTE = {
    "profit": "#00C851",
    "loss":   "#FF4444",
    "neutral":"#AAAAAA",
    "bg":     "#1A1A2E",
    "card":   "#16213E",
    "text":   "#E0E0E0",
    "accent": "#FFD700",
}

def _apply_dark_style(fig: plt.Figure, axes) -> None:
    fig.patch.set_facecolor(PALETTE["bg"])
    for ax in (axes if hasattr(axes, "__iter__") else [axes]):
        ax.set_facecolor(PALETTE["card"])
        ax.tick_params(colors=PALETTE["text"])
        ax.xaxis.label.set_color(PALETTE["text"])
        ax.yaxis.label.set_color(PALETTE["text"])
        ax.title.set_color(PALETTE["accent"])
        for spine in ax.spines.values():
            spine.set_edgecolor("#333355")


def _fetch_trades(user_id: str, months: int = 6) -> list[dict]:
    from datetime import date
    import calendar
    today  = datetime.now(JST).date()
    start  = date(today.year if today.month > months else today.year - 1,
                  ((today.month - months - 1) % 12) + 1, 1)
    res = (
        get_client()
        .table("trade_history")
        .select("pnl, traded_at, ticker")
        .eq("user_id", user_id)
        .eq("side", "sell")
        .gte("traded_at", start.isoformat())
        .order("traded_at")
        .execute()
    )
    return res.data or []


def _to_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ------------------------------------------------------------------ #
# グラフ①: 月次損益棒グラフ
# ------------------------------------------------------------------ #

def generate_monthly_pnl_chart(user_id: str) -> bytes:
    trades = _fetch_trades(user_id, months=12)
    if not trades:
        return _empty_chart("月次損益データなし")

    from collections import defaultdict
    monthly: dict[str, float] = defaultdict(float)
    for t in trades:
        if t.get("pnl") is None:
            continue
        ym = t["traded_at"][:7]   # "YYYY-MM"
        monthly[ym] += float(t["pnl"])

    months  = sorted(monthly.keys())
    values  = [monthly[m] for m in months]
    colors  = [PALETTE["profit"] if v >= 0 else PALETTE["loss"] for v in values]
    labels  = [m[5:] + "月" for m in months]

    fig, ax = plt.subplots(figsize=(10, 5))
    _apply_dark_style(fig, ax)

    bars = ax.bar(labels, values, color=colors, width=0.6, zorder=3)
    ax.axhline(0, color=PALETTE["neutral"], linewidth=0.8, linestyle="--")
    ax.set_title("月次損益", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("損益（円）")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"¥{x:+,.0f}"))
    ax.grid(axis="y", alpha=0.2, zorder=0)

    # 棒の上に金額ラベル
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (max(values) * 0.02 if val >= 0 else min(values) * 0.02),
                f"¥{val:+,.0f}", ha="center", va="bottom" if val >= 0 else "top",
                color=PALETTE["text"], fontsize=8)

    total = sum(values)
    ax.text(0.98, 0.97, f"合計: ¥{total:+,.0f}",
            transform=ax.transAxes, ha="right", va="top",
            color=PALETTE["accent"], fontsize=11, fontweight="bold")

    return _to_png(fig)


# ------------------------------------------------------------------ #
# グラフ②: 累計損益エクイティカーブ
# ------------------------------------------------------------------ #

def generate_equity_curve(user_id: str) -> bytes:
    trades = _fetch_trades(user_id, months=12)
    if not trades:
        return _empty_chart("取引データなし")

    pnls  = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    dates = [t["traded_at"][:10] for t in trades if t.get("pnl") is not None]
    if not pnls:
        return _empty_chart("実現損益データなし")

    cumulative = np.cumsum(pnls)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7),
                                    gridspec_kw={"height_ratios": [3, 1]})
    _apply_dark_style(fig, [ax1, ax2])

    # 上段: エクイティカーブ
    final_color = PALETTE["profit"] if cumulative[-1] >= 0 else PALETTE["loss"]
    ax1.plot(range(len(cumulative)), cumulative, color=final_color,
             linewidth=2, zorder=3)
    ax1.fill_between(range(len(cumulative)), cumulative, 0,
                     where=cumulative >= 0, alpha=0.15,
                     color=PALETTE["profit"])
    ax1.fill_between(range(len(cumulative)), cumulative, 0,
                     where=cumulative < 0, alpha=0.15,
                     color=PALETTE["loss"])
    ax1.axhline(0, color=PALETTE["neutral"], linewidth=0.8, linestyle="--")
    ax1.set_title("累計損益エクイティカーブ", fontsize=14, fontweight="bold", pad=12)
    ax1.set_ylabel("累計損益（円）")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"¥{x:+,.0f}"))
    ax1.grid(alpha=0.15, zorder=0)
    ax1.set_xticks([])

    # 最大・最小をアノテート
    peak_idx = int(np.argmax(cumulative))
    ax1.annotate(f"最高 ¥{cumulative[peak_idx]:+,.0f}",
                 xy=(peak_idx, cumulative[peak_idx]),
                 xytext=(peak_idx + len(cumulative) * 0.05, cumulative[peak_idx]),
                 color=PALETTE["profit"], fontsize=8,
                 arrowprops=dict(arrowstyle="->", color=PALETTE["profit"]))

    # 下段: 個別損益バー
    bar_colors = [PALETTE["profit"] if p >= 0 else PALETTE["loss"] for p in pnls]
    ax2.bar(range(len(pnls)), pnls, color=bar_colors, width=0.8, zorder=3)
    ax2.axhline(0, color=PALETTE["neutral"], linewidth=0.8, linestyle="--")
    ax2.set_title("個別トレード損益", fontsize=9, pad=4)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"¥{x:+,.0f}"))
    ax2.grid(axis="y", alpha=0.15, zorder=0)
    ax2.set_xticks([])

    fig.tight_layout(h_pad=1.5)
    return _to_png(fig)


# ------------------------------------------------------------------ #
# グラフ③: 勝率ドーナツ + 月別勝敗ヒートマップ
# ------------------------------------------------------------------ #

def generate_winrate_chart(user_id: str) -> bytes:
    trades = _fetch_trades(user_id, months=6)
    pnls   = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    if not pnls:
        return _empty_chart("取引データなし")

    wins   = sum(1 for p in pnls if p > 0)
    losses = len(pnls) - wins
    total  = len(pnls)
    wr     = wins / total * 100

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
    _apply_dark_style(fig, [ax1, ax2])

    # 左: ドーナツチャート
    wedges, _, autotexts = ax1.pie(
        [wins, losses],
        labels=["勝ち", "負け"],
        colors=[PALETTE["profit"], PALETTE["loss"]],
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops={"width": 0.55, "edgecolor": PALETTE["bg"], "linewidth": 2},
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_color(PALETTE["text"])
        at.set_fontsize(11)
    ax1.set_title("勝敗内訳", fontsize=13, fontweight="bold")
    ax1.text(0, 0, f"{wr:.1f}%\n勝率",
             ha="center", va="center",
             color=PALETTE["accent"], fontsize=14, fontweight="bold")

    # 右: 統計サマリー
    avg_win  = np.mean([p for p in pnls if p > 0]) if wins > 0 else 0
    avg_loss = np.mean([p for p in pnls if p < 0]) if losses > 0 else 0
    pf       = abs(sum(p for p in pnls if p > 0) / sum(p for p in pnls if p < 0)) if losses > 0 else float("inf")

    stats = [
        ("総トレード数",  f"{total}回"),
        ("勝ちトレード",  f"{wins}回"),
        ("負けトレード",  f"{losses}回"),
        ("平均利益",      f"¥{avg_win:+,.0f}"),
        ("平均損失",      f"¥{avg_loss:+,.0f}"),
        ("PF",            f"{pf:.2f}"),
        ("合計損益",      f"¥{sum(pnls):+,.0f}"),
    ]
    ax2.axis("off")
    y = 0.9
    for label, value in stats:
        color = PALETTE["profit"] if "+" in value else (PALETTE["loss"] if "-" in value and "¥" in value else PALETTE["text"])
        ax2.text(0.1, y, label, transform=ax2.transAxes,
                 color=PALETTE["neutral"], fontsize=10)
        ax2.text(0.7, y, value, transform=ax2.transAxes,
                 color=color, fontsize=10, fontweight="bold", ha="right")
        y -= 0.12

    ax2.set_title("詳細統計", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _to_png(fig)


def _empty_chart(message: str) -> bytes:
    fig, ax = plt.subplots(figsize=(6, 3))
    _apply_dark_style(fig, ax)
    ax.text(0.5, 0.5, message, transform=ax.transAxes,
            ha="center", va="center", color=PALETTE["neutral"], fontsize=12)
    ax.axis("off")
    return _to_png(fig)
