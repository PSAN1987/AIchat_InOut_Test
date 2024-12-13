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
import logging
import traceback
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

# ユーザごとの勤怠入力状態と休暇入力状態を保持する辞書
user_states = {}

# データベースに保存する処理
def save_attendance_to_db(state, user_id):
    try:
        # データベースに保存
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
        conn.commit()  # コミットすることでデータベースに保存される
        cur.close()
        conn.close()
        return True
    except Exception as e:
        # エラー内容をログに記録
        logger.error(f"Failed to save attendance: {e}")
        logger.error(traceback.format_exc())
        return False

import re
from datetime import datetime

# バリデーション関数
def validate_date(input_date):
    """
    日付入力を検証し、YYYY-MM-DD形式に変換する。
    """
    try:
        # 例: 20240101 -> 2024-01-01
        if re.match(r"^\d{8}$", input_date):  # 8桁の場合
            return datetime.strptime(input_date, "%Y%m%d").strftime("%Y-%m-%d")
        # 例: 2024-01-01 はそのまま
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", input_date):  # 正しい形式の場合
            return input_date
        else:
            return None  # 無効な形式
    except ValueError:
        return None  # 無効な日付

def validate_time(input_time):
    """
    時間入力を検証し、HH:MM形式に変換する。
    """
    try:
        # 例: 0800 -> 08:00
        if re.match(r"^\d{4}$", input_time):  # 4桁の場合
            return datetime.strptime(input_time, "%H%M").strftime("%H:%M")
        # 例: 8:00 -> 08:00 または 800 -> 08:00
        elif re.match(r"^\d{1,2}:\d{2}$", input_time) or re.match(r"^\d{1,3}$", input_time):
            time_obj = datetime.strptime(input_time.zfill(4), "%H%M")
            return time_obj.strftime("%H:%M")
        else:
            return None  # 無効な形式
    except ValueError:
        return None  # 無効な時間

# 修正された勤怠入力ステップ関数
def process_step(user_id, user_input):
    state = user_states.get(user_id, {"step": 0})
    step = state.get("step", 0)

    if step == 1:
        state["name"] = user_input
        reply_text = "勤務日を入力してください (YYYY-MM-DD) 例 2024-01-01:"
        state["step"] = 2
    elif step == 2:
        work_day = validate_date(user_input)
        if work_day:
            state["work_day"] = work_day
            reply_text = "出勤時間を入力してください (HH:MM) 例 8:00:"
            state["step"] = 3
        else:
            reply_text = "無効な勤務日です。もう一度入力してください (YYYY-MM-DD) 例 2024-01-01:"
    elif step == 3:
        work_start = validate_time(user_input)
        if work_start:
            state["work_start"] = work_start
            reply_text = "退勤時間を入力してください (HH:MM) 例 17:00:"
            state["step"] = 4
        else:
            reply_text = "無効な出勤時間です。もう一度入力してください (HH:MM) 例 8:00:"
    elif step == 4:
        work_end = validate_time(user_input)
        if work_end:
            state["work_end"] = work_end
            reply_text = "休憩開始時間を入力してください (HH:MM) 例 12:00:"
            state["step"] = 5
        else:
            reply_text = "無効な退勤時間です。もう一度入力してください (HH:MM) 例 17:00:"
    elif step == 5:
        break_start = validate_time(user_input)
        if break_start:
            state["break_start"] = break_start
            reply_text = "休憩終了時間を入力してください (HH:MM) 例 13:00:"
            state["step"] = 6
        else:
            reply_text = "無効な休憩開始時間です。もう一度入力してください (HH:MM) 例 12:00:"
    elif step == 6:
        break_end = validate_time(user_input)
        if break_end:
            state["break_end"] = break_end
            reply_text = "業務日報を入力してください 例 アプリ開発:"
            state["step"] = 7
        else:
            reply_text = "無効な休憩終了時間です。もう一度入力してください (HH:MM) 例 13:00:"
    elif step == 7:
        state["work_summary"] = user_input
        state["device"] = "SP"  # デバイスを "SP" に設定
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
    return reply_text


# 休暇入力ステップの処理関数
def process_vacation_step(user_id, user_input):
    state = user_states.get(user_id, {"vacation_step": 0})
    step = state.get("vacation_step", 0)

    if step == 1:
        state["vacation_date"] = user_input
        reply_text = "休暇の種類を選択してください (全日休, 午前休, 午後休):"
        state["vacation_step"] = 2
    elif step == 2:
        state["vacation_type"] = user_input
        reply_text = f"確認してください:\n休暇日: {state['vacation_date']}\n休暇種類: {state['vacation_type']}\nこの内容でよろしいですか? (y/n) 例 y"
        state["vacation_step"] = 3
    elif step == 3:
        if user_input.lower() == 'y':
            # データベースに保存
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO vacation (vacation_date, vacation_type, line_id) VALUES (%s, %s, %s)",
                    (state["vacation_date"], state["vacation_type"], user_id)
                )
                conn.commit()
                cur.close()
                conn.close()
                reply_text = "休暇情報が保存されました。"
                state["vacation_step"] = 0  # 状態をリセット
            except Exception as e:
                logger.error(f"Failed to save vacation: {e}")
                logger.error(traceback.format_exc())
                reply_text = "休暇情報の保存に失敗しました。もう一度お試しください。"
        else:
            reply_text = "もう一度最初から入力してください。休暇日を入力してください (YYYY-MM-DD):"
            state["vacation_step"] = 1

    user_states[user_id] = state
    return reply_text

# メッセージイベントの処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    if user_input == "勤怠":
        # 勤怠入力モードに入る
        user_states[user_id] = {"step": 1, "mode": "attendance"}
        reply_text = "勤怠入力モードに入りました。名前を入力してください:"
    elif user_input == "休暇":
        # 休暇入力モードに入る
        user_states[user_id] = {"vacation_step": 1, "mode": "vacation"}
        reply_text = "休暇入力モードに入りました。休暇日を入力してください (YYYY-MM-DD):"
    elif user_id in user_states and user_states[user_id].get("step", 0) > 0:
        # 勤怠入力ステップの処理を続ける
        reply_text = process_step(user_id, user_input)
    elif user_id in user_states and user_states[user_id].get("vacation_step", 0) > 0:
        # 休暇入力ステップの処理を続ける
        reply_text = process_vacation_step(user_id, user_input)
    else:
        # 勤怠または休暇入力モードに入っていない場合、一般的なメッセージに対応
        reply_text = "勤怠または休暇情報を入力する場合は、「勤怠」または「休暇」というメッセージを書いてください。"

    # メッセージを返信
    reply_message = ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text=reply_text)]
    )
    messaging_api.reply_message(reply_message)

# LINEからのリクエストを処理
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    # リクエストの検証
    try:
        handler.handle(request.get_data(as_text=True), signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

if __name__ == "__main__":
    app.run(port=8000)
