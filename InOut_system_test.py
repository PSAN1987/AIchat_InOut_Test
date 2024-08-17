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

# 勤怠入力ステップの処理関数
def process_step(user_id, user_input):
    state = user_states.get(user_id, {"step": 0})
    step = state.get("step", 0)

    if step == 1:
        state["name"] = user_input
        reply_text = "出勤日を入力してください (YYYY-MM-DD) 例 2024-01-01:"
        state["step"] = 2
    elif step == 2:
        state["work_date"] = user_input
        reply_text = "出勤時間を入力してください (HH:MM) 例 8:00:"
        state["step"] = 3
    elif step == 3:
        state["check_in_time"] = user_input
        reply_text = "退勤時間を入力してください (HH:MM) 例 17:00:"
        state["step"] = 4
    elif step == 4:
        state["check_out_time"] = user_input
        reply_text = "休憩時間を入力してください (HH:MM) 例 1:00:"
        state["step"] = 5
    elif step == 5:
        state["break_time"] = user_input
        reply_text = "業務サマリを入力してください 例 アプリ開発:"
        state["step"] = 6
    elif step == 6:
        state["work_summary"] = user_input
        reply_text = f"確認してください:\n名前: {state['name']}\n出勤日: {state['work_date']}\n出勤時間: {state['check_in_time']}\n退勤時間: {state['check_out_time']}\n休憩時間: {state['break_time']}\n業務サマリ: {state['work_summary']}\nこの内容でよろしいですか? (Y/N) 例 Y"
        state["step"] = 7
    elif step == 7:
        if user_input.lower() == 'y':
            # データベースに保存
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO attendance (name, work_date, check_in_time, check_out_time, break_time, work_summary, line_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (state["name"], state["work_date"], state["check_in_time"], state["check_out_time"], state["break_time"], state["work_summary"], user_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            reply_text = "勤怠情報が保存されました。"
            state["step"] = 0  # 状態をリセットして勤怠入力モードから抜ける
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
        reply_text = f"確認してください:\n休暇日: {state['vacation_date']}\n休暇種類: {state['vacation_type']}\nこの内容でよろしいですか? (Y/N) 例 Y"
        state["vacation_step"] = 3
    elif step == 3:
        if user_input.lower() == 'y':
            # データベースに保存
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
            state["vacation_step"] = 0  # 状態をリセットして休暇入力モードから抜ける
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
