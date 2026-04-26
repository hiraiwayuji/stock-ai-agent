"""
LINE Webhook受信サーバー (FastAPI)
起動: uvicorn src.line.webhook:app --reload --port 8000
ngrokなどでトンネルしてLINE Developersに登録
"""
import os
import logging
from fastapi import FastAPI, Request, HTTPException
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from dotenv import load_dotenv

from src.ai.analyst import analyze
from src.stock.fetcher import get_price, get_ohlcv
from src.stock.technicals import compute_indicators, get_latest_signals
from src.stock.regime import detect_regime, format_regime_message
from src.stock.pattern_match import find_similar_patterns, format_pattern_message
from src.news.sentiment import compute_divergence, format_divergence_message
from src.db.supabase_client import upsert_watchlist, get_watchlist
from src.db.portfolio import add_position, reduce_position, get_positions
from src.stock.portfolio_analyzer import analyze_portfolio, format_portfolio_message
from src.stock.screener import run_screen, run_custom_screen, format_screen_message, PRESET_SCREENS
from src.stock.backtest import run_backtest, format_backtest_message
from src.stock.strategies import STRATEGY_MAP, STRATEGY_DESCRIPTIONS
from src.stock.ml_predictor import train_and_predict, format_ml_message
from src.stock.watchlist_optimizer import optimize_watchlist, audit_watchlist, format_optimize_message, score_ticker
from src.db.goals import set_goal, get_goal, get_all_goals
from src.stock.goal_tracker import calc_goal_progress, format_goal_message
from src.line.flex_builder import build_goal_flex
from src.line.client import push_flex, push_image
from src.stock.chart_generator import (
    generate_monthly_pnl_chart,
    generate_equity_curve,
    generate_winrate_chart,
)
from src.db.storage import upload_chart, chart_filename
from src.ai.daily_report import build_daily_report, format_daily_report_messages
from src.stock.earnings_calendar import check_earnings_alerts, format_earnings_message
from src.news.ticker_news import scan_ticker_news, format_ticker_news_message
from src.db.groups import (
    create_group, join_by_invite_code, get_group_by_line_id,
    list_user_groups, list_group_members,
    share_trade, post_comment, fetch_timeline, ranking,
)
from src.ai.personal_profile import (
    analyze_user_profile, format_profile_message, save_profile_snapshot,
    build_personal_context, analyze_win_lose_patterns, format_pattern_diff_message
)

load_dotenv()
log = logging.getLogger(__name__)


def _clean_env(name: str) -> str:
    value = os.environ.get(name, "")
    cleaned = value.strip()
    if value != cleaned:
        log.warning("%s had surrounding whitespace; using stripped value", name)
    return cleaned


def _fingerprint(value: str) -> str:
    if not value:
        return "missing"
    return f"len={len(value)} first5={value[:5]} last5={value[-5:]} has_equal={'=' in value}"


app = FastAPI(title="Stock AI Agent - LINE Webhook")

_line_access_token = _clean_env("LINE_CHANNEL_ACCESS_TOKEN")
_line_channel_secret = _clean_env("LINE_CHANNEL_SECRET")
log.info("LINE_CHANNEL_ACCESS_TOKEN fingerprint: %s", _fingerprint(_line_access_token))
log.info("LINE_CHANNEL_SECRET fingerprint: %s", _fingerprint(_line_channel_secret))
_config = Configuration(access_token=_line_access_token)
_parser = WebhookParser(_line_channel_secret)


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(type="text", text=text[:5000])],
        ))


def _handle_command(user_id: str, text: str) -> str:
    """
    コマンド仕様:
      /add <ticker> [指値]    — 監視銘柄追加
      /list                  — 監視銘柄一覧
      /check <ticker>        — テクニカル分析即時確認
      /ask <質問>            — AI投資相談
      それ以外               — AI相談にフォールバック
    """
    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower() if parts else ""

    if cmd == "/add":
        if len(parts) < 2:
            return "使い方: /add <ティッカー> [指値]\n例: /add 7203.T 3000"
        ticker = parts[1].upper()
        alert_price = float(parts[2]) if len(parts) > 2 else None
        upsert_watchlist(user_id, ticker, alert_price=alert_price)
        msg = f"✅ {ticker} を監視リストに追加しました"
        if alert_price:
            msg += f"\n指値: ¥{alert_price:,.0f}"
        return msg

    if cmd == "/list":
        items = get_watchlist(user_id)
        if not items:
            return "監視銘柄はまだ登録されていません。\n/add <ticker> で追加できます。"
        lines = ["📋 監視銘柄リスト"]
        for item in items:
            line = f"• {item['ticker']}"
            if item.get("alert_price"):
                line += f"  指値: ¥{item['alert_price']:,.0f}"
            lines.append(line)
        return "\n".join(lines)

    if cmd == "/check":
        if len(parts) < 2:
            return "使い方: /check <ティッカー>\n例: /check AAPL"
        ticker = parts[1].upper()
        price = get_price(ticker)
        if price is None:
            return f"⚠️ {ticker} の価格取得に失敗しました。ティッカーを確認してください。"
        df = get_ohlcv(ticker)
        df = compute_indicators(df)
        signals = get_latest_signals(df)
        context = (
            f"銘柄: {ticker}  現在値: {price:,.2f}\n"
            f"RSI: {signals['RSI']}  MACD差: {signals['MACD_diff']}\n"
            f"BB位置: {signals['BB_pct']}  MA乖離率: {signals['MA_div_pct']}%"
        )
        p_context = build_personal_context(user_id)
        analysis_context = context
        if p_context:
            analysis_context += f"\n\n{p_context}"
        analysis = analyze(analysis_context, f"{ticker} の現状分析と短期戦略を教えてください")
        return f"📊 {ticker} テクニカル分析\n\n{context}\n\n🤖 AI分析:\n{analysis}"

    if cmd == "/regime":
        if len(parts) < 2:
            return "使い方: /regime <ティッカー>\n例: /regime 7203.T"
        ticker = parts[1].upper()
        result = detect_regime(ticker)
        return format_regime_message(ticker, result)

    if cmd == "/pattern":
        if len(parts) < 2:
            return "使い方: /pattern <ティッカー>\n例: /pattern 7203.T"
        ticker = parts[1].upper()
        matches = find_similar_patterns(ticker)
        return format_pattern_message(ticker, matches)

    if cmd == "/divergence":
        if len(parts) < 2:
            return "使い方: /divergence <ティッカー>\n例: /divergence 7203.T"
        ticker = parts[1].upper()
        result = compute_divergence(ticker)
        return format_divergence_message(result)

    if cmd == "/ask":
        question = " ".join(parts[1:]) if len(parts) > 1 else text
        p_context = build_personal_context(user_id)
        return analyze(p_context, question)

    # ---- ポートフォリオ管理 ----
    if cmd == "/buy":
        # /buy <ticker> <単価> <株数> [メモ...]
        full_parts = text.strip().split(maxsplit=4)
        if len(full_parts) < 4:
            return "使い方: /buy <ticker> <単価> <株数>\n例: /buy 7203.T 3200 100"
        try:
            ticker = full_parts[1].upper()
            cost   = float(full_parts[2])
            qty    = float(full_parts[3])
            note   = full_parts[4] if len(full_parts) > 4 else ""
            add_position(user_id, ticker, qty, cost, note)
            msg = (
                f"✅ {ticker} 購入登録\n"
                f"  {qty:.0f}株 × ¥{cost:,.0f} = ¥{cost*qty:,.0f}"
            )
            try:
                gs = list_user_groups(user_id)
                if gs:
                    for g in gs:
                        share_trade(g.id, user_id, ticker, "buy", qty, cost, None, f"自動共有: {note}" if note else "自動共有")
                    msg += f"\n📣 {len(gs)}グループに共有"
            except Exception as e:
                log.warning(f"Auto share error: {e}")
            return msg
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/sell":
        # /sell <ticker> <株数> [単価] [メモ...]
        full_parts = text.strip().split(maxsplit=4)
        if len(full_parts) < 3:
            return "使い方: /sell <ticker> <株数> [単価]\n例: /sell 7203.T 50 3500"
        try:
            ticker    = full_parts[1].upper()
            qty       = float(full_parts[2])
            sell_price = float(full_parts[3]) if len(full_parts) > 3 else None
            note       = full_parts[4] if len(full_parts) > 4 else ""
            remaining, exec_price, pnl = reduce_position(user_id, ticker, qty, sell_price)
            msg = f"✅ {ticker} {qty:.0f}株 売却 @¥{exec_price:,.0f}"
            if pnl is not None:
                msg += f"\n実現損益: ¥{pnl:+,.0f}"
            msg += f"\n残: {remaining:.0f}株" if remaining > 0 else "\n（全売却）"
            try:
                gs = list_user_groups(user_id)
                if gs:
                    for g in gs:
                        share_trade(
                            g.id, user_id, ticker, "sell", qty,
                            exec_price, pnl, note or "自動共有",
                        )
                    msg += f"\n📣 {len(gs)}グループに共有"
            except Exception as e:
                log.warning(f"Auto share error: {e}")
            return msg
        except Exception as e:
            return f"⚠️ {e}"

    if cmd == "/port":
        summary = analyze_portfolio(user_id)
        return format_portfolio_message(summary)

    if cmd == "/port ai":
        summary = analyze_portfolio(user_id)
        port_text = format_portfolio_message(summary)
        ai_advice = analyze(port_text, "このポートフォリオのリスクと改善提案をください")
        return f"{port_text}\n\n🤖 AI提案:\n{ai_advice}"

    # ---- スクリーナー ----
    if cmd == "/screen":
        preset = parts[1].lower() if len(parts) > 1 else "oversold"
        if preset == "help":
            lines = ["📋 スクリーンプリセット一覧"]
            for k, v in PRESET_SCREENS.items():
                lines.append(f"  {k}: {v}")
            return "\n".join(lines)
        results = run_screen(preset)
        return format_screen_message(preset, results)

    if cmd == "/screen_custom":
        # /screen_custom rsi<30 ma<-5 vol>2
        # 簡易パーサー: キー<数値 / キー>数値
        import re
        rsi_max = rsi_min = ma_div_max = vol_min = None
        for token in parts[1:]:
            m = re.match(r"(rsi|ma|vol)([<>])(-?[\d.]+)", token)
            if not m:
                continue
            key, op, val = m.group(1), m.group(2), float(m.group(3))
            if key == "rsi"  and op == "<": rsi_max     = val
            if key == "rsi"  and op == ">": rsi_min     = val
            if key == "ma"   and op == "<": ma_div_max  = val
            if key == "vol"  and op == ">": vol_min     = val
        results = run_custom_screen(rsi_max, rsi_min, ma_div_max, vol_min)
        label = " ".join(parts[1:]) or "カスタム"
        return format_screen_message(label, results)

    if cmd == "/backtest":
        # /backtest <ticker> <strategy> [period]
        # /backtest <ticker> compare
        if len(parts) < 2:
            lines = ["使い方: /backtest <ticker> <戦略> [期間]", "例: /backtest 7203.T golden 2y", ""]
            lines += [f"  {k}: {v}" for k, v in STRATEGY_DESCRIPTIONS.items()]
            return "\n".join(lines)

        ticker = parts[1].upper()
        strat_key = parts[2].lower() if len(parts) > 2 else "golden"
        period    = parts[3] if len(parts) > 3 else "2y"

        # 全戦略比較
        if strat_key == "compare":
            df = get_ohlcv(ticker, period=period)
            if df.empty:
                return f"⚠️ {ticker} のデータ取得失敗"
            df = compute_indicators(df)
            lines = [f"📊 {ticker} 全戦略比較 ({period})"]
            for key, strat in STRATEGY_MAP.items():
                r = run_backtest(df, strat, ticker)
                icon = "📈" if r.total_return_pct >= 0 else "📉"
                lines.append(
                    f"{icon} {key}: {r.total_return_pct:+.1f}%  "
                    f"シャープ{r.sharpe_ratio:.2f}  DD{r.max_drawdown_pct:.1f}%  "
                    f"勝率{r.win_rate_pct:.0f}%"
                )
            return "\n".join(lines)

        if strat_key not in STRATEGY_MAP:
            return f"不明な戦略: {strat_key}\n利用可能: {', '.join(STRATEGY_MAP.keys())}"

        df = get_ohlcv(ticker, period=period)
        if df.empty:
            return f"⚠️ {ticker} のデータ取得失敗"
        df = compute_indicators(df)
        result = run_backtest(df, STRATEGY_MAP[strat_key], ticker)
        bt_text = format_backtest_message(result)

        # AI による戦略評価
        ai_eval = analyze(
            bt_text,
            f"{ticker} の {strat_key} 戦略バックテスト結果を評価し、改善案を提案してください"
        )
        return f"{bt_text}\n\n🤖 AI評価:\n{ai_eval}"

    if cmd == "/ml":
        # /ml <ticker> [forward_days]
        if len(parts) < 2:
            return "使い方: /ml <ticker> [日数]\n例: /ml 7203.T 5"
        ticker = parts[1].upper()
        fwd    = int(parts[2]) if len(parts) > 2 else 5
        try:
            pred = train_and_predict(ticker, forward_days=fwd)
            ml_text = format_ml_message(pred)
            ai_note = analyze(
                ml_text,
                f"{ticker} のML予測を踏まえた具体的な売買判断を教えてください"
            )
            return f"{ml_text}\n\n🤖 AI判断:\n{ai_note}"
        except Exception as e:
            return f"⚠️ ML予測失敗: {e}"

    if cmd == "/optimize":
        # /optimize [top_n]
        top_n = int(parts[1]) if len(parts) > 1 else 5
        try:
            scores = optimize_watchlist(top_n=top_n)
            return format_optimize_message(scores)
        except Exception as e:
            return f"⚠️ 最適化失敗: {e}"

    if cmd == "/score":
        # /score <ticker>  — 単一銘柄の4軸スコア
        if len(parts) < 2:
            return "使い方: /score <ticker>\n例: /score 7203.T"
        ticker = parts[1].upper()
        try:
            s = score_ticker(ticker)
            rec_icon = {"強力買い推奨": "🔥", "買い推奨": "✅", "様子見": "🔶", "除外推奨": "❌"}.get(s.recommendation, "")
            return (
                f"{rec_icon} {ticker} 総合スコア: {s.total_score:.0f}/100\n"
                f"  ML:         {s.ml_score:.0f}/25\n"
                f"  レジーム:   {s.regime_score:.0f}/25\n"
                f"  パターン:   {s.pattern_score:.0f}/25\n"
                f"  テクニカル: {s.technical_score:.0f}/25\n\n"
                f"判定: {s.recommendation}\n"
                f"根拠: {' / '.join(s.reasons[:3])}"
            )
        except Exception as e:
            return f"⚠️ スコア計算失敗: {e}"

    if cmd == "/audit":
        # 既存ウォッチリストを監査
        items = get_watchlist(user_id)
        if not items:
            return "監視銘柄が登録されていません。"
        tickers = [item["ticker"] for item in items]
        try:
            results = audit_watchlist(tickers)
            lines = ["🔍 ウォッチリスト監査結果"]
            for s in results:
                icon = {"強力買い推奨": "🔥", "買い推奨": "✅", "様子見": "🔶", "除外推奨": "❌"}.get(s.recommendation, "")
                lines.append(f"{icon} {s.ticker}: {s.total_score:.0f}点 — {s.recommendation}")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ 監査失敗: {e}"

    if cmd == "/report":
        # AI 総合デイリーレポートをオンデマンド生成
        try:
            from src.line.client import push_text as _push
            report = build_daily_report(user_id)
            msgs   = format_daily_report_messages(report)
            for msg in msgs[1:]:   # 1通目はreplyで返すので2通目以降をpush
                _push(user_id, msg)
            return msgs[0] if msgs else "レポート生成失敗"
        except Exception as e:
            return f"⚠️ レポート生成失敗: {e}"

    if cmd == "/earnings":
        # 保有・監視銘柄の決算カレンダー確認
        from src.db.portfolio import get_positions
        wl  = [i["ticker"] for i in get_watchlist(user_id)]
        hld = [p["ticker"] for p in get_positions(user_id)]
        if not wl and not hld:
            return "監視・保有銘柄がありません。\n/add または /buy で登録してください。"
        try:
            alerts = check_earnings_alerts(wl, hld, alert_days=list(range(0, 31)))
            if not alerts:
                return "今後30日以内に決算予定の銘柄はありません。"
            return format_earnings_message(alerts)
        except Exception as e:
            return f"⚠️ 決算データ取得失敗: {e}"

    if cmd == "/news":
        # /news <ticker>  — 銘柄個別ニュース
        if len(parts) < 2:
            return "使い方: /news <ticker>\n例: /news 7203.T"
        ticker = parts[1].upper()
        try:
            items = scan_ticker_news([ticker], importance_threshold=0.4)
            if not items:
                return f"{ticker} の重要ニュースは見つかりませんでした。"
            return format_ticker_news_message(items)
        except Exception as e:
            return f"⚠️ ニュース取得失敗: {e}"

    if cmd == "/chart":
        sub = parts[1].lower() if len(parts) > 1 else "monthly"
        chart_map = {
            "monthly":  (generate_monthly_pnl_chart, "月次損益グラフ",   "monthly_pnl"),
            "equity":   (generate_equity_curve,       "エクイティカーブ", "equity"),
            "winrate":  (generate_winrate_chart,       "勝率チャート",     "winrate"),
        }
        if sub not in chart_map:
            return "使い方: /chart monthly|equity|winrate\n  monthly — 月次損益棒グラフ\n  equity  — 累計損益カーブ\n  winrate — 勝率ドーナツ"
        gen_fn, alt, ctype = chart_map[sub]
        try:
            png   = gen_fn(user_id)
            fname = chart_filename(user_id, ctype)
            url   = upload_chart(fname, png)
            push_image(user_id, url)
            return f"📊 {alt} を送信しました"
        except Exception as e:
            return f"⚠️ グラフ生成失敗: {e}"

    if cmd == "/goal":
        from datetime import datetime, timezone, timedelta
        JST   = timezone(timedelta(hours=9))
        now   = datetime.now(JST)
        year  = now.year
        month = now.month

        sub = parts[1].lower() if len(parts) > 1 else "show"

        if sub == "set":
            # /goal set monthly|yearly <金額> [勝率] [取引数]
            if len(parts) < 4:
                return (
                    "使い方:\n"
                    "/goal set monthly <金額> [勝率%] [取引数]\n"
                    "/goal set yearly  <金額> [勝率%] [取引数]\n"
                    "例: /goal set monthly 50000 60 10"
                )
            try:
                gtype   = parts[2].lower()
                tpnl    = int(float(parts[3]))
                twin    = float(parts[4]) if len(parts) > 4 else None
                ttrades = int(parts[5])   if len(parts) > 5 else None
                m       = month if gtype == "monthly" else None
                set_goal(user_id, gtype, year, m, tpnl, twin, ttrades)
                label = f"{year}年{month}月" if gtype == "monthly" else f"{year}年間"
                msg = f"✅ {label}目標設定完了！\n目標損益: ¥{tpnl:+,.0f}"
                if twin:    msg += f"\n目標勝率: {twin}%"
                if ttrades: msg += f"\n目標取引数: {ttrades}回"
                return msg
            except Exception as e:
                return f"⚠️ 設定エラー: {e}"

        elif sub == "yearly":
            p = calc_goal_progress(user_id, "yearly", year)
            if not p:
                return f"年間目標が未設定です。\n/goal set yearly <金額> で設定してください。"
            push_flex(user_id, f"{year}年間 目標進捗", build_goal_flex(p))
            return format_goal_message(p)

        elif sub == "history":
            goals = get_all_goals(user_id)
            if not goals:
                return "目標履歴がありません。"
            lines = ["📋 目標設定履歴"]
            for g in goals:
                label = f"{g['year']}年{g['month']}月" if g["goal_type"] == "monthly" else f"{g['year']}年間"
                lines.append(f"• {label}: ¥{float(g['target_pnl']):+,.0f}")
            return "\n".join(lines)

        else:  # show / monthly
            p = calc_goal_progress(user_id, "monthly", year, month)
            if not p:
                return f"{year}年{month}月の目標が未設定です。\n/goal set monthly <金額> で設定してください。"
            push_flex(user_id, f"{year}年{month}月 目標進捗", build_goal_flex(p))
            return format_goal_message(p)

    # ===== グループ共有 (Step11) =====
    # /group create <名前>     — 新規グループ作成（仮想グループ）
    # /group join <招待コード> — 既存グループに参加
    # /group list              — 所属グループ一覧
    # /group members           — メンバー一覧（最初のグループ）
    # /share <ticker> <side> <qty> <price> [pnl] [コメント]
    # /wall [件数]             — in-app タイムライン閲覧
    # /comment <本文>          — タイムラインにコメント
    # /ranking [日数]          — グループ内損益ランキング
    if cmd == "/group":
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub == "create":
            if len(parts) < 3:
                return "使い方: /group create <グループ名>"
            g = create_group(parts[2], user_id)
            return (f"✅ グループ「{g.name}」を作成\n"
                    f"招待コード: {g.invite_code}\n"
                    f"メンバーに共有してください。\n"
                    f"参加は /group join {g.invite_code}")
        if sub == "join":
            if len(parts) < 3:
                return "使い方: /group join <招待コード>"
            g = join_by_invite_code(parts[2], user_id)
            if not g:
                return "⚠️ 招待コードが見つかりません"
            return f"✅ 「{g.name}」に参加しました"
        if sub == "list":
            gs = list_user_groups(user_id)
            if not gs:
                return "所属グループがありません。\n/group create <名前> で作成できます。"
            return "👥 所属グループ\n" + "\n".join(
                f"• {g.name} (コード: {g.invite_code})" for g in gs
            )
        if sub == "members":
            gs = list_user_groups(user_id)
            if not gs:
                return "所属グループがありません。"
            members = list_group_members(gs[0].id)
            lines = [f"👥 {gs[0].name} メンバー ({len(members)}人)"]
            for m in members:
                lines.append(f"• {m.get('nickname') or m['user_id'][:8]}")
            return "\n".join(lines)
        return "使い方: /group create|join|list|members"

    if cmd == "/share":
        if len(parts) < 5:
            return "使い方: /share <ticker> <buy|sell> <株数> <価格> [pnl] [コメント]"
        gs = list_user_groups(user_id)
        if not gs:
            return "⚠️ グループ未所属。/group create または /group join してください"
        try:
            ticker = parts[1].upper()
            side   = parts[2].lower()
            qty    = float(parts[3])
            price  = float(parts[4])
            pnl    = float(parts[5]) if len(parts) > 5 else None
            cmt    = parts[6] if len(parts) > 6 else None
            share_trade(gs[0].id, user_id, ticker, side, qty, price, pnl, cmt)
            return f"📣 {gs[0].name} に売買共有しました\n{side.upper()} {ticker} {qty}株 @¥{price:,.0f}"
        except Exception as e:
            return f"⚠️ 共有エラー: {e}"

    if cmd == "/wall":
        gs = list_user_groups(user_id)
        if not gs:
            return "⚠️ グループ未所属"
        limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        msgs = fetch_timeline(gs[0].id, limit=limit)
        if not msgs:
            return f"📜 {gs[0].name} のタイムラインは空です"
        lines = [f"📜 {gs[0].name} タイムライン"]
        for m in msgs:
            icon = {"trade": "💹", "comment": "💬", "system": "🔔"}.get(m["kind"], "•")
            who  = m["user_id"][:6]
            lines.append(f"{icon} [{who}] {m.get('body','')}")
        return "\n".join(lines)

    if cmd == "/comment":
        if len(parts) < 2:
            return "使い方: /comment <本文>"
        gs = list_user_groups(user_id)
        if not gs:
            return "⚠️ グループ未所属"
        body = text.split(maxsplit=1)[1]
        post_comment(gs[0].id, user_id, body)
        return "💬 コメント投稿しました"

    if cmd == "/ranking":
        gs = list_user_groups(user_id)
        if not gs:
            return "⚠️ グループ未所属"
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
        rows = ranking(gs[0].id, period_days=days)
        if not rows:
            return f"🏁 {gs[0].name} 直近{days}日の共有売買はまだありません"
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"🏆 {gs[0].name} ランキング (直近{days}日)"]
        for i, r in enumerate(rows[:10]):
            m = medals[i] if i < 3 else f"{i+1}."
            lines.append(
                f"{m} {r['user_id'][:6]}  ¥{r['pnl']:+,.0f}  "
                f"{r['trades']}回 / 勝率{r['winrate']:.0f}%"
            )
        return "\n".join(lines)

    if cmd == "/profile":
        sub = parts[1].lower() if len(parts) > 1 else "show"
        if sub == "show":
            p = analyze_user_profile(user_id)
            return format_profile_message(p)
        if sub == "save":
            # 手動スナップショット（デバッグ用）
            p = analyze_user_profile(user_id)
            save_profile_snapshot(p)
            return "✅ プロファイルを保存しました"
        if sub == "strength":
            diff = analyze_win_lose_patterns(user_id)
            if not diff.get("win") or diff["win"]["count"] < 5:
                return "勝ち取引データが不足しています（最低5件必要）"
            return format_pattern_diff_message(diff, strength=True)
        if sub == "weakness":
            diff = analyze_win_lose_patterns(user_id)
            if not diff.get("lose") or diff["lose"]["count"] < 5:
                return "負け取引データが不足しています（最低5件必要）"
            return format_pattern_diff_message(diff, strength=False)
        return "使い方: /profile [show|save|strength|weakness]"

    if cmd == "/help":
        return (
            "📖 コマンド一覧\n\n"
            "【分析】\n"
            "/check <ticker>      テクニカル+AI分析\n"
            "/regime <ticker>     相場レジーム判定\n"
            "/pattern <ticker>    類似パターン検索\n"
            "/divergence <ticker> センチメント乖離\n"
            "/ask <質問>          AI自由相談\n\n"
            "【監視】\n"
            "/add <ticker> [指値] 監視登録\n"
            "/list                監視一覧\n\n"
            "【ポートフォリオ】\n"
            "/buy <ticker> <単価> <株数>\n"
            "/sell <ticker> <株数>\n"
            "/port                損益サマリー\n"
            "/port ai             AI改善提案付き\n\n"
            "【スクリーナー】\n"
            "/screen <preset>     銘柄スクリーン\n"
            "/screen help         プリセット一覧\n"
            "/screen_custom rsi<30 ma<-5 vol>2\n\n"
            "【バックテスト】\n"
            "/backtest <ticker> <戦略> [期間]\n"
            "  戦略: golden rsi bb macd\n"
            "/backtest <ticker> compare  全戦略比較\n\n"
            "【総合レポート・ニュース】\n"
            "/report              AI総合投資デイリーレポート\n"
            "/earnings            保有・監視銘柄の決算カレンダー\n"
            "/news <ticker>       銘柄個別ニュース重要度分析\n\n"
            "【グラフ】\n"
            "/chart monthly   月次損益棒グラフ\n"
            "/chart equity    累計損益カーブ\n"
            "/chart winrate   勝率ドーナツ+統計\n\n"
            "【目標管理】\n"
            "/goal                     今月の目標進捗\n"
            "/goal yearly              年間目標進捗\n"
            "/goal set monthly <金額>  今月目標設定\n"
            "/goal set yearly  <金額>  年間目標設定\n"
            "/goal history             目標設定履歴\n\n"
            "【ML・最適化】\n"
            "/ml <ticker> [日数]    ML上昇確率予測\n"
            "/score <ticker>        4軸スコアリング\n"
            "/optimize [top_n]      ウォッチリスト最適化\n"
            "/audit                 既存ウォッチリスト監査\n\n"
            "【個人AI秘書】\n"
            "/profile               あなたの投資プロファイル\n"
            "/profile save          スナップショット保存\n"
            "/profile strength      得意パターンTOP3\n"
            "/profile weakness      苦手パターン + AI改善提案\n\n"
            "【グループ共有】\n"
            "/group create <名前>   グループ作成\n"
            "/group join <コード>   招待コードで参加\n"
            "/group list            所属グループ一覧\n"
            "/share <t> <side> <qty> <price> [pnl] [コメント]\n"
            "                       売買を共有\n"
            "/wall [件数]           タイムライン閲覧\n"
            "/comment <本文>        コメント投稿\n"
            "/ranking [日数]        グループ損益ランキング\n"
        )

    # フォールバック: 何でもAI相談
    return analyze("", text)


def _handle_group_command(event, text: str) -> str:
    """
    LINE グループチャット用ハンドラ
    方針: 個人のAI秘書機能はここでは動かさない。
          大きなお知らせ（ランキング・グループ登録・重大アラート）だけ返し、
          その他の売買共有・コメントは in-app (/wall /share /comment) に誘導する。
    """
    line_group_id = getattr(event.source, "group_id", None)
    user_id = event.source.user_id
    if not line_group_id:
        return ""

    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lower() if parts else ""

    # グループを Supabase に同期（初回発話時に自動登録）
    g = get_group_by_line_id(line_group_id)
    if g is None and cmd in ("/group", "/register", "/ranking"):
        name = parts[2] if cmd == "/register" and len(parts) > 2 else "LINEグループ"
        g = create_group(name=name, owner_id=user_id, line_group_id=line_group_id)
        return (f"✅ このLINEグループを「{g.name}」として登録しました\n"
                f"招待コード: {g.invite_code}\n"
                f"個別の売買共有・コメントはツール内チャット (/wall /share /comment) を\n"
                f"個人メッセージで送ってください。")

    if g is None:
        # 未登録グループでの一般発話は静かに無視（ノイズ防止）
        return ""

    if cmd == "/ranking":
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
        rows = ranking(g.id, period_days=days)
        if not rows:
            return f"🏁 直近{days}日の共有売買はまだありません"
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"🏆 {g.name} ランキング (直近{days}日)"]
        for i, r in enumerate(rows[:10]):
            m = medals[i] if i < 3 else f"{i+1}."
            lines.append(
                f"{m} {r['user_id'][:6]}  ¥{r['pnl']:+,.0f}  "
                f"{r['trades']}回 / 勝率{r['winrate']:.0f}%"
            )
        return "\n".join(lines)

    if cmd == "/help":
        return (
            "👥 グループで使えるのは「大きなお知らせ」系のみです:\n"
            "/ranking [日数]   損益ランキング\n"
            "/register <名前>  このグループの表示名変更\n\n"
            "個別の売買共有・コメント・分析は個人チャットで:\n"
            "/share /wall /comment /check /port など"
        )

    # それ以外はノイズ削減のため無応答
    return ""


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = _parser.parse(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            user_id = event.source.user_id
            text = event.message.text
            src_type = getattr(event.source, "type", "user")
            log.info(f"[LINE] src={src_type} user={user_id} text={text!r}")
            try:
                if src_type == "group":
                    reply_text = _handle_group_command(event, text)
                else:
                    reply_text = _handle_command(user_id, text)
            except Exception as e:
                log.error(f"Command error: {e}")
                reply_text = "⚠️ エラーが発生しました。しばらくしてから再試行してください。"
            if reply_text:
                _reply(event.reply_token, reply_text)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stock-ai-agent"}
