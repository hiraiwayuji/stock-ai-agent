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
from src.db.groups import fetch_timeline, list_group_members
from src.ai.personal_profile import SECTOR_MAP


@st.cache_data(ttl=300, show_spinner=False)
def fetch_live_price(ticker: str) -> float | None:
    """yfinance で現在価格取得（5分キャッシュ）。失敗時 None。"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", auto_adjust=False)
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_realized_pnl_by_ticker(user_id: str) -> dict:
    """trade_history から ticker ごとの実現損益を集約。"""
    try:
        client = get_client()
        res = (
            client.table("trade_history")
            .select("ticker, pnl")
            .eq("user_id", user_id)
            .eq("side", "sell")
            .execute()
        )
        rows = res.data or []
        result = {}
        for r in rows:
            t = r.get("ticker")
            p = float(r.get("pnl") or 0)
            if t:
                result[t] = result.get(t, 0.0) + p
        return result
    except Exception:
        return {}


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
        
        tab_time, tab_alert, tab_holdings, tab_personal = st.tabs([
            "📜 タイムライン",
            "🚨 アラート履歴",
            "💼 グループ保有分析",
            "🎯 私のパネル",
        ])
        
        # ---------------------------
        # Tab 1: Timeline
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
        # Tab 2: Alerts
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
                        # 現在価格を併記
                        with st.spinner("銘柄の現在価格を取得中..."):
                            popular["現在価格"] = popular["銘柄"].map(
                                lambda t: fetch_live_price(t)
                            ).map(lambda v: f"¥{v:,.2f}" if v is not None else "—")
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
                        # --- グループトレーナー対話 ---
                        st.markdown("### 🎤 グループトレーナーと対話")
                        st.caption("このグループの保有状況についてトレーナーに何でも聞いてください。")

                        from src.ai.analyst import analyze as _g_analyze

                        group_chat_key = f"group_chat_{group_id}"
                        if group_chat_key not in st.session_state:
                            try:
                                opening = _g_analyze(
                                    context,
                                    "このグループの保有状況の特徴・リスク・強みを3行でコメント。"
                                    "ぼーるくん（投資初心者〜中級者）向けの親しみやすい口調で。"
                                    "断定的な売買推奨は避け、根拠やソースを添える。"
                                )
                            except Exception as e:
                                opening = f"⚠️ 初回コメント生成失敗: {e}"
                            st.session_state[group_chat_key] = [
                                {"role": "assistant", "content": opening},
                            ]

                        for msg in st.session_state[group_chat_key]:
                            with st.chat_message(msg["role"], avatar="🎤" if msg["role"] == "assistant" else "👥"):
                                st.markdown(msg["content"])

                        g_user_q = st.chat_input(
                            "グループトレーナーに質問する（例: みんなが集中してるセクターのリスクは？）",
                            key=f"chat_input_{group_id}",
                        )
                        if g_user_q:
                            st.session_state[group_chat_key].append({"role": "user", "content": g_user_q})
                            with st.chat_message("user", avatar="👥"):
                                st.markdown(g_user_q)

                            history = st.session_state[group_chat_key][:-1]
                            history_text = "\n".join(
                                f"{'トレーナー' if m['role'] == 'assistant' else 'メンバー'}: {m['content']}"
                                for m in history
                            )
                            full_context = (
                                f"[このグループの保有状況]\n{context}\n\n"
                                f"[これまでの会話]\n{history_text}"
                            )
                            try:
                                with st.spinner("トレーナーが考えています..."):
                                    answer = _g_analyze(
                                        full_context,
                                        g_user_q + "\n\n（親しみやすいトレーナー口調で、グループ全体の視点で、断定的売買推奨は避け、根拠・ソースを添えて簡潔に。）"
                                    )
                            except Exception as e:
                                answer = f"⚠️ 応答生成失敗: {e}"

                            st.session_state[group_chat_key].append({"role": "assistant", "content": answer})
                            with st.chat_message("assistant", avatar="🎤"):
                                st.markdown(answer)

                        if st.session_state.get(group_chat_key) and len(st.session_state[group_chat_key]) > 1:
                            if st.button("🔄 グループ会話をリセット", key=f"reset_{group_chat_key}"):
                                del st.session_state[group_chat_key]
                                st.rerun()
            except Exception as e:
                st.error(f"グループ保有分析エラー: {e}")

        # ---------------------------
        # Tab 6: Personal Holdings
        # ---------------------------
        with tab_personal:
            st.subheader("🎯 私のパネル")
            st.caption("LINE Bot に /myid と送ると取得できる、あなたの user_id を入力してください。URLに `?uid=Uxxx...` を付けると次回から自動入力されます。")

            # URL ?uid= → 前回セッションの記憶 → 空 の優先順
            url_uid = st.query_params.get("uid", "")
            default_uid = st.session_state.get("my_user_id", "") or url_uid

            my_user_id = st.text_input(
                "あなたの LINE user_id (U で始まる33文字)",
                value=default_uid,
                type="password",
                help="LINE で株ボールシステム Bot に /myid と送信すると取得できます。"
            )

            # 有効な uid なら session_state に保存（同セッション中は再入力不要）
            if my_user_id and my_user_id.startswith("U") and len(my_user_id) == 33:
                st.session_state["my_user_id"] = my_user_id
            
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

                        # realized_pnl は trade_history から集約
                        realized_map = get_realized_pnl_by_ticker(my_user_id)
                        df_my["realized_pnl"] = df_my["ticker"].map(lambda t: realized_map.get(t, 0))

                        # 型調整
                        for col in ["qty", "avg_cost", "realized_pnl"]:
                            if col in df_my.columns:
                                df_my[col] = pd.to_numeric(df_my[col], errors="coerce").fillna(0)

                        # 現在価格取得
                        with st.spinner("現在価格を取得中..."):
                            df_my["current_price"] = df_my["ticker"].map(lambda t: fetch_live_price(t))

                        # 計算
                        df_my["invested"] = df_my["qty"] * df_my["avg_cost"]
                        df_my["market_value"] = df_my.apply(
                            lambda r: r["qty"] * r["current_price"] if r["current_price"] is not None else None,
                            axis=1,
                        )
                        df_my["unrealized_pnl"] = df_my.apply(
                            lambda r: (r["market_value"] - r["invested"]) if r["market_value"] is not None else None,
                            axis=1,
                        )
                        df_my["unrealized_pct"] = df_my.apply(
                            lambda r: (r["unrealized_pnl"] / r["invested"] * 100) if r["unrealized_pnl"] is not None and r["invested"] else None,
                            axis=1,
                        )

                        # --- 保有銘柄一覧 ---
                        st.markdown("### 📝 保有銘柄一覧")

                        def _fmt_money_signed(v):
                            return f"¥{v:+,.0f}" if v is not None and not pd.isna(v) else "—"

                        def _fmt_money_abs(v):
                            return f"¥{v:,.2f}" if v is not None and not pd.isna(v) else "—"

                        def _fmt_pct(v):
                            return f"{v:+.2f}%" if v is not None and not pd.isna(v) else "—"

                        view = pd.DataFrame({
                            "銘柄": df_my["ticker"],
                            "株数": df_my["qty"].map(lambda x: f"{x:.0f}"),
                            "取得単価": df_my["avg_cost"].map(_fmt_money_abs),
                            "現在値": df_my["current_price"].map(_fmt_money_abs),
                            "投資額": df_my["invested"].map(lambda x: f"¥{x:,.0f}"),
                            "評価額": df_my["market_value"].map(lambda x: f"¥{x:,.0f}" if x is not None and not pd.isna(x) else "—"),
                            "含み損益": df_my["unrealized_pnl"].map(_fmt_money_signed),
                            "含み損益率": df_my["unrealized_pct"].map(_fmt_pct),
                            "確定損益": df_my["realized_pnl"].map(_fmt_money_signed),
                        })
                        st.dataframe(view, use_container_width=True)

                        # --- メトリック ---
                        total_invested = df_my["invested"].sum()
                        total_market = df_my["market_value"].sum(skipna=True)
                        total_unrealized = df_my["unrealized_pnl"].sum(skipna=True)
                        total_realized = df_my["realized_pnl"].sum()
                        total_pnl = total_unrealized + total_realized
                        ticker_count = df_my["ticker"].nunique()

                        cols = st.columns(5)
                        cols[0].metric("銘柄数", f"{ticker_count}")
                        cols[1].metric("投資額", f"¥{total_invested:,.0f}")
                        cols[2].metric("評価額", f"¥{total_market:,.0f}")
                        cols[3].metric(
                            "含み損益",
                            f"¥{total_unrealized:+,.0f}",
                            delta=f"{(total_unrealized/total_invested*100 if total_invested else 0):+.2f}%",
                        )
                        cols[4].metric("総損益", f"¥{total_pnl:+,.0f}", help="含み損益+確定損益")

                        # --- セクター配分 ---
                        st.markdown("### 📊 セクター配分（投資額ベース）")
                        df_my["sector"] = df_my["ticker"].map(lambda t: SECTOR_MAP.get(t, "その他"))
                        sec_agg = df_my.groupby("sector")["invested"].sum().reset_index()
                        fig_my = px.pie(sec_agg, values="invested", names="sector", title="セクター配分")
                        st.plotly_chart(fig_my, use_container_width=True)

                        # --- 勝ち負け銘柄（含み + 確定の総合）---
                        st.markdown("### 🎖️ 得意・苦手銘柄（含み+確定 総合損益）")
                        df_my["total_pnl"] = df_my["unrealized_pnl"].fillna(0) + df_my["realized_pnl"]
                        wins = df_my[df_my["total_pnl"] > 0].sort_values("total_pnl", ascending=False).head(5)
                        losses = df_my[df_my["total_pnl"] < 0].sort_values("total_pnl").head(5)
                        col_w, col_l = st.columns(2)
                        with col_w:
                            st.markdown("#### ✅ 得意 (TOP5)")
                            if wins.empty:
                                st.caption("まだプラス銘柄がありません。")
                            else:
                                st.dataframe(wins[["ticker", "total_pnl"]].rename(columns={"ticker": "銘柄", "total_pnl": "総損益"}))
                        with col_l:
                            st.markdown("#### ❌ 苦手 (TOP5)")
                            if losses.empty:
                                st.caption("まだマイナス銘柄がありません。")
                            else:
                                st.dataframe(losses[["ticker", "total_pnl"]].rename(columns={"ticker": "銘柄", "total_pnl": "総損益"}))

                        # --- AIトレーナーとのチャット ---
                        st.markdown("### 🎤 トレーナーと対話")
                        st.caption("ポートフォリオの状況をふまえて、トレーナーに何でも聞いてください。")

                        portfolio_context = f"""
保有銘柄: {', '.join(df_my['ticker'].tolist()[:10])}
銘柄数: {ticker_count}
投資額: ¥{total_invested:,.0f}
評価額: ¥{total_market:,.0f}
含み損益: ¥{total_unrealized:+,.0f}
確定損益: ¥{total_realized:+,.0f}
総損益: ¥{total_pnl:+,.0f}
セクター偏り: {sec_agg.loc[sec_agg['invested'].idxmax(), 'sector']}
""".strip()

                        from src.ai.analyst import analyze as _analyze

                        chat_key = f"trainer_chat_{my_user_id}"
                        # 初回オープン時にトレーナー挨拶を生成
                        if chat_key not in st.session_state:
                            try:
                                opening = _analyze(
                                    portfolio_context,
                                    "ぼーるくんの今のポートフォリオを見て、特徴・リスク・気づきを3行で伝えてください。"
                                    "親しみやすいトレーナー口調で。断定的な売買推奨は避け、根拠やソースを添える。"
                                )
                            except Exception as e:
                                opening = f"⚠️ 初回コメント生成失敗: {e}"
                            st.session_state[chat_key] = [
                                {"role": "assistant", "content": opening},
                            ]

                        # 過去の会話を表示
                        for msg in st.session_state[chat_key]:
                            with st.chat_message(msg["role"], avatar="🎤" if msg["role"] == "assistant" else "🏐"):
                                st.markdown(msg["content"])

                        # ユーザー入力
                        user_q = st.chat_input("トレーナーに質問する（例: 半導体セクターの見通しは？）")
                        if user_q:
                            # ユーザーメッセージ追加・即表示
                            st.session_state[chat_key].append({"role": "user", "content": user_q})
                            with st.chat_message("user", avatar="🏐"):
                                st.markdown(user_q)

                            # 会話履歴を含めたコンテキスト構築
                            history = st.session_state[chat_key][:-1]  # 最新ユーザーメッセージは除く
                            history_text = "\n".join(
                                f"{'トレーナー' if m['role'] == 'assistant' else 'ぼーるくん'}: {m['content']}"
                                for m in history
                            )
                            full_context = (
                                f"[ぼーるくんのポートフォリオ]\n{portfolio_context}\n\n"
                                f"[これまでの会話]\n{history_text}"
                            )

                            try:
                                with st.spinner("トレーナーが考えています..."):
                                    answer = _analyze(
                                        full_context,
                                        user_q + "\n\n（親しみやすいトレーナー口調で、断定的売買推奨は避け、根拠・ソースを添えて簡潔に。）"
                                    )
                            except Exception as e:
                                answer = f"⚠️ 応答生成失敗: {e}"

                            st.session_state[chat_key].append({"role": "assistant", "content": answer})
                            with st.chat_message("assistant", avatar="🎤"):
                                st.markdown(answer)

                        # 会話リセットボタン
                        if st.session_state.get(chat_key) and len(st.session_state[chat_key]) > 1:
                            if st.button("🔄 会話をリセット", key=f"reset_{chat_key}"):
                                del st.session_state[chat_key]
                                st.rerun()
                except Exception as e:
                    st.error(f"取得エラー: {e}")

    except Exception as e:
        st.error(f"システムエラー: {e}")

if __name__ == "__main__":
    main()
