-- =============================================
-- Stock AI Agent — Supabase テーブル定義
-- =============================================

-- 監視銘柄リスト
CREATE TABLE IF NOT EXISTS watchlist (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     TEXT NOT NULL,           -- LINE User ID
  ticker      TEXT NOT NULL,           -- 例: "7203.T", "AAPL"
  alert_price NUMERIC,                 -- 指値アラート価格
  alert_pct   NUMERIC,                 -- 変動率アラート閾値(%)
  note        TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, ticker)
);

-- ユーザー設定
CREATE TABLE IF NOT EXISTS user_settings (
  user_id         TEXT PRIMARY KEY,
  morning_hour    INT DEFAULT 8,
  morning_minute  INT DEFAULT 0,
  alert_interval  INT DEFAULT 5,       -- 分
  language        TEXT DEFAULT 'ja',
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- アラート送信履歴（重複通知防止）
CREATE TABLE IF NOT EXISTS alert_history (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT NOT NULL,
  ticker     TEXT,
  alert_type TEXT NOT NULL,            -- 'price', 'pct', 'market', 'vix'
  message    TEXT,
  sent_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ポートフォリオ保有銘柄
CREATE TABLE IF NOT EXISTS portfolio (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT NOT NULL,
  ticker     TEXT NOT NULL,
  qty        NUMERIC NOT NULL,           -- 保有株数
  avg_cost   NUMERIC NOT NULL,           -- 平均取得単価
  note       TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, ticker)
);

-- 売買履歴（損益トラッキング用）
CREATE TABLE IF NOT EXISTS trade_history (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT NOT NULL,
  ticker     TEXT NOT NULL,
  side       TEXT NOT NULL,             -- 'buy' | 'sell'
  qty        NUMERIC NOT NULL,
  price      NUMERIC NOT NULL,
  pnl        NUMERIC,                   -- 売却時の実現損益
  traded_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security (必要に応じて有効化)
ALTER TABLE watchlist      ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_history  ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio      ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_history  ENABLE ROW LEVEL SECURITY;
