
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

# 勤怠入力ステップの処理関数
def process_step(user_id, user_input):
    state = user_states.get(user_id, {"step": 0})
    step = state.get("step", 0)

    if step == 1:
        state["name"] = user_input
        reply_text = "勤務日を入力してください (YYYY-MM-DD) 例 2024-01-01:"
        state["step"] = 2
    elif step == 2:
        state["work_day"] = user_input
        reply_text = "出勤時間を入力してください (HH:MM) 例 8:00:"
        state["step"] = 3
    elif step == 3:
        state["work_start"] = user_input
        reply_text = "退勤時間を入力してください (HH:MM) 例 17:00:"
        state["step"] = 4
    elif step == 4:
        state["work_end"] = user_input
        reply_text = "休憩開始時間を入力してください (HH:MM) 例 12:00:"
        state["step"] = 5
    elif step == 5:
        state["break_start"] = user_input
        reply_text = "休憩終了時間を入力してください (HH:MM) 例 13:00:"
        state["step"] = 6
    elif step == 6:
        state["break_end"] = user_input
        reply_text = "業務日報を入力してください 例 アプリ開発:"
        state["step"] = 7
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
            # データベースに保存を試みる
            if save_attendance_to_db(state, user_id):
                reply_text = "勤怠情報が保存されました。"
                state["step"] = 0  # 状態をリセット
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
        reply_text = f"確認してください:\n休暇日: {state['vacation_date']}\n休暇種類: {state['vacation_type']}\nこの内容でよろしいですか? (Y/N) 例 Y"
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


# Adding imports specific for rich menu
from linebot.v3.messaging import RichMenuRequest, RichMenuArea, RichMenuBounds, RichMenuSize, RichMenuAction

# Define function to create the rich menu with Attendance and Vacation modes
def create_rich_menu(client):
    # Create a rich menu with Attendance and Vacation mode options
    rich_menu_request = RichMenuRequest(
        size=RichMenuSize(width=2500, height=843),  # Standard size for a full-width rich menu
        selected=True,
        name="Attendance-Vacation Mode Menu",
        chat_bar_text="Select Mode",
        areas=[
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=1250, height=843),  # Left half for Attendance Mode
                action=RichMenuAction(
                    type="postback",
                    data="mode=attendance",
                    display_text="Attendance Mode"
                )
            ),
            RichMenuArea(
                bounds=RichMenuBounds(x=1251, y=0, width=1250, height=843),  # Right half for Vacation Mode
                action=RichMenuAction(
                    type="postback",
                    data="mode=vacation",
                    display_text="Vacation Mode"
                )
            )
        ]
    )

    # Send request to create the rich menu
    rich_menu_id = client.create_rich_menu(rich_menu_request).rich_menu_id

    # Set the rich menu as the default for users
    client.set_default_rich_menu(rich_menu_id)
    print("Rich menu created and set as default.")

# Initialize the LINE Messaging API client
client = MessagingApi(ApiClient(Configuration(access_token=CHANNEL_ACCESS_TOKEN)))

# Call create_rich_menu to ensure the rich menu is available when the app starts
create_rich_menu(client)

# Handling user postback event to switch between attendance and vacation modes
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(PostbackEvent)
def handle_postback(event):
    # Detecting the selected mode from the postback data
    if event.postback.data == "mode=attendance":
        response_text = "Switched to Attendance Mode."
        # Set the application state to attendance mode (you may need to adjust state handling logic here)
    elif event.postback.data == "mode=vacation":
        response_text = "Switched to Vacation Mode."
        # Set the application state to vacation mode (you may need to adjust state handling logic here)
    else:
        response_text = "Unknown command."

    # Reply to the user
    client.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=response_text)]
        )
    )
