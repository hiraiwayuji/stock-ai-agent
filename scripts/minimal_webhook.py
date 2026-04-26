"""
Minimal LINE Webhook for Phase B (group registration).

起動方法:
    uvicorn scripts.minimal_webhook:app --port 8000
"""

import logging
import os

from dotenv import load_dotenv

# .env は最初にロード
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src.db.groups import get_group_by_line_id, create_group, ranking, list_user_groups, share_trade
from src.db.portfolio import add_position, reduce_position, get_positions
from src.db.supabase_client import upsert_watchlist, get_watchlist, get_client
from src.ai.analyst import analyze

logging.basicConfig(level=logging.INFO)
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


app = FastAPI(title="Minimal LINE Webhook (Phase B: group registration)")
_line_access_token = _clean_env("LINE_CHANNEL_ACCESS_TOKEN")
_line_channel_secret = _clean_env("LINE_CHANNEL_SECRET")
log.info("LINE_CHANNEL_ACCESS_TOKEN fingerprint: %s", _fingerprint(_line_access_token))
log.info("LINE_CHANNEL_SECRET fingerprint: %s", _fingerprint(_line_channel_secret))
_config = Configuration(access_token=_line_access_token)
_parser = WebhookParser(_line_channel_secret)

# 個人チャットの会話履歴（プロセスメモリ。再起動で消える）
# 1ユーザー最大 20 メッセージ（=10往復）まで保持
_chat_history: dict[str, list[dict]] = {}
# グループチャットの会話履歴（group_id 単位、メンション時のみ）
_group_chat_history: dict[str, list[dict]] = {}
_MAX_HISTORY = 20

# Bot 自身の userId キャッシュ（メンション判定用）
_bot_user_id_cache: str | None = None


def _get_bot_user_id() -> str | None:
    """Bot 自身の userId を取得（初回 API call、以降キャッシュ）"""
    global _bot_user_id_cache
    if _bot_user_id_cache is not None:
        return _bot_user_id_cache
    try:
        with ApiClient(_config) as api_client:
            info = MessagingApi(api_client).get_bot_info()
            _bot_user_id_cache = getattr(info, "user_id", None) or getattr(info, "userId", None)
            log.info(f"Bot userId fetched: {_bot_user_id_cache[:8] if _bot_user_id_cache else 'None'}...")
            return _bot_user_id_cache
    except Exception as e:
        log.warning(f"get_bot_info failed: {e}")
        return None


def _is_bot_mentioned(event) -> bool:
    """LINE のメンション情報から Bot が呼ばれたかを判定。"""
    try:
        message = event.message
        mention = getattr(message, "mention", None)
        if mention is None:
            return False
        bot_id = _get_bot_user_id()
        if bot_id is None:
            return False
        for m in (mention.mentionees or []):
            mid = getattr(m, "user_id", None) or getattr(m, "userId", None)
            if mid == bot_id:
                return True
    except Exception as e:
        log.warning(f"_is_bot_mentioned failed: {e}")
    return False


def _ask_group_with_history(group_id: str, question: str) -> str:
    """グループ単位の会話履歴を踏まえて AI に質問。"""
    history = _group_chat_history.setdefault(group_id, [])
    history_text = "\n".join(
        f"{'トレーナー' if m['role'] == 'assistant' else 'メンバー'}: {m['content']}"
        for m in history
    )
    context = f"[このグループでのこれまでの会話]\n{history_text}" if history else ""
    try:
        response = analyze(
            context,
            question + "\n\n（このグループ全員が見ているので、丁寧で公開向けの口調で。断定的売買推奨は避け、根拠やソースを添える。）"
        ) or ""
    except Exception as e:
        log.error(f"_ask_group_with_history failed: {e}")
        return f"⚠️ AI応答生成失敗: {e}"

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": response})
    if len(history) > _MAX_HISTORY:
        del history[:-_MAX_HISTORY]
    return response[:5000] if response else "⚠️ AI応答が空でした。"


def _ask_with_history(user_id: str, question: str) -> str:
    """会話履歴を踏まえて AI に質問。応答を返し、履歴を更新。"""
    history = _chat_history.setdefault(user_id, [])
    history_text = "\n".join(
        f"{'トレーナー' if m['role'] == 'assistant' else 'ぼーるくん'}: {m['content']}"
        for m in history
    )
    context = f"[これまでの会話]\n{history_text}" if history else ""
    try:
        response = analyze(context, question) or ""
    except Exception as e:
        log.error(f"_ask_with_history failed: {e}")
        return f"⚠️ AI応答生成失敗: {e}"

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": response})
    if len(history) > _MAX_HISTORY:
        del history[:-_MAX_HISTORY]
    return response[:5000] if response else "⚠️ AI応答が空でした。"


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(type="text", text=text[:5000])],
            )
        )


def _handle_group_command(event, user_id, line_group_id, text, cmd, parts, reply_token) -> str:
    if cmd == "/register":
        name = parts[1].strip() if len(parts) > 1 else "LINEグループ"
        existing = get_group_by_line_id(line_group_id)
        if existing:
            return f"✅ このグループは既に「{existing.name}」として登録済みです\n招待コード: {existing.invite_code}"
        try:
            g = create_group(name=name, owner_id=user_id, line_group_id=line_group_id)
            return f"✅ このLINEグループを「{g.name}」として登録しました\n招待コード: {g.invite_code}\nSupabase に line_group_id を保存しました"
        except Exception as e:
            log.error(f"create_group failed: {e}")
            return f"⚠️ 登録エラー: {e}"

    if cmd == "/ranking":
        g = get_group_by_line_id(line_group_id)
        if g is None:
            return "⚠️ このグループは未登録です。/register <グループ名> で登録してください"
        try:
            days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
        except Exception:
            days = 30
        rows = ranking(g.id, period_days=days)
        if not rows:
            return f"🏁 {g.name} 直近{days}日の共有売買はまだありません"
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
            "📖 グループで使えるコマンド\n"
            "  /register <グループ名>  グループ登録\n"
            "  /ranking [日数]         損益ランキング\n"
            "  /reset                  グループ会話履歴リセット\n"
            "  /help                   このヘルプ\n\n"
            "💬 AI相談は @株ボールシステム をメンションしてください\n"
            "  例: @株ボールシステム トヨタの今後どう？\n\n"
            "個別の売買登録は個人チャットで行ってください。"
        )

    if cmd == "/reset":
        _group_chat_history.pop(line_group_id, None)
        return "🔄 このグループの会話履歴をリセットしました。"

    # @株ボールシステム メンション時のみ AI 応答
    if _is_bot_mentioned(event):
        # メンション部分を含めたまま渡す（AI に「呼ばれた」文脈を伝えるため）
        return _ask_group_with_history(line_group_id, text)

    return ""  # ノイズ削減のため無応答


def _handle_personal_command(user_id, text, cmd, parts, reply_token) -> str:
    if cmd == "/myid":
        return f"あなたのuser_id:\n{user_id}"
    
    if cmd == "/ask":
        if len(parts) < 2:
            return "使い方: /ask <質問>\n例: /ask 半導体セクターの見通しは？"
        question = text.split(maxsplit=1)[1]
        return _ask_with_history(user_id, question)

    if cmd == "/reset":
        _chat_history.pop(user_id, None)
        return "🔄 会話履歴をリセットしました。新しい質問からどうぞ。"
    
    if cmd == "/buy":
        full_parts = text.strip().split(maxsplit=4)
        if len(full_parts) < 4:
            return "使い方: /buy <ticker> <単価> <株数> [メモ]\n例: /buy NVDA 130 10"
        try:
            ticker = full_parts[1].upper()
            cost = float(full_parts[2])
            qty = float(full_parts[3])
            note = full_parts[4] if len(full_parts) > 4 else ""
            add_position(user_id, ticker, qty, cost, note)
            msg = (
                f"✅ {ticker} 購入登録\n"
                f"  {qty:.0f}株 × ¥{cost:,.0f} = ¥{qty*cost:,.0f}"
            )
            # 自動グループ共有
            try:
                gs = list_user_groups(user_id)
                if gs:
                    for g in gs:
                        share_trade(
                            g.id, user_id, ticker, "buy", qty, cost, None,
                            f"自動共有: {note}" if note else "自動共有",
                        )
                    msg += f"\n📣 {len(gs)}グループに共有"
            except Exception as e:
                log.warning(f"auto share error: {e}")
            return msg
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/sell":
        full_parts = text.strip().split(maxsplit=4)
        if len(full_parts) < 3:
            return "使い方: /sell <ticker> <株数> [単価]\n例: /sell NVDA 5 145"
        try:
            ticker = full_parts[1].upper()
            qty = float(full_parts[2])
            sell_price = float(full_parts[3]) if len(full_parts) > 3 else None
            note = full_parts[4] if len(full_parts) > 4 else ""
            remaining, exec_price, pnl = reduce_position(user_id, ticker, qty, sell_price)
            msg = f"✅ {ticker} {qty:.0f}株 売却 @¥{exec_price:,.0f}"
            if pnl is not None:
                msg += f"\n実現損益: ¥{pnl:+,.0f}"
            msg += f"\n残: {remaining:.0f}株" if remaining > 0 else "\n（全売却）"
            # 自動グループ共有
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
                log.warning(f"auto share error: {e}")
            return msg
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/port":
        try:
            positions = get_positions(user_id)
            if not positions:
                return "📊 保有銘柄なし\n/buy <ticker> <単価> <株数> で登録できます。"
            lines = ["📊 あなたの保有銘柄"]
            total_invested = 0.0
            total_realized = 0.0
            for p in positions:
                ticker = p.get("ticker", "")
                qty = float(p.get("qty") or 0)
                avg_cost = float(p.get("avg_cost") or 0)
                realized_pnl = float(p.get("realized_pnl") or 0)
                invested = qty * avg_cost
                total_invested += invested
                total_realized += realized_pnl
                lines.append(
                    f"• {ticker}: {qty:.0f}株 @¥{avg_cost:,.0f}"
                    f" (投資¥{invested:,.0f}, 確定損益¥{realized_pnl:+,.0f})"
                )
            lines.append("")
            lines.append(f"合計投資額: ¥{total_invested:,.0f}")
            lines.append(f"確定損益合計: ¥{total_realized:+,.0f}")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/add":
        full_parts = text.strip().split()
        if len(full_parts) < 2:
            return (
                "使い方: /add <ticker> [指値] [変動率%]\n"
                "例:\n"
                "  /add NVDA            (デフォルト: 前日比±5%変動でアラート)\n"
                "  /add NVDA 140        (価格140に接近でアラート)\n"
                "  /add NVDA 140 3      (140接近 or ±3%変動)"
            )
        try:
            ticker = full_parts[1].upper()
            alert_price = float(full_parts[2]) if len(full_parts) > 2 else None
            alert_pct = float(full_parts[3]) if len(full_parts) > 3 else None
            upsert_watchlist(user_id, ticker, alert_price=alert_price, alert_pct=alert_pct)
            msg = f"✅ {ticker} を監視リストに追加しました"
            if alert_price:
                msg += f"\n  指値: ¥{alert_price:,.2f}"
            if alert_pct:
                msg += f"\n  変動率: ±{alert_pct}%"
            if not alert_price and not alert_pct:
                msg += "\n  (デフォルト ±5% でアラート)"
            return msg
        except ValueError:
            return "⚠️ 数値が不正です。/add <ticker> [指値] [変動率%]"
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/list":
        try:
            items = get_watchlist(user_id)
            if not items:
                return (
                    "📋 監視銘柄はまだ登録されていません。\n"
                    "/add <ticker> [指値] で追加できます。"
                )
            lines = ["📋 監視銘柄リスト"]
            for item in items:
                ticker = item.get("ticker", "?")
                line = f"• {ticker}"
                ap = item.get("alert_price")
                pp = item.get("alert_pct")
                if ap:
                    line += f"  指値:¥{float(ap):,.2f}"
                if pp:
                    line += f"  ±{float(pp):.1f}%"
                lines.append(line)
            lines.append("")
            lines.append("削除: /unwatch <ticker>")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/unwatch":
        full_parts = text.strip().split()
        if len(full_parts) < 2:
            return "使い方: /unwatch <ticker>\n例: /unwatch NVDA"
        try:
            ticker = full_parts[1].upper()
            client = get_client()
            client.table("watchlist").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
            return f"✅ {ticker} を監視リストから削除しました"
        except Exception as e:
            return f"⚠️ エラー: {e}"

    if cmd == "/help":
        return (
            "📖 個人で使えるコマンド\n"
            "  /myid                      あなたのuser_id表示\n"
            "  /ask <質問>                AI投資相談（会話履歴あり）\n"
            "  /reset                     会話履歴をリセット\n"
            "  ※ コマンドなしの普通の文章でもAIが応答します\n"
            "\n"
            "【監視・アラート】\n"
            "  /add <t> [指値] [変動率%]  監視登録\n"
            "  /list                      監視一覧\n"
            "  /unwatch <t>               監視解除\n"
            "\n"
            "【ポートフォリオ】\n"
            "  /buy <t> <単価> <株数>     購入登録\n"
            "  /sell <t> <株数> [単価]    売却登録\n"
            "  /port                      保有サマリー\n"
            "\n"
            "  /help                      このヘルプ"
        )
    
    # --- 自然言語フォールバック ---
    # コマンド (/ で始まる) ではなく、空でもないテキストは会話履歴付きで AI に流す
    if text and not text.startswith("/"):
        return _ask_with_history(user_id, text)

    return ""  # ノイズ削減のため無応答


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        events = _parser.parse(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            continue

        user_id = getattr(event.source, "user_id", "")
        text = event.message.text.strip()
        src_type = getattr(event.source, "type", "user")
        line_group_id = getattr(event.source, "group_id", None)

        log.info(f"[LINE] src={src_type} group_id={line_group_id!r} user={user_id!r} text={text!r}")

        # --- コマンド解析 ---
        parts = text.split(maxsplit=2)
        cmd = parts[0].lower() if parts else ""
        
        # --- グループコンテキスト ---
        if src_type == "group" and line_group_id:
            reply = _handle_group_command(event, user_id, line_group_id, text, cmd, parts, event.reply_token)
        elif src_type == "user":
            reply = _handle_personal_command(user_id, text, cmd, parts, event.reply_token)
        else:
            reply = ""
        
        if reply:
            try:
                _reply(event.reply_token, reply)
            except Exception as e:
                log.error(f"reply failed: {e}")

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "minimal-webhook"}
