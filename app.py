import os
import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

st.set_page_config(page_title="Stock AI Agent — Group Dashboard", page_icon="📈", layout="wide")

# 未認証ユーザー向けに、マニュアルページへの誘導を表示（ダッシュボードは招待コード必須のまま）

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
        
        tab_rank, tab_time, tab_sec, tab_alert, tab_holdings, tab_personal = st.tabs([
            "🏆 ランキング",
            "📜 タイムライン",
            "📊 セクター集計",
            "🚨 アラート履歴",
            "💼 グループ保有分析",
            "🎯 私のパネル",
        ])
        
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
                    res_al = client.table("alert_history").select("*").eq("user_id", line_group_id).order("sent_at", desc=True).limit(50).execute()
                    raw_alerts = res_al.data or []
                    alerts = [al for al in raw_alerts if al.get("alert_type", "").startswith("group_critical")][:20]
                    
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

        # ---------------------------
        # Tab 5: Group Holdings
        # ---------------------------
        with tab_holdings:
            st.subheader(f"{group_name} メンバーの保有銘柄集約")
            try:
                members = list_group_members(group_id)
                if not members:
                    st.info("メンバーがまだいません。")
                else:
                    # 全メンバーの保有銘柄を収集
                    from src.db.portfolio import get_positions
                    all_positions = []
                    for m in members:
                        uid = m.get("user_id") if isinstance(m, dict) else getattr(m, "user_id", None)
                        nick = m.get("nickname") if isinstance(m, dict) else getattr(m, "nickname", None)
                        if not uid:
                            continue
                        positions = get_positions(uid)
                        for p in positions:
                            all_positions.append({
                                "ticker": p.get("ticker"),
                                "qty": float(p.get("qty") or 0),
                                "avg_cost": float(p.get("avg_cost") or 0),
                                "realized_pnl": float(p.get("realized_pnl") or 0),
                                "user_id": uid,
                                "nickname": nick or uid[:6],
                            })
                    
                    if not all_positions:
                        st.info("まだ誰も保有銘柄を登録していません。\nLINE Bot で /buy <ticker> <単価> <株数> コマンドを使うと登録されます。")
                    else:
                        df_pos = pd.DataFrame(all_positions)
                        
                        # --- 人気銘柄 TOP10（保有メンバー数順）---
                        st.markdown("### 🔥 グループで人気の銘柄 TOP10")
                        popular = (
                            df_pos.groupby("ticker")
                            .agg(
                                holders=("user_id", "nunique"),
                                total_qty=("qty", "sum"),
                                avg_cost_mean=("avg_cost", "mean"),
                            )
                            .sort_values("holders", ascending=False)
                            .head(10)
                            .reset_index()
                        )
                        popular.columns = ["銘柄", "保有者数", "合計株数", "平均取得単価"]
                        st.dataframe(popular, use_container_width=True)
                        
                        # --- セクター集中度（円グラフ）---
                        st.markdown("### 📊 セクター集中度（保有株数ベース）")
                        df_pos["sector"] = df_pos["ticker"].map(lambda t: SECTOR_MAP.get(t, "その他"))
                        sector_agg = df_pos.groupby("sector")["qty"].sum().reset_index()
                        fig_sec = px.pie(sector_agg, values="qty", names="sector", title="セクター保有比率")
                        st.plotly_chart(fig_sec, use_container_width=True)
                        
                        # --- メンバー別 実現損益 ---
                        st.markdown("### 🏅 メンバー別 実現損益（確定益）")
                        member_pnl = (
                            df_pos.groupby("nickname")["realized_pnl"]
                            .sum()
                            .sort_values(ascending=False)
                            .reset_index()
                        )
                        member_pnl["realized_pnl"] = member_pnl["realized_pnl"].map(lambda x: f"¥{x:+,.0f}")
                        member_pnl.columns = ["メンバー", "実現損益合計"]
                        st.dataframe(member_pnl, use_container_width=True)
                        
                        # --- AIコメント ---
                        st.markdown("### 🎤 トレーナーのひと言")
                        context = f"""
グループ{group_name}の保有銘柄集約:
- メンバー数: {len(members)}名
- 保有銘柄数(重複含む): {len(all_positions)}件
- ユニーク銘柄数: {df_pos['ticker'].nunique()}
- 人気TOP3: {', '.join(popular.head(3)['銘柄'].tolist())}
- セクター偏り: {sector_agg.loc[sector_agg['qty'].idxmax(), 'sector']} に集中
""".strip()
                        try:
                            from src.ai.analyst import analyze
                            comment = analyze(context, "このグループの保有状況の特徴・リスク・強みを3行でコメントしてください。ぼーるくん（投資初心者〜中級者）向けの親しみやすい口調で。")
                            st.info(comment)
                        except Exception as e:
                            st.warning(f"AIコメント生成失敗: {e}")
            except Exception as e:
                st.error(f"グループ保有分析エラー: {e}")

        # ---------------------------
        # Tab 6: Personal Holdings
        # ---------------------------
        with tab_personal:
            st.subheader("🎯 私のパネル")
            st.caption("LINE Bot に /myid と送ると取得できる、あなたの user_id を入力してください。")
            
            my_user_id = st.text_input(
                "あなたの LINE user_id (U で始まる33文字)",
                value="",
                type="password",
                help="LINE で株ボールシステム Bot に /myid と送信すると取得できます。"
            )
            
            if not my_user_id:
                st.info("user_id を入力するとあなたの保有銘柄分析が表示されます。")
            elif not (my_user_id.startswith("U") and len(my_user_id) == 33):
                st.error("user_id の形式が正しくありません（U で始まる33文字）。")
            else:
                try:
                    from src.db.portfolio import get_positions
                    my_positions = get_positions(my_user_id)
                    
                    if not my_positions:
                        st.info("保有銘柄はまだありません。\nLINE Bot で /buy <ticker> <単価> <株数> と送ると登録されます。")
                    else:
                        df_my = pd.DataFrame(my_positions)
                        
                        # 型調整
                        for col in ["qty", "avg_cost", "realized_pnl"]:
                            if col in df_my.columns:
                                df_my[col] = pd.to_numeric(df_my[col], errors="coerce").fillna(0)
                        
                        # --- 保有銘柄一覧 ---
                        st.markdown("### 📝 保有銘柄一覧")
                        df_display = df_my.copy()
                        df_display["投資額"] = df_display["qty"] * df_display["avg_cost"]
                        st.dataframe(
                            df_display[["ticker", "qty", "avg_cost", "投資額", "realized_pnl"]]
                            .rename(columns={
                                "ticker": "銘柄",
                                "qty": "株数",
                                "avg_cost": "取得単価",
                                "realized_pnl": "確定損益",
                            }),
                            use_container_width=True,
                        )
                        
                        # --- サマリー ---
                        total_invested = (df_my["qty"] * df_my["avg_cost"]).sum()
                        total_realized = df_my["realized_pnl"].sum()
                        ticker_count = df_my["ticker"].nunique()
                        col1, col2, col3 = st.columns(3)
                        col1.metric("保有銘柄数", f"{ticker_count}")
                        col2.metric("投資額合計", f"¥{total_invested:,.0f}")
                        col3.metric("確定損益合計", f"¥{total_realized:+,.0f}")
                        
                        # --- セクター配分 ---
                        st.markdown("### 📊 セクター配分")
                        df_my["sector"] = df_my["ticker"].map(lambda t: SECTOR_MAP.get(t, "その他"))
                        df_my["invested"] = df_my["qty"] * df_my["avg_cost"]
                        sec_agg = df_my.groupby("sector")["invested"].sum().reset_index()
                        fig_my = px.pie(sec_agg, values="invested", names="sector", title="投資額ベースのセクター配分")
                        st.plotly_chart(fig_my, use_container_width=True)
                        
                        # --- 勝ち負け銘柄 ---
                        st.markdown("### 🎖️ 得意・苦手銘柄（確定損益ベース）")
                        wins = df_my[df_my["realized_pnl"] > 0].sort_values("realized_pnl", ascending=False).head(5)
                        losses = df_my[df_my["realized_pnl"] < 0].sort_values("realized_pnl").head(5)
                        col_w, col_l = st.columns(2)
                        with col_w:
                            st.markdown("#### ✅ 得意 (TOP5)")
                            if wins.empty:
                                st.caption("まだ確定益の銘柄がありません。")
                            else:
                                st.dataframe(wins[["ticker", "realized_pnl"]].rename(columns={"ticker": "銘柄", "realized_pnl": "確定益"}))
                        with col_l:
                            st.markdown("#### ❌ 苦手 (TOP5)")
                            if losses.empty:
                                st.caption("まだ確定損の銘柄がありません。")
                            else:
                                st.dataframe(losses[["ticker", "realized_pnl"]].rename(columns={"ticker": "銘柄", "realized_pnl": "確定損"}))
                        
                        # --- AIコメント ---
                        st.markdown("### 🎤 トレーナーのひと言")
                        context = f"""
保有銘柄: {', '.join(df_my['ticker'].tolist()[:10])}
銘柄数: {ticker_count}
投資額合計: ¥{total_invested:,.0f}
確定損益: ¥{total_realized:+,.0f}
セクター偏り: {sec_agg.loc[sec_agg['invested'].idxmax(), 'sector']} に集中
""".strip()
                        try:
                            from src.ai.analyst import analyze
                            my_comment = analyze(context, "このポートフォリオの特徴・リスク・改善点を3行でコメントしてください。ぼーるくんへの親しみやすい口調で。必ず情報ソースや根拠を添えて。")
                            st.info(my_comment)
                        except Exception as e:
                            st.warning(f"AIコメント生成失敗: {e}")
                except Exception as e:
                    st.error(f"取得エラー: {e}")

    except Exception as e:
        st.error(f"システムエラー: {e}")

if __name__ == "__main__":
    main()
