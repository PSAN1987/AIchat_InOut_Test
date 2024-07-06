# -*- coding: utf-8 -*-
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
import os
import openai
import sqlite3
from dotenv import load_dotenv
from datetime import datetime

# .envファイルを読み込む
load_dotenv()

# 環境変数の設定
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# OpenAI APIキーの設定
openai.api_key = OPENAI_API_KEY

# Flaskアプリのインスタンス化
app = Flask(__name__)

# LINEのアクセストークンを読み込む
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# OpenAI APIから応答を取得する関数
def get_chat_response(prompt, model="gpt-4"):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": prompt}]
    )
    return response.choices[0].message['content']

# テーブルを作成する関数
def create_table():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS attendance
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT,
                       datetime TEXT,
                       check_in_time TEXT,
                       check_out_time TEXT,
                       break_time TEXT,
                       work_summary TEXT)''')
    conn.commit()
    conn.close()

# 従業員データをデータベースに保存する関数
def save_to_database(employee_data):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO attendance (name, datetime, check_in_time, check_out_time, break_time, work_summary)
                      VALUES (?, ?, ?, ?, ?, ?)''',
                   (employee_data["名前"],
                    employee_data["日時"],
                    employee_data["出勤時間"].strftime("%Y-%m-%d %H:%M:%S"),
                    employee_data["退勤時間"].strftime("%Y-%m-%d %H:%M:%S"),
                    employee_data["休憩時間"],
                    employee_data["業務内容サマリ"]))
    conn.commit()
    conn.close()

# 従業員データの初期化
employee_data = {
    "名前": None,
    "日時": None,
    "出勤時間": None,
    "退勤時間": None,
    "休憩時間": None,
    "業務内容サマリ": None
}

# コールバック関数
@app.route("/callback", methods=['POST'])
def callback():
    # X-Line-Signatureヘッダーの値を取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディをテキストとして取得
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # Webhookボディを処理
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# 友達追加時のメッセージ送信
@handler.add(FollowEvent)
def handle_follow(event):
    # APIクライアントのインスタンス化
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 返信
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text='Thank You!')]
        ))

# メッセージ受信時の処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # APIクライアントのインスタンス化
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        user_message = event.message.text
        reply_token = event.reply_token

        if employee_data["名前"] is None:
            employee_data["名前"] = user_message
            response_message = "出勤時間を教えてください（例：09:00）。"
        
        elif employee_data["出勤時間"] is None:
            try:
                current_date = datetime.now().strftime("%Y-%m-%d")
                employee_data["出勤時間"] = datetime.strptime(f"{current_date} {user_message}", "%Y-%m-%d %H:%M")
                response_message = "退勤時間を教えてください（例：18:00）。"
            except ValueError:
                response_message = "時間の形式が正しくありません。再度入力してください。出勤時間を教えてください（例：09:00）。"

        elif employee_data["退勤時間"] is None:
            try:
                current_date = datetime.now().strftime("%Y-%m-%d")
                employee_data["退勤時間"] = datetime.strptime(f"{current_date} {user_message}", "%Y-%m-%d %H:%M")
                response_message = "休憩時間を教えてください（例：1時間）。"
            except ValueError:
                response_message = "時間の形式が正しくありません。再度入力してください。退勤時間を教えてください（例：18:00）。"

        elif employee_data["休憩時間"] is None:
            employee_data["休憩時間"] = user_message
            response_message = "今日の業務内容を教えてください。"
        
        elif employee_data["業務内容サマリ"] is None:
            employee_data["業務内容サマリ"] = user_message
            current_date = datetime.now()
            employee_data["日時"] = current_date.strftime("%Y-%m-%d %H:%M:%S")
            save_to_database(employee_data)
            response_message = "勤怠情報を保存しました。ありがとうございました。"

            # 次のユーザーのためにemployee_dataをリセット
            for key in employee_data.keys():
                employee_data[key] = None

        else:
            response_message = "勤怠情報が既に保存されています。"

        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=response_message)]
        ))

if __name__ == "__main__":
    create_table()
    app.run(debug=True, host='0.0.0.0', port=5000)

