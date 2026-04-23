#!/bin/bash
# LINE Webhook サーバー起動
# ngrok などで公開してLINE Developersに登録
# Webhook URL: https://<ngrok-url>/webhook
source venv/Scripts/activate
uvicorn src.line.webhook:app --reload --port 8000
