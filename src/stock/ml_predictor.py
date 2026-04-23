"""
ML予測シグナル
特徴量: RSI / MACD / BB / MA乖離 / 出来高比 / 短期ボラ / 価格モメンタム
モデル: RandomForest + LogisticRegression アンサンブル
ラベル: 翌 forward_days 日のリターンが +threshold% 以上 → 1, それ以外 → 0
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import warnings
from dataclasses import dataclass

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import joblib
import os

from src.stock.fetcher import get_ohlcv
from src.stock.technicals import compute_indicators

warnings.filterwarnings("ignore", category=UserWarning)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "../../.models")
os.makedirs(MODEL_DIR, exist_ok=True)


# ------------------------------------------------------------------ #
# 特徴量エンジニアリング
# ------------------------------------------------------------------ #

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCVデータから ML特徴量を生成"""
    df = df.copy()
    close  = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    # テクニカル指標
    import ta
    df["RSI"]      = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["RSI_fast"] = ta.momentum.RSIIndicator(close, window=7).rsi()

    macd = ta.trend.MACD(close)
    df["MACD_diff"] = macd.macd_diff()
    df["MACD_hist_slope"] = df["MACD_diff"].diff()

    bb = ta.volatility.BollingerBands(close, window=20)
    df["BB_pct"]   = bb.bollinger_pband()
    df["BB_width"] = (bb.bollinger_hband() - bb.bollinger_lband()) / close  # バンド幅

    df["MA5"]      = close.rolling(5).mean()
    df["MA25"]     = close.rolling(25).mean()
    df["MA75"]     = close.rolling(75).mean()
    df["MA_div5"]  = (close - df["MA5"])  / df["MA5"]  * 100
    df["MA_div25"] = (close - df["MA25"]) / df["MA25"] * 100
    df["MA_div75"] = (close - df["MA75"]) / df["MA75"] * 100

    # モメンタム（過去N日リターン）
    for n in [1, 3, 5, 10, 20]:
        df[f"ret_{n}d"] = close.pct_change(n) * 100

    # 短期ボラティリティ
    df["vol_5d"]  = close.pct_change().rolling(5).std()  * 100
    df["vol_20d"] = close.pct_change().rolling(20).std() * 100

    # 出来高比
    df["vol_ratio5"]  = volume / volume.rolling(5).mean()
    df["vol_ratio20"] = volume / volume.rolling(20).mean()

    # 高値・安値からの距離
    df["hi52w"] = close / close.rolling(252).max()
    df["lo52w"] = close / close.rolling(252).min()

    return df


FEATURE_COLS = [
    "RSI", "RSI_fast",
    "MACD_diff", "MACD_hist_slope",
    "BB_pct", "BB_width",
    "MA_div5", "MA_div25", "MA_div75",
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d",
    "vol_5d", "vol_20d",
    "vol_ratio5", "vol_ratio20",
    "hi52w", "lo52w",
]


# ------------------------------------------------------------------ #
# データクラス
# ------------------------------------------------------------------ #

@dataclass
class MLPrediction:
    ticker: str
    signal: int              # 1=買い, 0=中立/売り
    prob_up: float           # 上昇確率 0.0~1.0
    confidence: str          # "高" / "中" / "低"
    cv_accuracy: float       # 時系列CV精度
    feature_importance: dict[str, float]
    forward_days: int


# ------------------------------------------------------------------ #
# モデル学習 & 予測
# ------------------------------------------------------------------ #

def _build_pipeline() -> Pipeline:
    rf  = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42, n_jobs=-1)
    return Pipeline([("scaler", StandardScaler()), ("clf", rf)])


def train_and_predict(
    ticker: str,
    forward_days: int = 5,
    threshold_pct: float = 1.5,
    period: str = "3y",
) -> MLPrediction:
    """
    過去データで学習し、最新バーの上昇確率を返す。
    forward_days 日後に threshold_pct% 以上上昇 → ラベル1
    """
    df = get_ohlcv(ticker, period=period, interval="1d")
    if df.empty or len(df) < 150:
        raise ValueError(f"{ticker}: データ不足 ({len(df)}本)")

    df = build_features(df)

    close = df["Close"].squeeze()
    # ラベル生成
    future_ret = close.shift(-forward_days) / close - 1
    df["label"] = (future_ret * 100 >= threshold_pct).astype(int)

    # 有効行を抽出
    df_clean = df[FEATURE_COLS + ["label"]].dropna()
    if len(df_clean) < 100:
        raise ValueError(f"{ticker}: クリーンデータ不足 ({len(df_clean)}行)")

    X = df_clean[FEATURE_COLS].values
    y = df_clean["label"].values

    # 時系列CV（未来リーク防止）
    tscv = TimeSeriesSplit(n_splits=5)
    accs = []
    for tr_idx, val_idx in tscv.split(X):
        pipe = _build_pipeline()
        pipe.fit(X[tr_idx], y[tr_idx])
        preds = pipe.predict(X[val_idx])
        accs.append(accuracy_score(y[val_idx], preds))
    cv_acc = float(np.mean(accs))

    # 全データで再学習
    final_pipe = _build_pipeline()
    final_pipe.fit(X, y)

    # 最新バーを予測
    latest_df = df[FEATURE_COLS].dropna().iloc[[-1]]
    prob = float(final_pipe.predict_proba(latest_df.values)[0][1])
    signal = 1 if prob >= 0.55 else 0

    # 特徴量重要度（RFから取得）
    rf_model = final_pipe.named_steps["clf"]
    importances = {
        col: round(float(imp), 4)
        for col, imp in sorted(
            zip(FEATURE_COLS, rf_model.feature_importances_),
            key=lambda x: x[1], reverse=True
        )[:5]
    }

    confidence = "高" if abs(prob - 0.5) > 0.15 else ("中" if abs(prob - 0.5) > 0.08 else "低")

    return MLPrediction(
        ticker=ticker,
        signal=signal,
        prob_up=round(prob, 3),
        confidence=confidence,
        cv_accuracy=round(cv_acc, 3),
        feature_importance=importances,
        forward_days=forward_days,
    )


def format_ml_message(pred: MLPrediction) -> str:
    signal_icon = "🟢 買いシグナル" if pred.signal == 1 else "🔴 中立/様子見"
    bar_len = int(pred.prob_up * 20)
    prob_bar = "█" * bar_len + "░" * (20 - bar_len)

    fi_lines = "\n".join([f"  {k}: {v:.3f}" for k, v in pred.feature_importance.items()])

    return (
        f"🤖 ML予測シグナル: {pred.ticker}\n"
        f"{signal_icon}\n\n"
        f"上昇確率 ({pred.forward_days}日後)\n"
        f"[{prob_bar}] {pred.prob_up*100:.1f}%\n"
        f"確信度: {pred.confidence}  CV精度: {pred.cv_accuracy*100:.1f}%\n\n"
        f"主要特徴量 TOP5:\n{fi_lines}"
    )
