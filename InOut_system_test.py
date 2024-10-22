# -*- coding: utf-8 -*-
import os
import psycopg2
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent
)
import logging
import traceback

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

# LINE bot APIの設定
config = Configuration(
    access_token=CHANNEL_ACCESS_TOKEN,
)
api_client = ApiClient(configuration=config)
messaging_api = MessagingApi(api_client=api_client)
handler = WebhookHandler(CHANNEL_SECRET)

# データベース接続のための関数
def get_db_connection():
    conn = psycopg2.connect(
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
        host=DATABASE_HOST,
        port=DATABASE_PORT
    )
    return conn

# ユーザごとの勤怠入力状態を保持する辞書
user_states = {}

# 勤務日選択 (YYYY-MM-DD)
def create_date_flex_message():
    flex_message = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "勤務日を選んでください:",
                    "wrap": True
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "action": {
                                "type": "datetimepicker",
                                "label": "勤務日を選択",
                                "data": "work_day",
                                "mode": "date",
                                "initial": "2024-10-22",
                                "min": "2024-01-01",
                                "max": "2025-12-31"
                            }
                        }
                    ]
                }
            ]
        }
    }
    return FlexMessage(alt_text="勤務日選択", contents=flex_message)

# 出勤時間、退勤時間、休憩開始時間、休憩終了時間選択 (HH:MM)
def create_time_flex_message(label, data):
    flex_message = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"{label}を選んでください:",
                    "wrap": True
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "action": {
                                "type": "datetimepicker",
                                "label": f"{label}を選択",
                                "data": data,
                                "mode": "time",
                                "initial": "08:00",
                                "min": "00:00",
                                "max": "23:59"
                            }
                        }
                    ]
                }
            ]
        }
    }
    return FlexMessage(alt_text=f"{label}選択", contents=flex_message)

# 業務日報入力 (テキストボックス)
def create_work_summary_flex_message():
    flex_message = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "業務日報を入力してください:",
                    "wrap": True
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "テキストボックスに業務日報を入力してください。"
                        }
                    ]
                }
            ]
        }
    }
    return FlexMessage(alt_text="業務日報入力", contents=flex_message)

# 勤怠情報をデータベースに保存する関数
def save_attendance_to_db(state, user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO attendance (name, work_day, work_start, work_end, break_start, break_end, work_summary, device, line_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                state["name"], state["work_day"], state["work_start"], state["work_end"],
                state["break_start"], state["break_end"], state["work_summary"],
                state["device"], user_id
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save attendance: {e}")
        logger.error(traceback.format_exc())
        return False

# 勤怠入力ステップの処理関数
def process_step(user_id, user_input):
    state = user_states.get(user_id, {"step": 0})
    step = state.get("step", 0)

    if step == 1:
        state["name"] = user_input
        reply_flex_message = create_date_flex_message()
        state["step"] = 2
    elif step == 2:
        state["work_day"] = user_input
        reply_flex_message = create_time_flex_message("出勤時間", "work_start")
        state["step"] = 3
    elif step == 3:
        state["work_start"] = user_input
        reply_flex_message = create_time_flex_message("退勤時間", "work_end")
        state["step"] = 4
    elif step == 4:
        state["work_end"] = user_input
        reply_flex_message = create_time_flex_message("休憩開始時間", "break_start")
        state["step"] = 5
    elif step == 5:
        state["break_start"] = user_input
        reply_flex_message = create_time_flex_message("休憩終了時間", "break_end")
        state["step"] = 6
    elif step == 6:
        state["break_end"] = user_input
        reply_flex_message = create_work_summary_flex_message()
        state["step"] = 7
    elif step == 7:
        state["work_summary"] = user_input
        state["device"] = "SP"
        reply_text = (
            f"確認してください:\n"
            f"名前: {state['name']}\n"
            f"勤務日: {state['work_day']}\n"
            f"出勤時間: {state['work_start']}\n"
            f"退勤時間: {state['work_end']}\n"
            f"休憩開始時間: {state['break_start']}\n"
            f"休憩終了時間: {state['break_end']}\n"
            f"業務日報: {state['work_summary']}\n"
            f"勤怠打刻デバイス: {state['device']}\n"
            "この内容でよろしいですか? (Y/N) 例 Y"
        )
        state["step"] = 8
        return reply_text, None
    elif step == 8:
        if user_input.lower() == 'y':
            if save_attendance_to_db(state, user_id):
                reply_text = "勤怠情報が保存されました。"
                state["step"] = 0
            else:
                reply_text = "勤怠情報の保存に失敗しました。もう一度お試しください。"
        else:
            reply_text = "もう一度最初から入力してください。名前を入力してください:"
            state["step"] = 1

    user_states[user_id] = state
    return reply_text, reply_flex_message

# メッセージイベントの処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    if user_input == "勤怠":
        user_states[user_id] = {"step": 1, "mode": "attendance"}
        reply_text = "勤怠入力モードに入りました。名前を入力してください:"
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )
    elif user_id in user_states and user_states[user_id].get("step", 0) > 0:
        reply_text, reply_flex_message = process_step(user_id, user_input)
        if reply_flex_message:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[reply_flex_message]
                )
            )
        else:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    else:
        reply_text = "勤怠または休暇情報を入力する場合は、「勤怠」または「休暇」というメッセージを書いてください。"
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# LINEからのリクエストを処理
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    try:
        handler.handle(request.get_data(as_text=True), signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

if __name__ == "__main__":
    app.run(port=8000)
