from __future__ import annotations
import dataclasses
from datetime import datetime
from typing import Optional

from src.db.supabase_client import get_client
from src.db.portfolio import get_trade_history

@dataclasses.dataclass
class UserProfile:
    user_id: str
    total_trades: int
    win_rate: float
    avg_pnl: float
    avg_hold_days: float
    sector_winrate: dict[str, dict]
    weekday_pattern: dict[str, int]
    discipline_score: Optional[float]  # 未実装時は None
    generated_at: datetime

SECTOR_MAP = {
    "7203.T": "自動車", "6758.T": "電機", "6861.T": "電機",
    "8306.T": "金融", "9984.T": "通信/IT", "9432.T": "通信/IT",
    "7974.T": "ゲーム", "4063.T": "化学", "6367.T": "機械",
    "8035.T": "半導体", "6920.T": "半導体", "8001.T": "商社",
    "8002.T": "商社", "9501.T": "電力", "7267.T": "自動車",
}

def analyze_user_profile(user_id: str) -> UserProfile:
    trades = get_trade_history(user_id, limit=500)
    
    total_trades = 0
    wins = 0
    total_pnl = 0.0
    
    buy_records = {}
    hold_days_list = []
    
    sector_stats = {}
    
    weekday_pattern = {"月": 0, "火": 0, "水": 0, "木": 0, "金": 0, "土": 0, "日": 0}
    weekdays_str = ["月", "火", "水", "木", "金", "土", "日"]
    
    trades_asc = list(reversed(trades))
    
    for row in trades_asc:
        side = row["side"]
        ticker = row["ticker"]
        dt = datetime.fromisoformat(row["traded_at"])
        wd = weekdays_str[dt.weekday()]
        weekday_pattern[wd] += 1
        
        qty = float(row.get("qty") or 0.0)

        if side == "buy":
            if ticker not in buy_records:
                buy_records[ticker] = []
            # FIFOロット: (date, 残り数量) で保持
            buy_records[ticker].append([dt, qty])
        elif side == "sell":
            pnl = float(row.get("pnl") or 0.0)
            total_trades += 1
            if pnl > 0:
                wins += 1
            total_pnl += pnl

            sector = SECTOR_MAP.get(ticker, "その他")
            if sector not in sector_stats:
                sector_stats[sector] = {"trades": 0, "wins": 0, "pnl": 0.0}
            sector_stats[sector]["trades"] += 1
            if pnl > 0:
                sector_stats[sector]["wins"] += 1
            sector_stats[sector]["pnl"] += pnl

            # 保有日数 = 消費したロットの数量加重平均
            lots = buy_records.get(ticker, [])
            remaining = qty
            weighted_days = 0.0
            consumed_qty = 0.0
            while remaining > 0 and lots:
                lot = lots[0]
                take = min(lot[1], remaining)
                days = (dt - lot[0]).total_seconds() / 86400.0
                weighted_days += days * take
                consumed_qty += take
                lot[1] -= take
                remaining -= take
                if lot[1] <= 0:
                    lots.pop(0)
            if consumed_qty > 0:
                hold_days_list.append(weighted_days / consumed_qty)

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    avg_pnl = (total_pnl / total_trades) if total_trades > 0 else 0.0
    avg_hold_days = (sum(hold_days_list) / len(hold_days_list)) if hold_days_list else 0.0
    
    sector_winrate = {}
    for sec, stats in sector_stats.items():
        st = stats["trades"]
        sw = (stats["wins"] / st * 100.0) if st > 0 else 0.0
        spnl = (stats["pnl"] / st) if st > 0 else 0.0
        sector_winrate[sec] = {"trades": st, "winrate": sw, "avg_pnl": spnl}
        
    # TODO: 損切り実行率の実装（含み損閾値超えからの売却比率）
    # 未実装の間は None にして表示を抑制する
    discipline_score: Optional[float] = None
    
    return UserProfile(
        user_id=user_id,
        total_trades=total_trades,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        avg_hold_days=avg_hold_days,
        sector_winrate=sector_winrate,
        weekday_pattern=weekday_pattern,
        discipline_score=discipline_score,
        generated_at=datetime.now()
    )

def format_profile_message(p: UserProfile) -> str:
    if p.total_trades == 0:
        return "まだ取引履歴がありません"
        
    lines = [
        "📊 あなたの投資プロファイル",
        "",
        "【基本統計】",
        f"総取引数: {p.total_trades}回 / 勝率: {p.win_rate:.1f}% / 平均損益: ¥{p.avg_pnl:+,.0f}",
        f"平均保有日数: {p.avg_hold_days:.1f}日",
        "",
        "【得意セクター TOP3】"
    ]
    
    sorted_sec = sorted(p.sector_winrate.items(), key=lambda x: (x[1]["winrate"], x[1]["trades"]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    for i, (sec, st) in enumerate(sorted_sec[:3]):
        lines.append(f"{medals[i]} {sec}: 勝率{st['winrate']:.0f}% ({st['trades']}回, 平均¥{st['avg_pnl']:+,.0f})")
        
    lines.append("")
    lines.append("【取引曜日パターン】")
    
    wd_str = []
    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        cnt = p.weekday_pattern.get(wd, 0)
        mark = "●" * cnt if cnt > 0 else "-"
        wd_str.append(f"{wd}{mark}")
    lines.append("  ".join(wd_str))
    
    if p.discipline_score is not None:
        lines.append("")
        lines.append("【規律スコア】")
        lines.append(f"{p.discipline_score:.0f}/100 (損切り実行率 ※暫定値)")

    return "\n".join(lines)[:5000]

def save_profile_snapshot(profile: UserProfile):
    client = get_client()
    payload = dataclasses.asdict(profile)
    payload["generated_at"] = profile.generated_at.isoformat()
    
    client.table("user_insights").insert({
        "user_id": profile.user_id,
        "insight_type": "weekly_profile",
        "payload": payload
    }).execute()

def build_personal_context(user_id: str) -> str:
    try:
        p = analyze_user_profile(user_id)
        if p.total_trades < 5:
            return ""
        
        lines = [
            "【このユーザーの傾向】",
            f"総取引{p.total_trades}回 / 勝率{p.win_rate:.0f}% / 平均保有{p.avg_hold_days:.0f}日"
        ]
        
        sorted_sec = sorted(p.sector_winrate.items(), key=lambda x: (x[1]["winrate"], x[1]["trades"]), reverse=True)
        if sorted_sec:
            best = sorted_sec[0]
            if len(sorted_sec) == 1:
                lines.append(f"得意: {best[0]}(勝率{best[1]['winrate']:.0f}%)")
            else:
                worst = sorted_sec[-1]
                lines.append(f"得意: {best[0]}(勝率{best[1]['winrate']:.0f}%) / 苦手: {worst[0]}(勝率{worst[1]['winrate']:.0f}%)")
             
        return "\n".join(lines)
    except Exception:
        return ""

def analyze_win_lose_patterns(user_id: str) -> dict:
    trades = get_trade_history(user_id, limit=500)
    
    buy_records = {}
    win_list = []
    lose_list = []
    
    weekdays_str = ["月", "火", "水", "木", "金", "土", "日"]
    trades_asc = list(reversed(trades))
    
    for row in trades_asc:
        side = row["side"]
        ticker = row["ticker"]
        dt = datetime.fromisoformat(row["traded_at"])
        wd = weekdays_str[dt.weekday()]
        qty = float(row.get("qty") or 0.0)
        price = float(row.get("price") or 0.0)
        
        if side == "buy":
            if ticker not in buy_records:
                buy_records[ticker] = []
            buy_records[ticker].append([dt, qty])
        elif side == "sell":
            pnl = float(row.get("pnl") or 0.0)
            sector = SECTOR_MAP.get(ticker, "その他")
            
            lots = buy_records.get(ticker, [])
            remaining = qty
            weighted_days = 0.0
            consumed_qty = 0.0
            while remaining > 0 and lots:
                lot = lots[0]
                take = min(lot[1], remaining)
                days = (dt - lot[0]).total_seconds() / 86400.0
                weighted_days += days * take
                consumed_qty += take
                lot[1] -= take
                remaining -= take
                if lot[1] <= 0:
                    lots.pop(0)
            
            hold_days = weighted_days / consumed_qty if consumed_qty > 0 else 0.0
            pos_size = qty * price
            
            record = {
                "sector": sector,
                "weekday": wd,
                "hold_days": hold_days,
                "pos_size": pos_size
            }
            
            if pnl > 0:
                win_list.append(record)
            else:
                lose_list.append(record)
                
    def summarize(lst):
        if not lst:
            return None
        count = len(lst)
        avg_hold_days = sum(x["hold_days"] for x in lst) / count
        avg_pos_size = sum(x["pos_size"] for x in lst) / count
        sectors = {}
        weekdays = {}
        for x in lst:
            sectors[x["sector"]] = sectors.get(x["sector"], 0) + 1
            weekdays[x["weekday"]] = weekdays.get(x["weekday"], 0) + 1
        return {
            "count": count,
            "avg_hold_days": avg_hold_days,
            "avg_position_size": avg_pos_size,
            "sectors": sectors,
            "weekdays": weekdays
        }
        
    return {
        "win": summarize(win_list),
        "lose": summarize(lose_list)
    }

def format_pattern_diff_message(diff: dict, strength: bool) -> str:
    if strength:
        target = diff.get("win")
        other = diff.get("lose")
        title = "💪 あなたの得意パターン"
        desc = "勝ち"
        other_desc = "負け"
    else:
        target = diff.get("lose")
        other = diff.get("win")
        title = "⚠️ 苦手パターン注意"
        desc = "負け"
        other_desc = "勝ち"
        
    lines = [title, ""]
    
    count = target["count"]
    
    # 1. Sector
    top_sector = sorted(target["sectors"].items(), key=lambda x: x[1], reverse=True)[0]
    lines.append(f"1. セクター: {top_sector[0]} ({desc}{count}回中{top_sector[1]}回)")
    
    # 2. Hold days
    other_hold = other["avg_hold_days"] if other else 0
    hold_diff = abs(target["avg_hold_days"] - other_hold) if other else 0
    if other:
        lines.append(f"2. 保有日数: 平均{target['avg_hold_days']:.1f}日（{other_desc}より{hold_diff:.1f}日{'短い' if target['avg_hold_days'] < other_hold else '長い'}）")
    else:
        lines.append(f"2. 保有日数: 平均{target['avg_hold_days']:.1f}日")
    
    # 3. Position Size or Weekday
    if strength:
        top_wd = sorted(target["weekdays"].items(), key=lambda x: x[1], reverse=True)[0]
        lines.append(f"3. 取引曜日: {top_wd[0]}曜が最も{desc}やすい")
    else:
        lines.append(f"3. ポジションサイズ: {desc}取引は平均¥{target['avg_position_size']:,.0f}")
        
    if not strength:
        from src.ai.analyst import analyze
        context = "\n".join(lines)
        advice = analyze(context, "この苦手パターンに対する具体的な改善提案を2〜3文で出力してください。")
        lines.append("\n🤖 AI改善提案\n" + advice)
        
    return "\n".join(lines)
