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
DATABASE_URL = os.getenv('DATABASE_URL')

# Flaskアプリのインスタンス化
app = Flask(__name__)

# LINEのアクセストークンを読み込む
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# グローバル変数としてemployee_dataを初期化
employee_data = {
    "名前": None,
    "日時": None,
    "出勤時間": None,
    "退勤時間": None,
    "休憩時間": None,
    "業務内容サマリ": None
}

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
    global employee_data
    reply_token = event.reply_token
    user_message = event.message.text

    app.logger.info(f"Received message: {user_message}")

    if employee_data["名前"] is None:
        send_initial_message(reply_token)
    else:
        handle_message(event, user_message)

# 初回メッセージ送信
def send_initial_message(reply_token):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        initial_message = "名前を教えてください。"
        app.logger.info("Sending initial message for name.")
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=initial_message)]
        ))

# ユーザーのメッセージを処理してデータを更新
def handle_message(event, user_message):
    global employee_data
    reply_token = event.reply_token

    if employee_data["名前"] is None:
        employee_data["名前"] = user_message
        response_message = "日時を教えてください。"
    elif employee_data["日時"] is None:
        employee_data["日時"] = user_message
        response_message = "出勤時間を教えてください。"
    elif employee_data["出勤時間"] is None:
        employee_data["出勤時間"] = datetime.strptime(user_message, "%Y-%m-%d %H:%M:%S")
        response_message = "退勤時間を教えてください。"
    elif employee_data["退勤時間"] is None:
        employee_data["退勤時間"] = datetime.strptime(user_message, "%Y-%m-%d %H:%M:%S")
        response_message = "休憩時間を教えてください。"
    elif employee_data["休憩時間"] is None:
        employee_data["休憩時間"] = user_message
        response_message = "業務内容サマリを教えてください。"
    elif employee_data["業務内容サマリ"] is None:
        employee_data["業務内容サマリ"] = user_message
        save_to_database(employee_data)
        response_message = "データが保存されました。ありがとうございます。"

        # Reset employee_data for the next interaction
        employee_data = {key: None for key in employee_data}

    app.logger.info(f"Sending message: {response_message}")
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=response_message)]
        ))

# トップページ
@app.route('/', methods=['GET'])
def toppage():
    return 'Hello world!'

# LINEのWebhookイベントを処理するルート
@app.route('/callback', methods=['POST'])
def callback():
    # Get request body as text
    signature = request.headers['X-Line-Signature']

    # Handle webhook body
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# Bot起動コード
if __name__ == "__main__":
    create_table()
    app.run(host="0.0.0.0", port=8000, debug=True)




