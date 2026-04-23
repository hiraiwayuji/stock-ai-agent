-- =============================================
-- Stock AI Agent — デモ用サンプルデータ投入
-- 実行先: Supabase SQL Editor
-- 招待コード: DEMO01
-- URL: https://stock-ai-agent-ball.streamlit.app/?code=DEMO01
-- =============================================

-- 既存DEMO01があれば全部消してからやり直す（冪等化）
DELETE FROM alert_history   WHERE user_id = 'LINE_GROUP_DEMO';
DELETE FROM group_messages  WHERE group_id = '11111111-1111-1111-1111-111111111111';
DELETE FROM trade_shares    WHERE group_id = '11111111-1111-1111-1111-111111111111';
DELETE FROM group_members   WHERE group_id = '11111111-1111-1111-1111-111111111111';
DELETE FROM groups          WHERE id       = '11111111-1111-1111-1111-111111111111';

-- グループ
INSERT INTO groups (id, name, line_group_id, invite_code, owner_id) VALUES
  ('11111111-1111-1111-1111-111111111111',
   'デモ投資部',
   'LINE_GROUP_DEMO',
   'DEMO01',
   'demo-user-alice');

-- メンバー5名
INSERT INTO group_members (group_id, user_id, nickname) VALUES
  ('11111111-1111-1111-1111-111111111111', 'demo-user-alice',   'アリス(部長)'),
  ('11111111-1111-1111-1111-111111111111', 'demo-user-bob',     'ボブ'),
  ('11111111-1111-1111-1111-111111111111', 'demo-user-carol',   'キャロル'),
  ('11111111-1111-1111-1111-111111111111', 'demo-user-dan',     'ダン'),
  ('11111111-1111-1111-1111-111111111111', 'demo-user-emma',    'エマ');

-- 売買共有 (直近30日のバラけた取引・勝ち負け混在)
INSERT INTO trade_shares (group_id, user_id, ticker, side, qty, price, pnl, comment, shared_at) VALUES
  -- アリス (勝ち中心・半導体得意)
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','8035.T','buy', 100, 28000, NULL, '東エレ仕込み',             NOW() - INTERVAL '28 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','8035.T','sell',100, 31500,  350000, '+12.5%で利確',           NOW() - INTERVAL '20 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','6920.T','buy', 200, 42000, NULL, 'レーザーテック',            NOW() - INTERVAL '18 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','6920.T','sell',200, 45000,  600000, '+7.1%',                  NOW() - INTERVAL '10 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','7974.T','buy', 50,  7200,  NULL, '任天堂',                    NOW() - INTERVAL '8 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','7974.T','sell',50,  7650,   22500, 'サクッと',                NOW() - INTERVAL '3 days'),

  -- ボブ (負け込み・保有長め)
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '8306.T','buy', 300, 1450,  NULL, '三菱UFJ',                   NOW() - INTERVAL '27 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '8306.T','sell',300, 1380,  -21000,'損切',                    NOW() - INTERVAL '5 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '9984.T','buy', 10,  8900,  NULL, 'ソフトバンクG',              NOW() - INTERVAL '22 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '9984.T','sell',10,  8450,   -4500,'早めに切った',             NOW() - INTERVAL '15 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '4063.T','buy', 50,  5600,  NULL, '信越化学',                  NOW() - INTERVAL '12 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  '4063.T','sell',50,  5920,   16000,'ようやく+',                NOW() - INTERVAL '2 days'),

  -- キャロル (ゲーム・IT集中)
  ('11111111-1111-1111-1111-111111111111','demo-user-carol','7974.T','buy', 30,  7000,  NULL, '任天堂狙い',                NOW() - INTERVAL '25 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-carol','7974.T','sell',30,  7550,   16500,'Switch2期待で利確',        NOW() - INTERVAL '18 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-carol','9984.T','buy', 20,  8700,  NULL, 'SBG',                      NOW() - INTERVAL '14 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-carol','9984.T','sell',20,  9200,   10000,'AIテーマで押し目取り',      NOW() - INTERVAL '6 days'),

  -- ダン (小口短期)
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '7203.T','buy', 100, 3100,  NULL, 'トヨタ',                    NOW() - INTERVAL '26 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '7203.T','sell',100, 3250,   15000,'+4.8%',                   NOW() - INTERVAL '21 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '6758.T','buy', 80,  13500, NULL, 'ソニー',                    NOW() - INTERVAL '17 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '6758.T','sell',80,  13100,  -32000,'決算跨ぎ失敗',            NOW() - INTERVAL '11 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '6367.T','buy', 30,  24000, NULL, 'ダイキン',                  NOW() - INTERVAL '7 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  '6367.T','sell',30,  24800,  24000,'短期+',                   NOW() - INTERVAL '1 days'),

  -- エマ (エース級・高勝率)
  ('11111111-1111-1111-1111-111111111111','demo-user-emma', '8035.T','buy', 50,  27500, NULL, '半導体底値狙い',            NOW() - INTERVAL '24 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-emma', '8035.T','sell',50,  30200,  135000,'+9.8%',                  NOW() - INTERVAL '16 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-emma', '6920.T','buy', 80,  40500, NULL, 'レーザーテック押し目',      NOW() - INTERVAL '13 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-emma', '6920.T','sell',80,  43800,  264000,'トレンドフォロー成功',    NOW() - INTERVAL '4 days');

-- コメントやシステム発話 (タイムライン用)
INSERT INTO group_messages (group_id, user_id, kind, body, created_at) VALUES
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','system', '👋 みんな今月もよろしく！', NOW() - INTERVAL '29 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-bob',  'comment','8306損切り勉強になった…',   NOW() - INTERVAL '5 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-emma', 'comment','半導体まだ行けそう',         NOW() - INTERVAL '4 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-carol','comment','Switch2続報次第では買い増し', NOW() - INTERVAL '3 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-dan',  'comment','決算跨ぎはやめとくべきだった', NOW() - INTERVAL '11 days'),
  ('11111111-1111-1111-1111-111111111111','demo-user-alice','comment','🎯 来週の決算組は慎重に',     NOW() - INTERVAL '1 days');

-- グループ向け重大アラート履歴
INSERT INTO alert_history (user_id, ticker, alert_type, message, sent_at) VALUES
  ('LINE_GROUP_DEMO', NULL, 'group_critical_vix',
   '🚨 デモ投資部 市場重大アラート\n・VIX 急騰: 31.2',
   NOW() - INTERVAL '15 days'),
  ('LINE_GROUP_DEMO', NULL, 'group_critical_n225',
   '🚨 デモ投資部 市場重大アラート\n・日経平均 -3.4%',
   NOW() - INTERVAL '9 days'),
  ('LINE_GROUP_DEMO', NULL, 'group_critical_crash',
   '🚨 デモ投資部 市場重大アラート\n・保有銘柄急落: 8306.T -7.8%',
   NOW() - INTERVAL '2 days');

-- 確認
SELECT invite_code, name FROM groups WHERE id = '11111111-1111-1111-1111-111111111111';
