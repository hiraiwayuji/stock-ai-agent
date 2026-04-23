import os
import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

st.set_page_config(page_title="Stock AI Agent — Group Dashboard", page_icon="📈", layout="wide")

load_dotenv()

# Streamlit Cloud Secret handling (secrets.toml 未設定でも起動できるようガード)
try:
    if "SUPABASE_URL" in st.secrets:
        os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
except Exception:
    pass  # ローカル .env にフォールバック

# DB imports (Must happen after env is set)
from src.db.supabase_client import get_client
from src.db.groups import ranking, fetch_timeline, list_group_members
from src.ai.personal_profile import SECTOR_MAP

def main():
    code = st.query_params.get("code", "")
    
    if not code:
        code = st.text_input("招待コードを入力してください", value="", type="password")
        if not code:
            st.info("グループの招待コードを入力するとダッシュボードが表示されます。")
            st.stop()
            
    client = get_client()
    try:
        res = client.table("groups").select("*").eq("invite_code", code).execute()
        if not res.data:
            st.error("不正な招待コードです。")
            st.stop()
            
        group = res.data[0]
        group_id = group["id"]
        group_name = group["name"]
        line_group_id = group.get("line_group_id")
        
        st.title(f"📈 {group_name}")
        st.caption(f"招待コード: {code}")
        
        tab_rank, tab_time, tab_sec, tab_alert = st.tabs(["🏆 ランキング", "📜 タイムライン", "📊 セクター集計", "🚨 アラート履歴"])
        
        # ---------------------------
        # Tab 1: Ranking
        # ---------------------------
        with tab_rank:
            period_label = st.radio("集計期間", ["今月", "直近30日", "年間"], horizontal=True)
            if period_label == "年間":
                days = 365
            elif period_label == "今月":
                # 簡易的に直近30日とする
                days = 30
            else:
                days = 30
                
            try:
                members = list_group_members(group_id)
                rows = ranking(group_id, period_days=days)
                
                total_trades = sum(r['trades'] for r in rows) if rows else 0
                total_pnl = sum(r['pnl'] for r in rows) if rows else 0.0
                
                col1, col2, col3 = st.columns(3)
                col1.metric("参加メンバー", f"{len(members)}名")
                col2.metric("総取引数", f"{total_trades}回")
                col3.metric("グループ合計損益", f"¥{total_pnl:+,.0f}")
                
                st.write("---")
                
                if not rows:
                    st.info("この期間の共有売買はありません。")
                else:
                    medals = ["🥇", "🥈", "🥉"]
                    df_rows = []
                    for i, r in enumerate(rows):
                        rank_str = medals[i] if i < 3 else f"{i+1}."
                        df_rows.append({
                            "順位": rank_str,
                            "ユーザー": r['user_id'][:8], # Nicknameがあれば良いが、rankingはuser_idベース
                            "損益 (円)": r['pnl'],
                            "取引回数": r['trades'],
                            "勝率 (%)": f"{r['winrate']:.1f}%"
                        })
                        
                    df_rank = pd.DataFrame(df_rows)
                    st.dataframe(df_rank, use_container_width=True)
            except Exception as e:
                st.error(f"ランキング取得エラー: {e}")

        # ---------------------------
        # Tab 2: Timeline
        # ---------------------------
        with tab_time:
            limit = st.slider("表示件数", 10, 100, 30)
            try:
                msgs = fetch_timeline(group_id, limit=limit)
                if not msgs:
                    st.info("タイムラインはまだ空です。")
                else:
                    for m in msgs:
                        with st.container():
                            kind = m.get("kind", "comment")
                            dt_str = m.get("created_at", "")[:16].replace("T", " ")
                            user = m.get("user_id", "")[:8]
                            body = m.get("body", "")
                            
                            if kind == "trade":
                                icon = "💹"
                                st.markdown(f"**{icon} {user}** &nbsp;&nbsp; <small>{dt_str}</small>", unsafe_allow_html=True)
                                st.success(body)
                            elif kind == "comment":
                                icon = "💬"
                                st.markdown(f"**{icon} {user}** &nbsp;&nbsp; <small>{dt_str}</small>", unsafe_allow_html=True)
                                st.info(body)
                            else:
                                icon = "🔔"
                                st.markdown(f"**{icon} System** &nbsp;&nbsp; <small>{dt_str}</small>", unsafe_allow_html=True)
                                st.warning(body)
            except Exception as e:
                st.error(f"タイムライン取得エラー: {e}")

        # ---------------------------
        # Tab 3: Sector
        # ---------------------------
        with tab_sec:
            try:
                # Group shares
                res_shares = client.table("trade_shares").select("*").eq("group_id", group_id).execute()
                shares = res_shares.data or []
                
                if not shares:
                    st.info("共有データが不足しています。")
                else:
                    sector_stats = {}
                    for s in shares:
                        if s["side"] != "sell":
                            continue
                        ticker = s["ticker"]
                        pnl = float(s.get("pnl") or 0.0)
                        sec = SECTOR_MAP.get(ticker, "その他")
                        
                        if sec not in sector_stats:
                            sector_stats[sec] = {"trades": 0, "wins": 0, "pnl": 0.0}
                        sector_stats[sec]["trades"] += 1
                        if pnl > 0:
                            sector_stats[sec]["wins"] += 1
                        sector_stats[sec]["pnl"] += pnl
                        
                    if not sector_stats:
                        st.info("売却共有データが不足しています。")
                    else:
                        sec_rows = []
                        for sec, stats in sector_stats.items():
                            tr = stats["trades"]
                            wr = (stats["wins"] / tr * 100) if tr > 0 else 0
                            apnl = stats["pnl"] / tr if tr > 0 else 0
                            sec_rows.append({
                                "セクター": sec,
                                "勝率 (%)": wr,
                                "平均損益": apnl,
                                "取引数": tr
                            })
                            
                        df_sec = pd.DataFrame(sec_rows)
                        df_sec = df_sec.sort_values("勝率 (%)", ascending=True)
                        
                        fig = px.bar(df_sec, x="勝率 (%)", y="セクター", orientation="h", title="セクター別勝率")
                        st.plotly_chart(fig, use_container_width=True)
                        
                        st.dataframe(df_sec.sort_values("勝率 (%)", ascending=False).style.format({"勝率 (%)": "{:.1f}", "平均損益": "{:,.0f}"}), use_container_width=True)

            except Exception as e:
                st.error(f"セクター集計エラー: {e}")

        # ---------------------------
        # Tab 4: Alerts
        # ---------------------------
        with tab_alert:
            try:
                if not line_group_id:
                    st.info("LINEグループとの連携が行われていません。")
                else:
                    res_al = client.table("alert_history").select("*").eq("user_id", line_group_id).like("alert_type", "group_critical%").order("sent_at", desc=True).limit(20).execute()
                    alerts = res_al.data or []
                    
                    if not alerts:
                        st.info("直近アラートなし ✅")
                    else:
                        for al in alerts:
                            with st.container():
                                dt_str = al.get("sent_at", "")[:16].replace("T", " ")
                                st.markdown(f"**🚨 重大アラート** &nbsp;&nbsp; <small>{dt_str}</small>", unsafe_allow_html=True)
                                st.error(al.get("message", ""))
            except Exception as e:
                st.error(f"アラート履歴取得エラー: {e}")

    except Exception as e:
        st.error(f"システムエラー: {e}")

if __name__ == "__main__":
    main()
