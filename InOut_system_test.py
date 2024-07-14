# -*- coding: utf-8 -*-
import os
import psycopg2
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, request, abort
import openai
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage, PushMessageRequest
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent
)

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
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# OpenAI APIキーの設定
openai.api_key = OPENAI_API_KEY

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
    "業務内容サマリ": None,
}
current_step = "start"  # 初期ステップを設定
current_user_id = None  # 現在のユーザーIDを保存する変数

# データベース接続
def get_db_connection():
    return psycopg2.connect(
        database=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
        host=DATABASE_HOST,
        port=DATABASE_PORT
    )

# データベースへの接続をテストする関数
def test_database_connection():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info("Database connection successful.")
    except psycopg2.Error as e:
        app.logger.error(f"Database connection failed: {e}")
        raise

# テーブルを作成する関数
def create_table():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        create_table_query = '''
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                work_date TEXT NOT NULL,
                check_in_time TEXT NOT NULL,
                check_out_time TEXT NOT NULL,
                break_time TEXT NOT NULL,
                work_summary TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        '''
        cursor.execute(create_table_query)
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info("Tables created successfully or already exist.")
    except Exception as error:
        app.logger.error(f"Failed to create table: {error}")
        raise

# 従業員データをデータベースに保存する関数
def save_to_database(employee_data):
    try:
        conn = get_db_connection()
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

# AI対話データをデータベースに保存する関数
def save_ai_conversation(user_id, user_message, ai_response):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO ai_conversations (user_id, user_message, ai_response)
            VALUES (%s, %s, %s)
        ''', (user_id, user_message, ai_response))
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info("AI conversation saved successfully.")
    except psycopg2.Error as e:
        app.logger.error(f"Database error: {e}")
        raise

# OpenAI APIを使用してAI応答を生成する関数
def get_ai_response(user_message):
    prompt = f"従業員が仕事の悩みについて話しています。次のメッセージにどのように応答しますか？\n\n従業員: {user_message}\nAI:"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150
    )
    return response.choices[0].message['content'].strip()

# AIがユーザーに質問する関数
def get_ai_question():
    prompt = "従業員の仕事の悩みを引き出すための質問をしてください。"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=100
    )
    return response.choices[0].message['content'].strip()

# モチベーションを上げるメッセージを生成する関数
def generate_motivation_message():
    prompt = "Provide an inspirational and motivational message to help an employee start their day positively."
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=100
    )
    return response.choices[0].message['content'].strip()

# スケジュールタスク
scheduler = BackgroundScheduler()

# 毎朝3時にWebアプリケーション側の従業員データを消去
def reset_employee_data():
    global employee_data
    employee_data = {
        "名前": None,
        "勤務日": None,
        "出勤時間": None,
        "退勤時間": None,
        "休憩時間": None,
        "業務内容サマリ": None,
    }
    app.logger.info("Employee data reset successfully.")

scheduler.add_job(reset_employee_data, 'cron', hour=3)

# 毎朝7時に挨拶と昨日の勤怠情報を促すメッセージをPush
def send_morning_message():
    if current_user_id is not None:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            yesterday = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
            motivation_message = generate_motivation_message()
            message = f"おはようございます！{motivation_message} 昨日（{yesterday}）の勤怠情報を教えてください。今日も一日頑張りましょう！"
            line_bot_api.push_message(PushMessageRequest(
                to=current_user_id,
                messages=[TextMessage(text=message)]
            ))
        app.logger.info("Morning message sent successfully.")

scheduler.add_job(send_morning_message, 'cron', hour=7)

scheduler.start()

# ステップを管理する関数
def handle_step(user_message, user_id):
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
                current_step = "AI対話モード"
            except psycopg2.Error as e:
                app.logger.error(f"Failed to save data: {e}")
                current_step = "業務内容サマリ"
    elif current_step == "AI対話モード":
        ai_response = get_ai_response(user_message)  # OpenAI APIを使用してAI応答を生成
        save_ai_conversation(user_id, user_message, ai_response)
        return ai_response
    app.logger.info(f"Updated step: {current_step}")

# 各ステップごとに適切な質問を送信する関数
def ask_next_question(reply_token, message=None):
    global current_step
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if message:
            response_message = message
        elif current_step == "start":
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
        elif current_step == "AI対話モード":
            response_message = get_ai_question()

        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=response_message)]
        ))

# 初回メッセージ送信をトリガーするためにユーザーからのメッセージをハンドリング
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    global current_step, current_user_id
    reply_token = event.reply_token
    user_message = event.message.text.strip()
    current_user_id = event.source.user_id

    app.logger.info(f"Received message: {user_message}")
    app.logger.info(f"Current employee_data: {employee_data}")
    app.logger.info(f"Current step: {current_step}")

    ai_response = handle_step(user_message, current_user_id)
    ask_next_question(reply_token, ai_response)

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
    app.logger.info("Testing database connection.")
    test_database_connection()  # データベース接続をテスト
    app.logger.info("Creating table if not exists.")
    create_table()  # テーブルを作成
    app.run(host="0.0.0.0", port=8000, debug=True)
