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

# Load .env file
load_dotenv()

# Assign environment variables to variables
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Set OpenAI API key
openai.api_key = OPENAI_API_KEY

# Instantiate Flask app
app = Flask(__name__)

# Load LINE access token
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Function to get response from OpenAI API
def get_chat_response(prompt, model="gpt-4"):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": prompt}]
    )
    return response.choices[0].message['content']

# Create table if not exists
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

# Save employee data to database
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

# Initialize employee data dictionary
employee_data = {
    "名前": None,
    "日時": None,
    "出勤時間": None,
    "退勤時間": None,
    "休憩時間": None,
    "業務内容サマリ": None
}

# Callback function
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# Send a message when a friend is added
@handler.add(FollowEvent)
def handle_follow(event):
    # Instantiate API client
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # Reply
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text='Thank You!')]
        ))

# Echo back received messages
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # Instantiate API client
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        user_message = event.message.text
        reply_token = event.reply_token

        if employee_data["名前"] is None:
            employee_data["名前"] = user_message
            response_message = "出勤時間を教えてください（例：09:00）。"
        
        elif employee_data["出勤時間"] is None:
            try:
                employee_data["出勤時間"] = datetime.strptime(user_message, "%H:%M")
                response_message = "退勤時間を教えてください（例：18:00）。"
            except ValueError:
                response_message = "時間の形式が正しくありません。再度入力してください。出勤時間を教えてください（例：09:00）。"

        elif employee_data["退勤時間"] is None:
            try:
                employee_data["退勤時間"] = datetime.strptime(user_message, "%H:%M")
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

            # Reset employee_data for next user
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
    app.run()
