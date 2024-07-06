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
            messages=[TextMessage(text='こんにちは！お名前を教えてください。')]
        ))

# 初期設定
employee_data = {
    "名前": None,
    "出勤時間": None,
    "退勤時間": None,
    "休憩時間": None,
    "業務内容サマリ": None,
    "日時": None
}

# メッセージ受信時の処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # APIクライアントのインスタンス化
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        user_message = event.message.text
        reply_token = event.reply_token

        # 勤怠情報収集ロジック
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
            response_message = "勤怠情報を保存しました。ありがとうございました。次に、今日の業務についてお話しましょう。"

            # 勤怠情報が保存されたらリセット
            for key in employee_data.keys():
                employee_data[key] = None

            # 勤怠情報保存メッセージをユーザーに送信
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=response_message)]
            ))
            return

        else:
            response_message = "勤怠情報が既に保存されています。"

        # 勤怠情報収集メッセージをユーザーに返信
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=response_message)]
        ))

# AI応答を処理する別のハンドラを追加
@handler.add(MessageEvent, message=TextMessageContent)
def handle_ai_message(event):
    if all(value is not None for value in employee_data.values()):
        user_message = event.message.text
        reply_token = event.reply_token

        # AI応答を生成
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "あなたは役に立つアシスタントです。今日の業務の議論について集中してください。"},
                {"role": "user", "content": user_message}
            ]
        )
        ai_message = response.choices[0].message["content"]

        # AI応答メッセージをユーザーに送信
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=ai_message)]
            ))

# 最初にユーザーにメッセージを送信
def send_initial_message(user_id):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        initial_message = "名前を教えてください。"
        line_bot_api.push_message(PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=initial_message)]
        ))


if __name__ == "__main__":
    create_table()
    app.run(debug=True, host='0.0.0.0', port=5000)

    # Top page for checking if the bot is running
@app.route('/', methods=['GET'])
def toppage():
    return 'Hello world!'

# Bot startup code
if __name__ == "__main__":
    # Set `debug=True` for local testing
    app.run(host="0.0.0.0", port=8000, debug=True)

