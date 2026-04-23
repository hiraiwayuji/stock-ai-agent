"""
バックテスト CLI 実行スクリプト
使い方: python scripts/run_backtest.py <ticker> <strategy> [period]
例:     python scripts/run_backtest.py 7203.T golden 2y
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.stock.fetcher import get_ohlcv
from src.stock.technicals import compute_indicators
from src.stock.backtest import run_backtest, format_backtest_message
from src.stock.strategies import STRATEGY_MAP, STRATEGY_DESCRIPTIONS


def main():
    if len(sys.argv) < 3:
        print("使い方: python scripts/run_backtest.py <ticker> <strategy> [period]")
        print(f"戦略一覧: {list(STRATEGY_MAP.keys())}")
        sys.exit(1)

    ticker   = sys.argv[1].upper()
    strat_key = sys.argv[2].lower()
    period   = sys.argv[3] if len(sys.argv) > 3 else "2y"

    if strat_key not in STRATEGY_MAP:
        print(f"不明な戦略: {strat_key}")
        print("利用可能:", list(STRATEGY_MAP.keys()))
        sys.exit(1)

    print(f"バックテスト開始: {ticker} / {strat_key} / {period}")
    df = get_ohlcv(ticker, period=period, interval="1d")
    if df.empty:
        print("データ取得失敗")
        sys.exit(1)

    df = compute_indicators(df)
    strategy = STRATEGY_MAP[strat_key]
    result = run_backtest(df, strategy, ticker)

    print("\n" + format_backtest_message(result))

    # 全戦略比較モード
    if "--compare" in sys.argv:
        print("\n=== 全戦略比較 ===")
        rows = []
        for key, strat in STRATEGY_MAP.items():
            r = run_backtest(df, strat, ticker)
            rows.append({
                "戦略": key,
                "総リターン": f"{r.total_return_pct:+.2f}%",
                "シャープ": f"{r.sharpe_ratio:.2f}",
                "最大DD": f"{r.max_drawdown_pct:.2f}%",
                "勝率": f"{r.win_rate_pct:.1f}%",
                "取引数": r.total_trades,
            })
        for row in rows:
            print("  ".join(f"{k}:{v}" for k, v in row.items()))


if __name__ == "__main__":
    main()
