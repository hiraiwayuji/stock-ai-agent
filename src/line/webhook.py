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

load_dotenv()
log = logging.getLogger(__name__)

app = FastAPI(title="Stock AI Agent - LINE Webhook")

_config = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""))
_parser = WebhookParser(os.environ.get("LINE_CHANNEL_SECRET", ""))


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
        analysis = analyze(context, f"{ticker} の現状分析と短期戦略を教えてください")
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
        return analyze("", question)

    # ---- ポートフォリオ管理 ----
    if cmd == "/buy":
        # /buy <ticker> <単価> <株数> [メモ]
        if len(parts) < 4:
            return "使い方: /buy <ticker> <単価> <株数>\n例: /buy 7203.T 3200 100"
        try:
            ticker = parts[1].upper()
            cost   = float(parts[2])
            qty    = float(parts[3])
            note   = parts[4] if len(parts) > 4 else ""
            add_position(user_id, ticker, qty, cost, note)
            return (
                f"✅ {ticker} 購入登録\n"
                f"  {qty:.0f}株 × ¥{cost:,.0f} = ¥{cost*qty:,.0f}"
            )
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/sell":
        # /sell <ticker> <株数>
        if len(parts) < 3:
            return "使い方: /sell <ticker> <株数>\n例: /sell 7203.T 50"
        try:
            ticker    = parts[1].upper()
            qty       = float(parts[2])
            remaining = reduce_position(user_id, ticker, qty)
            msg = f"✅ {ticker} {qty:.0f}株 売却"
            msg += f"\n残: {remaining:.0f}株" if remaining > 0 else "\n（全売却）"
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
            "【ML・最適化】\n"
            "/ml <ticker> [日数]    ML上昇確率予測\n"
            "/score <ticker>        4軸スコアリング\n"
            "/optimize [top_n]      ウォッチリスト最適化\n"
            "/audit                 既存ウォッチリスト監査\n"
        )

    # フォールバック: 何でもAI相談
    return analyze("", text)


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
            log.info(f"[LINE] user={user_id} text={text!r}")
            try:
                reply_text = _handle_command(user_id, text)
            except Exception as e:
                log.error(f"Command error: {e}")
                reply_text = "⚠️ エラーが発生しました。しばらくしてから再試行してください。"
            _reply(event.reply_token, reply_text)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stock-ai-agent"}
