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
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import re
from datetime import datetime

# .envファイルを読み込む
load_dotenv()

# 環境変数の設定
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')
DATABASE_NAME = os.getenv('DATABASE_NAME')
DATABASE_USER = os.getenv('DATABASE_USER')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD')
DATABASE_HOST = os.getenv('DATABASE_HOST')
DATABASE_PORT = os.getenv('DATABASE_PORT')

# Flaskアプリのインスタンス化
app = Flask(__name__)

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# LINEのアクセストークンを読み込む
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)
handler = WebhookHandler(CHANNEL_SECRET)

# グローバル変数としてuser_stepsを初期化
user_steps = {}

# データベースへの接続をテストする関数
def test_database_connection():
    try:
        conn = psycopg2.connect(
            database=DATABASE_NAME,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT
        )
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Database connection successful.")
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise

# テーブルを作成する関数
def create_table():
    try:
        connection = psycopg2.connect(
            database=DATABASE_NAME,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT
        )
        cursor = connection.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                line_id VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                work_date DATE,
                check_in_time TIME,
                check_out_time TIME,
                break_time TIME,
                work_summary TEXT
            )
        ''')
        connection.commit()
        cursor.close()
        connection.close()
        logger.info("Table created successfully.")
    except psycopg2.Error as e:
        logger.error(f"Failed to create table: {e}")
        raise

def handle_step(user_message, user_id):
    global user_steps
    if user_id not in user_steps:
        user_steps[user_id] = {
            "current_step": "start",
            "employee_data": {
                "名前": None,
                "勤務日": None,
                "出勤時間": None,
                "退勤時間": None,
                "休憩時間": None,
                "業務内容サマリ": None
            }
        }

    step_data = user_steps[user_id]
    current_step = step_data["current_step"]
    employee_data = step_data["employee_data"]

    try:
        if current_step == "start":
            current_step = "名前"
        elif current_step == "名前":
            employee_data["名前"] = user_message
            current_step = "勤務日"
        elif current_step == "勤務日":
            if validate_date(user_message):
                employee_data["勤務日"] = user_message
                current_step = "出勤時間"
            else:
                raise ValueError("勤務日の形式が正しくありません。 (例: 2023-07-01)")
        elif current_step == "出勤時間":
            if validate_time(user_message):
                employee_data["出勤時間"] = user_message
                current_step = "退勤時間"
            else:
                raise ValueError("出勤時間の形式が正しくありません。 (例: 09:00)")
        elif current_step == "退勤時間":
            if validate_time(user_message):
                employee_data["退勤時間"] = user_message
                current_step = "休憩時間"
            else:
                raise ValueError("退勤時間の形式が正しくありません。 (例: 18:00)")
        elif current_step == "休憩時間":
            if validate_time(user_message):
                employee_data["休憩時間"] = user_message
                current_step = "業務内容サマリ"
            else:
                raise ValueError("休憩時間の形式が正しくありません。 (例: 01:00)")
        elif current_step == "業務内容サマリ":
            employee_data["業務内容サマリ"] = user_message
            save_to_database(user_id, employee_data)
            current_step = "completed"
        
        step_data["current_step"] = current_step
        step_data["employee_data"] = employee_data
        user_steps[user_id] = step_data

    except ValueError as e:
        # エラーメッセージを送信し、ステップを最初に戻す
        line_bot_api.push_message(user_id, TextMessage(text=str(e)))
        user_steps[user_id]["current_step"] = "start"

def validate_date(date_text):
    try:
        datetime.strptime(date_text, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_time(time_text):
    try:
        datetime.strptime(time_text, '%H:%M')
        return True
    except ValueError:
        return False

def ask_next_question(reply_token, user_id):
    global user_steps
    step_data = user_steps[user_id]
    current_step = step_data["current_step"]

    if current_step == "start":
        response_message = "名前を教えてください。"
    elif current_step == "名前":
        response_message = "名前を教えてください。"
    elif current_step == "勤務日":
        response_message = "勤務日を教えてください。 (例: 2023-07-01)"
    elif current_step == "出勤時間":
        response_message = "出勤時間を教えてください。 (入力例: 09:00)"
    elif current_step == "退勤時間":
        response_message = "退勤時間を教えてください。 (入力例: 18:00)"
    elif current_step == "休憩時間":
        response_message = "休憩時間を教えてください。 (入力例: 01:00)"
    elif current_step == "業務内容サマリ":
        response_message = "業務内容サマリを教えてください。 (入力例: アプリ開発)"
    elif current_step == "completed":
        response_message = "データが保存されました。ありがとうございます。"
        del user_steps[user_id]

    line_bot_api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text=response_message)]
    ))

def save_to_database(user_id, employee_data):
    try:
        connection = psycopg2.connect(
            database=DATABASE_NAME,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT
        )
        cursor = connection.cursor()
        cursor.execute('''
            INSERT INTO attendance (line_id, name, work_date, check_in_time, check_out_time, break_time, work_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, employee_data["名前"], employee_data["勤務日"], employee_data["出勤時間"],
              employee_data["退勤時間"], employee_data["休憩時間"], employee_data["業務内容サマリ"]))
        connection.commit()
        cursor.close()
        connection.close()
        logger.info("Data saved successfully.")
    except psycopg2.Error as e:
        logger.error(f"Failed to save data: {e}")
        raise

# 毎朝7時にメッセージを送信する関数
def send_daily_message():
    try:
        # ユーザーIDをデータベースやファイルから取得する必要があります
        user_ids = get_all_user_ids()  # これはユーザーIDを取得する関数です
        for user_id in user_ids:
            line_bot_api.push_message(user_id, TextMessage(text="おはようございます。昨日の勤怠情報を登録してくれますか？"))
        logger.info("Daily message sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send daily message: {e}")

# ユーザーIDを取得するダミー関数（実際にはデータベースなどから取得する実装が必要です）
def get_all_user_ids():
    return ['USER_ID_1', 'USER_ID_2']  # ここに実際のユーザーIDリストを返す実装を追加します

# スケジューラーを設定
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_message, 'cron', hour=7, minute=0)
scheduler.start()

# 初回メッセージ送信をトリガーするためにユーザーからのメッセージをハンドリング
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    global user_steps
    reply_token = event.reply_token
    user_message = event.message.text.strip()
    user_id = event.source.user_id  # LINE IDを取得

    logger.info(f"Received message: {user_message} from user: {user_id}")
    logger.info(f"Current employee_data: {user_steps.get(user_id, {}).get('employee_data', {})}")
    logger.info(f"Current step: {user_steps.get(user_id, {}).get('current_step', 'start')}")

    try:
        handle_step(user_message, user_id)
        ask_next_question(reply_token, user_id)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="エラーが発生しました。入力形式に従って、もう一度やり直してください。")]
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
    logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid signature. Check your channel access token/channel secret.")
        abort(400)
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        abort(500)

    return 'OK'

# Bot起動コード
if __name__ == "__main__":
    logger.info("Testing database connection.")
    test_database_connection()  # データベース接続をテスト
    logger.info("Creating table if not exists.")
    create_table()  # テーブルを作成
    app.run(host="0.0.0.0", port=8000, debug=True)
