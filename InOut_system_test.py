# -*- coding: utf-8 -*-
import openai
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import (
    FollowEvent, MessageEvent, TextMessageContent
)

# .envファイルを読み込む
load_dotenv()

# 環境変数の設定
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

# OpenAIのAPIキーを設定します
openai.api_key = OPENAI_API_KEY

# Flaskアプリのインスタンス化
app = Flask(__name__)

# LINEのアクセストークンを読み込む
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# テーブルを作成する関数
def create_table():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            name TEXT,
            datetime TEXT,
            check_in_time TEXT,
            check_out_time TEXT,
            break_time TEXT,
            work_summary TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

# 従業員データをデータベースに保存する関数
def save_to_database(employee_data):
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO attendance (name, datetime, check_in_time, check_out_time, break_time, work_summary)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (
        employee_data["名前"],
        employee_data["日時"],
        employee_data["出勤時間"].strftime("%Y-%m-%d %H:%M:%S"),
        employee_data["退勤時間"].strftime("%Y-%m-%d %H:%M:%S"),
        employee_data["休憩時間"],
        employee_data["業務内容サマリ"]
    ))
    conn.commit()
    cursor.close()
    conn.close()

# 初回メッセージ送信をトリガーするためにユーザーからのメッセージをハンドリング
@handler.add(MessageEvent, message=TextMessageContent)
def start_attendance_collection(event):
    reply_token = event.reply_token
    user_message = event.message.text

    if employee_data["名前"] is None:
        send_initial_message(reply_token)
    else:
        handle_message(event)

# 初回メッセージ送信
def send_initial_message(reply_token):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        initial_message = "名前を教えてください。"
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=initial_message)]
        ))

# AI応答を処理する別のハンドラを追加
@handler.add(MessageEvent, message=TextMessageContent)
def handle_ai_message(event):
    if all(value is not None for value in employee_data.values()):
        received_message = event.message.text
        reply_token = event.reply_token

        # AI応答を生成
        response = openai.chat_completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "あなたは役に立つアシスタントです。今日の業務の議論について集中してください。"},
                {"role": "user", "content": received_message}
            ]
        )
        ai_message = response.choices[0].message.content

        # AI応答メッセージをユーザーに送信
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=ai_message)]
            ))

# トップページ
@app.route('/', methods=['GET'])
def toppage():
    return 'Hello world!'

# Bot起動コード
if __name__ == "__main__":
    create_table()
    app.run(host="0.0.0.0", port=8000, debug=True)


