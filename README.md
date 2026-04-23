# Stock AI Agent

## 概要

LINE Bot + OpenAI + Supabase を組み合わせた株式投資支援 AI エージェント。テクニカル分析・相場レジーム判定・ML予測・ポートフォリオ管理・スクリーニングなど 17 コマンドをLINEから操作でき、GitHub Actions で自動ブリーフィング・アラート・レポートを配信します。

---

## 機能一覧

- **テクニカル + AI 分析** — RSI・MACD・ボリンジャーバンドなどのテクニカル指標と OpenAI による総合分析コメントを生成
- **相場レジーム判定** — トレンド・レンジ・ボラティリティを分類し、現在の市場環境を診断
- **過去類似パターン検索** — 直近チャートと類似した過去パターンを特定し、その後の値動きを参考情報として提示
- **センチメント乖離検出** — ニュース感情スコアと株価の乖離を検知し、過熱・売られすぎを警告
- **AI 自由相談** — 銘柄・戦略・経済状況など任意の質問を OpenAI で回答
- **指値監視** — 指定価格に到達した際に LINE 通知を送るアラート登録
- **ポートフォリオ管理** — 購入・売却を記録し、損益サマリーと AI による改善提案を提供
- **スクリーナー** — プリセット条件またはカスタム条件で銘柄フィルタリング
- **戦略バックテスト** — 移動平均クロスなどの戦略を過去データで検証し、パフォーマンス指標を算出
- **ML 上昇確率予測** — 機械学習モデルで短期上昇確率を算出
- **4 軸スコアリング** — テクニカル・ファンダメンタル・センチメント・モメンタムで銘柄を総合スコアリング
- **ウォッチリスト最適化・監査** — 保有ウォッチリストを AI が見直し、追加・削除を提案
- **朝イチブリーフィング（自動）** — 平日8:00 JST に市場概況・注目銘柄をプッシュ通知
- **市場アラート監視（自動）** — 取引時間中 15 分毎に価格・センチメントを監視し条件成立時に通知
- **ポートフォリオ日次レポート（自動）** — 毎日 15:35 JST に損益サマリーを自動配信
- **ウォッチリスト週次最適化（自動）** — 毎週月曜 7:30 JST にウォッチリストを自動レビュー

---

## ディレクトリ構成

```
stock-ai-agent/
├── main.py                    # LINE Webhook サーバー (Flask)
├── requirements.txt           # Python 依存パッケージ
├── supabase_schema.sql        # Supabase テーブル定義
├── start_webhook.sh           # Webhook サーバー起動スクリプト
├── start_scheduler.sh         # ローカルスケジューラ起動スクリプト
├── scripts/                   # GitHub Actions から呼び出すバッチ
│   ├── run_morning.py         # 朝イチブリーフィング
│   ├── run_alert.py           # 市場アラート監視
│   ├── run_portfolio_report.py# ポートフォリオ日次レポート
│   ├── run_optimize.py        # ウォッチリスト週次最適化
│   └── run_backtest.py        # バックテスト単体実行
├── src/
│   ├── ai/
│   │   └── analyst.py         # OpenAI呼び出し・分析コメント生成
│   ├── alerts/
│   │   └── monitor.py         # 指値アラート管理・通知
│   ├── db/
│   │   ├── supabase_client.py # Supabase クライアント初期化
│   │   └── portfolio.py       # ポートフォリオ CRUD
│   ├── line/
│   │   ├── client.py          # LINE Messaging API ラッパー
│   │   └── webhook.py         # コマンドルーティング
│   ├── news/
│   │   ├── fetcher.py         # ニュース取得
│   │   └── sentiment.py       # センチメントスコア算出
│   └── stock/
│       ├── fetcher.py         # 株価データ取得 (yfinance)
│       ├── technicals.py      # テクニカル指標計算
│       ├── regime.py          # 相場レジーム判定
│       ├── pattern_match.py   # 類似パターン検索
│       ├── screener.py        # スクリーナー
│       ├── backtest.py        # バックテストエンジン
│       ├── strategies.py      # バックテスト戦略定義
│       ├── ml_predictor.py    # ML予測モデル
│       ├── portfolio_analyzer.py # 損益集計・AI提案
│       └── watchlist_optimizer.py# ウォッチリスト最適化
└── .github/workflows/
    ├── morning_briefing.yml
    ├── market_alert.yml
    ├── portfolio_report.yml
    └── weekly_optimize.yml
```

---

## セットアップ

### 1. Python 仮想環境

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 2. 依存インストール

```bash
pip install -r requirements.txt
```

### 3. .env 設定

プロジェクトルートに `.env` を作成し、以下のキーを設定してください。

```env
# LINE
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
LINE_CHANNEL_SECRET=your_channel_secret
LINE_USER_ID=your_line_user_id

# OpenAI
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o          # 例: gpt-4o, gpt-4o-mini

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

> `.env` は `.gitignore` 済みです。絶対にコミットしないでください。

### 4. Supabase スキーマ適用

Supabase ダッシュボードの SQL Editor で `supabase_schema.sql` を実行してテーブルを作成してください。

```bash
# Supabase CLI を使う場合
supabase db push
```

---

## LINEコマンド一覧

LINE でエージェントに送信できる全 17 コマンドです。銘柄コードは Yahoo Finance 形式（例: `7203.T`, `^N225`）で指定します。

| カテゴリ | コマンド | 説明 | 例 |
|---|---|---|---|
| 分析 | `/check <銘柄>` | テクニカル指標 + AI 総合分析 | `/check 7203.T` |
| 分析 | `/regime <銘柄>` | 相場レジーム判定（トレンド/レンジ/高VIX等） | `/regime ^N225` |
| 分析 | `/pattern <銘柄>` | 過去の類似チャートパターンを検索 | `/pattern 9984.T` |
| 分析 | `/divergence <銘柄>` | ニュースセンチメントと株価の乖離を検出 | `/divergence 6758.T` |
| 分析 | `/ask <質問>` | AI への自由相談（銘柄・戦略・市場など） | `/ask 日経平均の見通しは？` |
| 監視 | `/add <銘柄> <価格>` | 指値監視を登録（到達時にLINE通知） | `/add 7203.T 3200` |
| 監視 | `/list` | 登録中の監視アラート一覧を表示 | `/list` |
| ポートフォリオ | `/buy <銘柄> <株数> <取得価格>` | 購入を記録 | `/buy 7203.T 100 3000` |
| ポートフォリオ | `/sell <銘柄> <株数> <売却価格>` | 売却を記録 | `/sell 7203.T 100 3500` |
| ポートフォリオ | `/port` | 保有銘柄の損益サマリーを表示 | `/port` |
| ポートフォリオ | `/port ai` | 損益サマリー + AI によるリバランス提案 | `/port ai` |
| スクリーナー | `/screen <プリセット>` | プリセット条件でスクリーニング（例: momentum, value） | `/screen momentum` |
| スクリーナー | `/screen_custom <条件>` | カスタム条件でスクリーニング（例: rsi<30 volume>1M） | `/screen_custom rsi<30` |
| バックテスト | `/backtest <銘柄> <戦略>` | 過去データで戦略をバックテスト | `/backtest 7203.T sma_cross` |
| ML・最適化 | `/ml <銘柄>` | ML モデルで短期上昇確率を予測 | `/ml 9984.T` |
| ML・最適化 | `/score <銘柄>` | テクニカル・センチメント等 4 軸でスコアリング | `/score 6758.T` |
| ML・最適化 | `/optimize` | ウォッチリスト全体を AI が評価し最適化提案 | `/optimize` |
| ML・最適化 | `/audit` | ウォッチリストの弱銘柄を監査・削除候補を提示 | `/audit` |

---

## GitHub Actions スケジュール

リポジトリを GitHub にプッシュすると、以下のワークフローが自動実行されます。GitHub Secrets に `.env` の各キーを、GitHub Variables に以下の変数を設定してください。

### Secrets（GitHub リポジトリ設定 > Secrets and variables > Actions > Secrets）

`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET` / `LINE_USER_ID` / `OPENAI_API_KEY` / `OPENAI_MODEL` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`

### Variables（GitHub リポジトリ設定 > Secrets and variables > Actions > Variables）

| 変数名 | 説明 | 設定例 |
|---|---|---|
| `WATCH_TICKERS` | 毎朝ウォッチする銘柄リスト（カンマ区切り） | `^N225,^VIX,7203.T` |
| `SCAN_TICKERS` | アラート監視対象銘柄 | `7203.T,9984.T,6758.T` |
| `SCREEN_UNIVERSE` | スクリーナー対象ユニバース | `7203.T,9984.T,6758.T,6861.T,8306.T` |
| `DIVERGENCE_THRESHOLD` | センチメント乖離の閾値（標準偏差） | `2.0` |
| `OPTIMIZE_TOP_N` | 最適化後に残すウォッチリスト件数 | `5` |

### ワークフロー一覧

| ワークフロー | 実行タイミング | スクリプト |
|---|---|---|
| 朝イチブリーフィング | 毎朝 8:00 JST（月〜金） | `scripts/run_morning.py` |
| 市場アラート監視 | 9:00〜15:30 JST の 15 分毎 | `scripts/run_alert.py` |
| ポートフォリオ日次レポート | 毎日 15:35 JST | `scripts/run_portfolio_report.py` |
| ウォッチリスト週次最適化 | 毎週月曜 7:30 JST | `scripts/run_optimize.py` |

> すべてのワークフローは `workflow_dispatch` による手動実行にも対応しています。

---

## 独自アルゴリズム

### 1. 相場レジーム判定（`src/stock/regime.py`）

ADX（平均方向性指数）・ATR（真の値幅平均）・VIX を組み合わせ、市場環境を以下の 4 レジームに分類します。

- **Strong Trend** — ADX > 25 かつ方向性が明確
- **Weak Trend / Range** — ADX < 20 で値動きが小さい
- **High Volatility** — ATR や VIX が閾値超
- **Reversal Watch** — RSI 過買い・過売りと出来高急増の同時発生

レジームに応じて `/check` の分析コメントのトーンと推奨戦略が変化します。

### 2. 過去類似パターン検索（`src/stock/pattern_match.py`）

直近 N 日間の株価変動率系列を正規化し、過去データ全体に対してユークリッド距離（または DTW）でローリング比較を行います。上位 K 件の類似区間を抽出し、その後 M 日間の平均リターン・勝率・最大ドローダウンを統計として返します。

### 3. 4 軸スコアリング（`src/stock/ml_predictor.py` / `portfolio_analyzer.py`）

銘柄を以下の 4 軸で 0〜100 点に正規化し、加重合計で総合スコアを算出します。

| 軸 | 主な指標 |
|---|---|
| テクニカル | RSI・MACD・ボリンジャーバンド・出来高 |
| センチメント | ニュース感情スコア・社会的言及量 |
| モメンタム | 直近 1・3・6 ヶ月リターン |
| ボラティリティ | ATR・シャープレシオ・ベータ |

---

## ローカル実行

### LINE Webhook サーバー（ngrok 等でトンネリングが必要）

```bash
source venv/bin/activate
python main.py
# または
bash start_webhook.sh
```

### 各バッチスクリプトの単体実行

```bash
# 朝イチブリーフィング
python scripts/run_morning.py

# 市場アラート監視（1回実行）
python scripts/run_alert.py

# ポートフォリオ日次レポート
python scripts/run_portfolio_report.py

# ウォッチリスト最適化
python scripts/run_optimize.py

# バックテスト（銘柄・戦略は環境変数またはスクリプト内で指定）
python scripts/run_backtest.py
```

### ローカルスケジューラ（GitHub Actions を使わない場合）

```bash
bash start_scheduler.sh
```

---

## ライセンス

MIT
