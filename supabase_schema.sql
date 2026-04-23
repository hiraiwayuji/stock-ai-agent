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

-- 投資目標テーブル
-- yearly は month=0 で統一（NULL だと UNIQUE 制約が効かないため）
CREATE TABLE IF NOT EXISTS investment_goals (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        TEXT    NOT NULL,
  goal_type      TEXT    NOT NULL CHECK (goal_type IN ('monthly', 'yearly')),
  year           INT     NOT NULL CHECK (year >= 2020),
  month          INT     NOT NULL DEFAULT 0
                         CHECK (
                           (goal_type = 'monthly' AND month BETWEEN 1 AND 12)
                           OR (goal_type = 'yearly' AND month = 0)
                         ),
  target_pnl     NUMERIC(15,0) NOT NULL,   -- 整数円で管理
  target_winrate NUMERIC(5,2)  CHECK (target_winrate BETWEEN 0 AND 100),
  target_trades  INT           CHECK (target_trades > 0),
  created_at     TIMESTAMPTZ   DEFAULT NOW(),
  UNIQUE (user_id, goal_type, year, month)
);

ALTER TABLE investment_goals ENABLE ROW LEVEL SECURITY;

-- =============================================
-- Step11: グループ共有機能
-- =============================================

-- グループ（LINEグループ or 仮想グループ）
CREATE TABLE IF NOT EXISTS groups (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT NOT NULL,
  line_group_id TEXT UNIQUE,               -- LINE グループID (event.source.group_id)
  invite_code  TEXT UNIQUE NOT NULL,       -- 6桁招待コード
  owner_id     TEXT NOT NULL,              -- 作成者 user_id
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- グループメンバー
CREATE TABLE IF NOT EXISTS group_members (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  nickname   TEXT,
  joined_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (group_id, user_id)
);

-- 売買共有（trade_history からグループに共有されたもの）
CREATE TABLE IF NOT EXISTS trade_shares (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  ticker     TEXT NOT NULL,
  side       TEXT NOT NULL CHECK (side IN ('buy','sell')),
  qty        NUMERIC NOT NULL,
  price      NUMERIC NOT NULL,
  pnl        NUMERIC,
  comment    TEXT,
  shared_at  TIMESTAMPTZ DEFAULT NOW()
);

-- グループ内チャット（in-app タイムライン）
CREATE TABLE IF NOT EXISTS group_messages (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id    TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'comment',  -- 'comment' | 'trade' | 'system'
  body       TEXT,
  ref_trade_id UUID REFERENCES trade_shares(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_shares_group   ON trade_shares (group_id, shared_at DESC);
CREATE INDEX IF NOT EXISTS idx_group_messages_group ON group_messages (group_id, created_at DESC);

ALTER TABLE groups         ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_members  ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_shares   ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_messages ENABLE ROW LEVEL SECURITY;
