#!/bin/bash
# LINE Webhook サーバー起動 (最小版 / Phase B)
# 注: フル版 src.line.webhook は ml_predictor → sklearn → pyarrow が
#     Windows のアプリ実行ポリシーで DLL ロードに失敗するため、
#     当面は scripts/minimal_webhook を使用する。
# ngrok などで公開して LINE Developers の Webhook URL に登録
# Webhook URL: https://<ngrok-url>/webhook
cd "$(dirname "$0")"
venv/Scripts/python.exe -m uvicorn scripts.minimal_webhook:app --reload --port 8000
