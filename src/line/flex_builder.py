"""
LINE Flex Message ビルダー
目標進捗を達成率に応じた色・エフェクトでリッチ表示
"""
from __future__ import annotations
from src.stock.goal_tracker import GoalProgress


def _color(achievement_pct: float, actual_pnl: float) -> str:
    if actual_pnl < 0:        return "#FF4444"   # 赤: マイナス
    if achievement_pct >= 100: return "#FFD700"  # ゴールド: 達成
    if achievement_pct >= 60:  return "#00C851"  # 緑: 順調
    if achievement_pct >= 30:  return "#FF8800"  # オレンジ: 中間
    return "#0099FF"                              # 青: 序盤


def _effect_header(achievement_pct: float, actual_pnl: float) -> str:
    if actual_pnl < 0:         return "💪 巻き返しモード"
    if achievement_pct >= 100: return "🏆🎉 目標達成！！"
    if achievement_pct >= 90:  return "🎯 目前！あと一歩"
    if achievement_pct >= 60:  return "⚡ ラストスパート"
    if achievement_pct >= 30:  return "🔥 折り返し通過"
    return "🌱 スタートダッシュ"


def build_goal_flex(p: GoalProgress) -> dict:
    """
    Flex Message の contents dict を返す（BubbleContainer）
    LINE Messaging API の FlexMessage.contents に渡す
    """
    color      = _color(p.achievement_pct, p.actual_pnl)
    header_txt = _effect_header(p.achievement_pct, p.actual_pnl)
    label      = f"{p.year}年{p.month}月" if p.goal_type == "monthly" else f"{p.year}年間"
    pct_str    = f"{p.achievement_pct:.1f}%"
    bar_pct    = min(p.achievement_pct / 100, 1.0)

    def row(label: str, value: str, color: str = "#555555") -> dict:
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#888888", "flex": 2},
                {"type": "text", "text": value, "size": "sm", "color": color,
                 "align": "end", "flex": 3},
            ],
        }

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": header_txt, "color": "#FFFFFF",
                 "weight": "bold", "size": "lg"},
                {"type": "text", "text": f"{label} 目標進捗", "color": "#FFFFFF",
                 "size": "sm", "margin": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                # 達成率 大表示
                {
                    "type": "box",
                    "layout": "vertical",
                    "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": pct_str, "size": "5xl",
                         "weight": "bold", "color": color, "align": "center"},
                        {"type": "text", "text": "達成率", "size": "xs",
                         "color": "#888888", "align": "center"},
                    ],
                },
                # プログレスバー
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#EEEEEE",
                    "cornerRadius": "10px",
                    "height": "12px",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "backgroundColor": color,
                            "cornerRadius": "10px",
                            "height": "12px",
                            "width": f"{int(bar_pct * 100)}%",
                            "contents": [],
                        }
                    ],
                },
                {"type": "separator", "margin": "md"},
                # 損益詳細
                row("実現損益", f"¥{p.actual_pnl:+,.0f}",
                    "#00C851" if p.actual_pnl >= 0 else "#FF4444"),
                row("目標損益", f"¥{p.target_pnl:+,.0f}"),
                row("残り",    f"¥{p.remaining_pnl:+,.0f}",
                    "#FF8800" if p.remaining_pnl > 0 else "#00C851"),
                {"type": "separator"},
                row("勝率",     f"{p.actual_winrate:.1f}%  ({p.win_trades}勝{p.total_trades-p.win_trades}敗)"),
                row("取引数",   f"{p.total_trades}回"),
                row("経過日数", f"{p.elapsed_days} / {p.total_days}日"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F8F8F8",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "text",
                    "text": p.pace_message,
                    "size": "sm",
                    "color": color,
                    "weight": "bold",
                    "wrap": True,
                    "align": "center",
                }
            ],
        },
    }
