# -*- coding: utf-8 -*-
import os
import psycopg2
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent
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
    "勤務日": None,
    "出勤時間": None,
    "退勤時間": None,
    "休憩時間": None,
    "業務内容サマリ": None
}
current_step = "start"  # 初期ステップを設定

# テーブルを作成する関数
def create_table():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                name TEXT,
                work_date TEXT,
                check_in_time TEXT,
                check_out_time TEXT,
                break_time TEXT,
                work_summary TEXT
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info("Table created successfully or already exists.")
    except psycopg2.Error as e:
        app.logger.error(f"Failed to create table: {e}")
        raise

# 従業員データをデータベースに保存する関数
def save_to_database(employee_data):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO attendance (name, work_date, check_in_time, check_out_time, break_time, work_summary)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            employee_data["名前"],
            employee_data["勤務日"],
            employee_data["出勤時間"],
            employee_data["退勤時間"],
            employee_data["休憩時間"],
            employee_data["業務内容サマリ"]
        ))
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info("Data saved successfully.")
    except psycopg2.Error as e:
        app.logger.error(f"Database error: {e}")
        raise

# ステップを管理する関数
def handle_step(user_message):
    global current_step, employee_data
    app.logger.info(f"Handling step: {current_step} with message: {user_message}")

    if current_step == "start":
        current_step = "名前"
    elif current_step == "名前":
        employee_data["名前"] = user_message
        current_step = "勤務日" if employee_data["名前"] else "名前"
    elif current_step == "勤務日":
        employee_data["勤務日"] = user_message
        current_step = "出勤時間" if employee_data["勤務日"] else "勤務日"
    elif current_step == "出勤時間":
        employee_data["出勤時間"] = user_message
        current_step = "退勤時間" if employee_data["出勤時間"] else "出勤時間"
    elif current_step == "退勤時間":
        employee_data["退勤時間"] = user_message
        current_step = "休憩時間" if employee_data["退勤時間"] else "退勤時間"
    elif current_step == "休憩時間":
        employee_data["休憩時間"] = user_message
        current_step = "業務内容サマリ" if employee_data["休憩時間"] else "休憩時間"
    elif current_step == "業務内容サマリ":
        employee_data["業務内容サマリ"] = user_message
        if employee_data["業務内容サマリ"]:
            try:
                save_to_database(employee_data)
                current_step = "completed"
            except psycopg2.Error as e:
                app.logger.error(f"Failed to save data: {e}")
                current_step = "業務内容サマリ"
    app.logger.info(f"Updated step: {current_step}")

# 各ステップごとに適切な質問を送信する関数
def ask_next_question(reply_token):
    global current_step
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if current_step == "start":
            response_message = "こんにちは！まず、あなたの名前を教えてください。"
        elif current_step == "名前":
            response_message = "名前を教えてください。"
        elif current_step == "勤務日":
            response_message = "いつの勤務日のデータを入力しますか？ (例: 2024-07-07)"
        elif current_step == "出勤時間":
            response_message = "出勤時間を教えてください。 (例: 09:00)"
        elif current_step == "退勤時間":
            response_message = "退勤時間を教えてください。 (例: 18:00)"
        elif current_step == "休憩時間":
            response_message = "休憩時間を教えてください。 (例: 1時間)"
        elif current_step == "業務内容サマリ":
            response_message = "業務内容サマリを教えてください。"
        elif current_step == "completed":
            response_message = "データが保存されました。ありがとうございます。"
            current_step = "start"
            employee_data.update({
                "名前": None,
                "勤務日": None,
                "出勤時間": None,
                "退勤時間": None,
                "休憩時間": None,
                "業務内容サマリ": None
            })

        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=response_message)]
        ))

# 初回メッセージ送信をトリガーするためにユーザーからのメッセージをハンドリング
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    global current_step
    reply_token = event.reply_token
    user_message = event.message.text.strip()

    app.logger.info(f"Received message: {user_message}")
    app.logger.info(f"Current employee_data: {employee_data}")
    app.logger.info(f"Current step: {current_step}")

    handle_step(user_message)
    ask_next_question(reply_token)

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
    app.logger.info("Creating table if not exists.")
    create_table()  # テーブルを作成
    app.run(host="0.0.0.0", port=8000, debug=True)







