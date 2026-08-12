import os
import json
import requests
from dotenv import load_dotenv
from flask import Flask, request

load_dotenv()

ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
VERIFY_TOKEN = "instagram_test_token"

IG_USER_ID = "27884946851148261"
IG_WEBHOOK_USER_ID = "17841442834056441"

with open("rules.json", "r", encoding="utf-8") as f:
    RULES = json.load(f)

app = Flask(__name__)


def reply_to_comment(comment_id, message):
    url = f"https://graph.instagram.com/v26.0/{comment_id}/replies"

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "message": message
        }
    )

    print("Public reply status:", response.status_code)
    print("Public reply response:", response.text)

    return response


def send_private_reply(comment_id, message):
    url = f"https://graph.instagram.com/v26.0/{IG_USER_ID}/messages"

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "recipient": {
                "comment_id": comment_id
            },
            "message": {
                "text": message
            }
        }
    )

    print("DM status:", response.status_code)
    print("DM response:", response.text)

    return response


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue

            value = change.get("value", {})

            comment_id = value.get("id")
            comment = value.get("text", "")
            username = value.get("from", {}).get("username")
            user_id = value.get("from", {}).get("id")
            media_id = value.get("media", {}).get("id")

            if user_id == IG_WEBHOOK_USER_ID:
                continue

            print("\n--- COMMENT RECEIVED ---")
            print("Username:", username)
            print("User ID:", user_id)
            print("Comment:", comment)
            print("Comment ID:", comment_id)
            print("Media ID:", media_id)
            print("------------------------")

            comment_lower = comment.lower()

            for rule in RULES:
                if rule["enabled"].lower() != "on":
                    continue

                if rule["trigger"].lower() in comment_lower:
                    print("TRIGGER DETECTED:", rule["trigger"])

                    reply_to_comment(
                        comment_id,
                        rule["comment"]
                    )

                    send_private_reply(
                        comment_id,
                        rule["dm"]
                    )

                    break

    return "OK", 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)
