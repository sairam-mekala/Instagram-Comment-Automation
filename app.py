import os
import json
import time
import logging
import requests

from flask import Flask, request, jsonify


# ============================================================
# CONFIG
# ============================================================

ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
IG_USERNAME = os.getenv("IG_USERNAME")

GRAPH_VERSION = "v26.0"
GRAPH_URL = f"https://graph.instagram.com/{GRAPH_VERSION}"

RETRY_DELAY = 2
MAX_RETRIES = 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

app = Flask(__name__)


# ============================================================
# BASIC VALIDATION
# ============================================================

if not ACCESS_TOKEN:
    raise RuntimeError("INSTAGRAM_ACCESS_TOKEN is missing")

if not VERIFY_TOKEN:
    raise RuntimeError("VERIFY_TOKEN is missing")

if not IG_USERNAME:
    raise RuntimeError("IG_USERNAME is missing")


# ============================================================
# LOAD RULES FROM RENDER ENVIRONMENT VARIABLE
# ============================================================

def load_rules():
    raw_rules = os.getenv("RULES_JSON")

    if not raw_rules:
        raise RuntimeError("RULES_JSON environment variable is missing")

    try:
        rules = json.loads(raw_rules)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"RULES_JSON contains invalid JSON: {e}")

    if not isinstance(rules, list):
        raise RuntimeError("RULES_JSON must contain a JSON array")

    return rules


# ============================================================
# RULE VALIDATION
# ============================================================

def validate_rules(rules):
    errors = []

    for i, rule in enumerate(rules):
        prefix = f"Rule {i + 1}"

        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        # ----------------------------------------------------
        # Mandatory fields
        # ----------------------------------------------------

        for field in ["enabled", "reel", "trigger", "comment", "dm"]:
            if field not in rule:
                errors.append(f"{prefix}: missing '{field}'")

        if "enabled" in rule:
            if rule["enabled"] not in ["on", "off"]:
                errors.append(
                    f"{prefix}: enabled must be 'on' or 'off'"
                )

        if "reel" in rule and not isinstance(rule["reel"], str):
            errors.append(f"{prefix}: reel must be a string")

        if "trigger" in rule and not isinstance(rule["trigger"], str):
            errors.append(f"{prefix}: trigger must be a string")

        if "comment" in rule and not isinstance(rule["comment"], str):
            errors.append(f"{prefix}: comment must be a string")

        # ----------------------------------------------------
        # DM validation
        # ----------------------------------------------------

        if "dm" not in rule:
            continue

        dm = rule["dm"]

        if not isinstance(dm, dict):
            errors.append(f"{prefix}: dm must be an object")
            continue

        if "type" not in dm:
            errors.append(
                f"{prefix}: dm.type is required"
            )
            continue

        dm_type = dm["type"]

        if dm_type == "text":

            if not dm.get("text"):
                errors.append(
                    f"{prefix}: text DM requires 'text'"
                )

        elif dm_type == "link":

            if not dm.get("text"):
                errors.append(
                    f"{prefix}: link DM requires 'text'"
                )

            if not dm.get("button"):
                errors.append(
                    f"{prefix}: link DM requires 'button'"
                )

            if not dm.get("url"):
                errors.append(
                    f"{prefix}: link DM requires 'url'"
                )

        elif dm_type == "follow_gate":

            if not dm.get("text"):
                errors.append(
                    f"{prefix}: follow_gate requires 'text'"
                )

            if not dm.get("button"):
                errors.append(
                    f"{prefix}: follow_gate requires 'button'"
                )

            not_following = dm.get("not_following")

            if not isinstance(not_following, dict):
                errors.append(
                    f"{prefix}: follow_gate requires 'not_following'"
                )
            else:
                if not not_following.get("text"):
                    errors.append(
                        f"{prefix}: not_following requires 'text'"
                    )

                if not not_following.get("profile_button"):
                    errors.append(
                        f"{prefix}: not_following requires "
                        "'profile_button'"
                    )

                if not not_following.get("check_button"):
                    errors.append(
                        f"{prefix}: not_following requires "
                        "'check_button'"
                    )

            final = dm.get("final")

            if not isinstance(final, dict):
                errors.append(
                    f"{prefix}: follow_gate requires 'final'"
                )
            else:
                if not final.get("text"):
                    errors.append(
                        f"{prefix}: final requires 'text'"
                    )

                if not final.get("button"):
                    errors.append(
                        f"{prefix}: final requires 'button'"
                    )

                if not final.get("url"):
                    errors.append(
                        f"{prefix}: final requires 'url'"
                    )

        else:
            errors.append(
                f"{prefix}: invalid dm.type '{dm_type}'. "
                "Use text, link, or follow_gate"
            )

    if errors:
        for error in errors:
            logging.error(error)

        raise RuntimeError(
            "RULES_JSON validation failed"
        )


RULES = load_rules()
validate_rules(RULES)

logging.info(
    "Loaded %d valid automation rule(s)",
    len(RULES)
)


# ============================================================
# INSTAGRAM ACCOUNT INFO
# ============================================================

IG_USER_ID = None

MEDIA_CACHE = {}


def get_ig_user_id():
    global IG_USER_ID

    if IG_USER_ID:
        return IG_USER_ID

    url = f"{GRAPH_URL}/me"

    params = {
        "fields": "id,username",
        "access_token": ACCESS_TOKEN
    }

    response = api_request(
        "GET",
        url,
        params=params
    )

    if not response:
        raise RuntimeError(
            "Unable to retrieve Instagram account information"
        )

    IG_USER_ID = response["id"]

    logging.info(
        "Instagram account resolved: %s (%s)",
        response.get("username"),
        IG_USER_ID
    )

    return IG_USER_ID


# ============================================================
# GENERIC GRAPH API REQUEST
# ============================================================

def api_request(
    method,
    url,
    params=None,
    json_data=None,
    retry=True
):
    attempts = 1 + (MAX_RETRIES if retry else 0)

    for attempt in range(attempts):

        try:
            if method.upper() == "GET":

                response = requests.get(
                    url,
                    params=params,
                    timeout=20
                )

            else:

                response = requests.post(
                    url,
                    params=params,
                    json=json_data,
                    timeout=20
                )

            if response.ok:
                try:
                    return response.json()
                except Exception:
                    return {}

            logging.error(
                "Graph API error: %s %s",
                response.status_code,
                response.text
            )

        except requests.RequestException as e:

            logging.error(
                "Request error: %s",
                e
            )

        if attempt < attempts - 1:

            logging.warning(
                "Retrying request in %s seconds...",
                RETRY_DELAY
            )

            time.sleep(RETRY_DELAY)

    return None


# ============================================================
# GET MEDIA PERMALINK
# ============================================================

def get_media_permalink(media_id):

    if media_id in MEDIA_CACHE:
        return MEDIA_CACHE[media_id]

    url = f"{GRAPH_URL}/{media_id}"

    params = {
        "fields": "id,permalink",
        "access_token": ACCESS_TOKEN
    }

    data = api_request(
        "GET",
        url,
        params=params
    )

    if not data:
        return None

    permalink = data.get("permalink")

    if permalink:
        MEDIA_CACHE[media_id] = permalink

    return permalink


# ============================================================
# REEL MATCHING
# ============================================================

def normalize_reel_url(url):

    if not url:
        return ""

    url = url.strip()

    if url.endswith("/"):
        url = url[:-1]

    return url


def reel_matches(rule_reel, media_id):

    if rule_reel == "*":
        return True

    permalink = get_media_permalink(media_id)

    if not permalink:
        logging.error(
            "Could not resolve permalink for media %s",
            media_id
        )
        return False

    return (
        normalize_reel_url(rule_reel)
        ==
        normalize_reel_url(permalink)
    )


# ============================================================
# TRIGGER MATCHING
# ============================================================

def trigger_matches(rule_trigger, comment_text):

    if rule_trigger == "*":
        return True

    if not comment_text:
        return False

    return rule_trigger.lower() in comment_text.lower()


# ============================================================
# RULE PRIORITY
# ============================================================

def rule_priority(rule):

    reel = rule.get("reel")
    trigger = rule.get("trigger")

    if reel != "*" and trigger != "*":
        return 4

    if reel != "*" and trigger == "*":
        return 3

    if reel == "*" and trigger != "*":
        return 2

    return 1


def find_matching_rule(media_id, comment_text):

    matches = []

    for index, rule in enumerate(RULES):

        if rule.get("enabled") != "on":
            continue

        if not reel_matches(
            rule.get("reel"),
            media_id
        ):
            continue

        if not trigger_matches(
            rule.get("trigger"),
            comment_text
        ):
            continue

        matches.append(
            (
                rule_priority(rule),
                index,
                rule
            )
        )

    if not matches:
        return None

    matches.sort(
        key=lambda x: (-x[0], x[1])
    )

    priority, index, rule = matches[0]

    logging.info(
        "Matched Rule %s (priority %s)",
        index + 1,
        priority
    )

    return rule


# ============================================================
# PUBLIC COMMENT REPLY
# ============================================================

def reply_to_comment(comment_id, message):

    url = f"{GRAPH_URL}/{comment_id}/replies"

    params = {
        "access_token": ACCESS_TOKEN
    }

    data = {
        "message": message
    }

    response = api_request(
        "POST",
        url,
        params=params,
        json_data=data
    )

    if response:
        logging.info(
            "Public reply status: success"
        )
        logging.info(
            "Public reply response: %s",
            response
        )
        return True

    logging.error(
        "Public reply failed"
    )

    return False


# ============================================================
# SEND REGULAR TEXT DM
# ============================================================

def send_text_dm(user_id, text):

    url = f"{GRAPH_URL}/me/messages"

    params = {
        "access_token": ACCESS_TOKEN
    }

    data = {
        "recipient": {
            "id": user_id
        },
        "message": {
            "text": text
        }
    }

    response = api_request(
        "POST",
        url,
        params=params,
        json_data=data
    )

    if response:
        logging.info(
            "DM status: success"
        )
        logging.info(
            "DM response: %s",
            response
        )
        return True

    logging.error(
        "DM failed"
    )

    return False


# ============================================================
# SEND BUTTON DM
# ============================================================

def send_button_dm(
    user_id,
    text,
    button_title,
    payload
):

    url = f"{GRAPH_URL}/me/messages"

    params = {
        "access_token": ACCESS_TOKEN
    }

    data = {
        "recipient": {
            "id": user_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": [
                        {
                            "type": "postback",
                            "title": button_title,
                            "payload": payload
                        }
                    ]
                }
            }
        }
    }

    response = api_request(
        "POST",
        url,
        params=params,
        json_data=data
    )

    if response:
        logging.info(
            "Button DM sent: %s",
            response
        )
        return True

    logging.error(
        "Button DM failed"
    )

    return False


# ============================================================
# SEND URL BUTTON DM
# ============================================================

def send_url_button_dm(
    user_id,
    text,
    button_title,
    url
):

    graph_url = f"{GRAPH_URL}/me/messages"

    params = {
        "access_token": ACCESS_TOKEN
    }

    data = {
        "recipient": {
            "id": user_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": url,
                            "title": button_title
                        }
                    ]
                }
            }
        }
    }

    response = api_request(
        "POST",
        graph_url,
        params=params,
        json_data=data
    )

    if response:
        logging.info(
            "URL button DM sent: %s",
            response
        )
        return True

    logging.error(
        "URL button DM failed"
    )

    return False


# ============================================================
# FOLLOW STATUS
# ============================================================

def check_following(user_id):

    url = f"{GRAPH_URL}/{user_id}"

    params = {
        "fields": "id,username,name,is_user_follow_business",
        "access_token": ACCESS_TOKEN
    }

    response = api_request(
        "GET",
        url,
        params=params
    )

    if not response:
        logging.error(
            "Could not check follow status for %s",
            user_id
        )
        return None

    following = response.get(
        "is_user_follow_business"
    )

    logging.info(
        "PROFILE CHECK STATUS: success"
    )

    logging.info(
        "PROFILE CHECK RESPONSE: %s",
        response
    )

    return bool(following)


# ============================================================
# HARD-CODED INTERNAL PAYLOADS
# ============================================================

def make_payload(rule_index):
    return f"AUTO_SEND_LINK_{rule_index}"


def make_follow_check_payload(rule_index):
    return f"AUTO_CHECK_FOLLOW_{rule_index}"


# ============================================================
# PROFILE URL
# ============================================================

def get_profile_url():

    username = IG_USERNAME.strip().lstrip("@")

    return f"https://www.instagram.com/{username}/"


# ============================================================
# DIRECT LINK DM
# ============================================================

def send_link_dm(
    user_id,
    dm,
    rule_index
):

    return send_url_button_dm(
        user_id=user_id,
        text=dm["text"],
        button_title=dm["button"],
        url=dm["url"]
    )


# ============================================================
# FOLLOW GATE
# ============================================================

def send_follow_gate_start(
    user_id,
    dm,
    rule_index
):

    following = check_following(user_id)

    if following is None:
        logging.error(
            "Unable to determine follow status"
        )
        return False

    if following:

        logging.info(
            "User is already following. "
            "Sending final link."
        )

        final = dm["final"]

        return send_url_button_dm(
            user_id=user_id,
            text=final["text"],
            button_title=final["button"],
            url=final["url"]
        )

    payload = make_follow_check_payload(
        rule_index
    )

    not_following = dm["not_following"]

    profile_url = get_profile_url()

    sent = send_button_dm(
        user_id=user_id,
        text=not_following["text"],
        button_title=not_following["check_button"],
        payload=payload
    )

    if not sent:
        return False

    return True


# ============================================================
# INITIAL FOLLOW-GATE MESSAGE
# ============================================================

def send_follow_gate_initial(
    user_id,
    dm,
    rule_index
):

    payload = make_follow_check_payload(
        rule_index
    )

    return send_button_dm(
        user_id=user_id,
        text=dm["text"],
        button_title=dm["button"],
        payload=payload
    )


# ============================================================
# FOLLOW-GATE NOT FOLLOWING MESSAGE
# ============================================================

def send_not_following_message(
    user_id,
    dm,
    rule_index
):

    not_following = dm["not_following"]

    profile_url = get_profile_url()

    check_payload = make_follow_check_payload(
        rule_index
    )

    url = f"{GRAPH_URL}/me/messages"

    params = {
        "access_token": ACCESS_TOKEN
    }

    data = {
        "recipient": {
            "id": user_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": not_following["text"],
                    "buttons": [
                        {
                            "type": "web_url",
                            "title": not_following["profile_button"],
                            "url": profile_url
                        },
                        {
                            "type": "postback",
                            "title": not_following["check_button"],
                            "payload": check_payload
                        }
                    ]
                }
            }
        }
    }

    response = api_request(
        "POST",
        url,
        params=params,
        json_data=data
    )

    if response:
        logging.info(
            "Follow gate message sent: %s",
            response
        )
        return True

    logging.error(
        "Follow gate message failed"
    )

    return False


# ============================================================
# FINAL FOLLOW-GATE MESSAGE
# ============================================================

def send_final_link(
    user_id,
    dm
):

    final = dm["final"]

    return send_url_button_dm(
        user_id=user_id,
        text=final["text"],
        button_title=final["button"],
        url=final["url"]
    )


# ============================================================
# PROCESS DM RULE
# ============================================================

def process_dm(
    user_id,
    rule,
    rule_index
):

    dm = rule["dm"]

    dm_type = dm["type"]

    # --------------------------------------------------------
    # TYPE 1: REGULAR TEXT
    # --------------------------------------------------------

    if dm_type == "text":

        return send_text_dm(
            user_id,
            dm["text"]
        )

    # --------------------------------------------------------
    # TYPE 2: DIRECT LINK
    # --------------------------------------------------------

    if dm_type == "link":

        return send_link_dm(
            user_id,
            dm,
            rule_index
        )

    # --------------------------------------------------------
    # TYPE 3: FOLLOW GATE
    # --------------------------------------------------------

    if dm_type == "follow_gate":

        return send_follow_gate_start(
            user_id,
            dm,
            rule_index
        )

    logging.error(
        "Unknown DM type: %s",
        dm_type
    )

    return False


# ============================================================
# FIND RULE INDEX
# ============================================================

def get_rule_index(rule):

    for index, current_rule in enumerate(RULES):

        if current_rule is rule:
            return index + 1

    return 1


# ============================================================
# HANDLE COMMENT
# ============================================================

def handle_comment(
    username,
    user_id,
    comment_text,
    comment_id,
    media_id
):

    logging.info("")
    logging.info("--- COMMENT RECEIVED ---")
    logging.info("Username: %s", username)
    logging.info("User ID: %s", user_id)
    logging.info("Comment: %s", comment_text)
    logging.info("Comment ID: %s", comment_id)
    logging.info("Media ID: %s", media_id)
    logging.info("------------------------")

    rule = find_matching_rule(
        media_id,
        comment_text
    )

    if not rule:

        logging.info(
            "No matching rule."
        )

        return

    rule_index = get_rule_index(rule)

    logging.info(
        "TRIGGER MATCHED: %s",
        rule.get("trigger")
    )

    # --------------------------------------------------------
    # PUBLIC COMMENT
    # --------------------------------------------------------

    comment_sent = reply_to_comment(
        comment_id,
        rule["comment"]
    )

    if not comment_sent:
        logging.error(
            "Failed to post public reply."
        )

    # --------------------------------------------------------
    # DM
    # --------------------------------------------------------

    dm_sent = process_dm(
        user_id,
        rule,
        rule_index
    )

    if not dm_sent:
        logging.error(
            "Failed to send DM for Rule %s",
            rule_index
        )


# ============================================================
# HANDLE BUTTON / POSTBACK
# ============================================================

def handle_postback(
    user_id,
    payload
):

    logging.info("")
    logging.info("--- BUTTON CLICKED ---")
    logging.info("User ID: %s", user_id)
    logging.info("Payload: %s", payload)
    logging.info("----------------------")

    prefix = "AUTO_CHECK_FOLLOW_"

    if not payload.startswith(prefix):
        logging.info(
            "Unknown payload. Ignoring."
        )
        return

    value = payload[len(prefix):]

    try:
        rule_index = int(value)
    except ValueError:
        logging.error(
            "Invalid rule index in payload: %s",
            payload
        )
        return

    if rule_index < 1 or rule_index > len(RULES):
        logging.error(
            "Rule index out of range: %s",
            rule_index
        )
        return

    rule = RULES[rule_index - 1]

    if rule.get("enabled") != "on":
        logging.info(
            "Rule is disabled. Ignoring button."
        )
        return

    dm = rule.get("dm", {})

    if dm.get("type") != "follow_gate":
        logging.error(
            "Payload points to a non-follow-gate rule."
        )
        return

    following = check_following(user_id)

    if following is None:

        logging.error(
            "Follow check failed for user %s",
            user_id
        )

        return

    if following:

        logging.info(
            "User is following. Sending final link."
        )

        send_final_link(
            user_id,
            dm
        )

    else:

        logging.info(
            "User is still not following. "
            "Sending follow message again."
        )

        send_not_following_message(
            user_id,
            dm,
            rule_index
        )


# ============================================================
# WEBHOOK VERIFICATION
# ============================================================

@app.route(
    "/webhook",
    methods=["GET"]
)
def verify_webhook():

    mode = request.args.get(
        "hub.mode"
    )

    token = request.args.get(
        "hub.verify_token"
    )

    challenge = request.args.get(
        "hub.challenge"
    )

    if (
        mode == "subscribe"
        and token == VERIFY_TOKEN
    ):

        logging.info(
            "Webhook verification successful."
        )

        return challenge, 200

    logging.warning(
        "Webhook verification failed."
    )

    return "Forbidden", 403


# ============================================================
# WEBHOOK
# ============================================================

@app.route(
    "/webhook",
    methods=["POST"]
)
def webhook():

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "status": "ignored"
        }), 200

    logging.info(
        "Webhook received."
    )

    try:

        # ====================================================
        # INSTAGRAM COMMENT WEBHOOK
        # ====================================================

        for entry in data.get(
            "entry",
            []
        ):

            changes = entry.get(
                "changes",
                []
            )

            for change in changes:

                field = change.get(
                    "field"
                )

                value = change.get(
                    "value",
                    {}
                )

                if field != "comments":
                    continue

                comment_id = value.get(
                    "id"
                )

                comment_text = value.get(
                    "text",
                    ""
                )

                media = value.get(
                    "media",
                    {}
                )

                media_id = media.get(
                    "id"
                )

                from_user = value.get(
                    "from",
                    {}
                )

                user_id = from_user.get(
                    "id"
                )

                username = from_user.get(
                    "username",
                    "unknown"
                )

                if not comment_id:
                    continue

                if not media_id:
                    logging.error(
                        "Comment webhook missing media ID."
                    )
                    continue

                if not user_id:
                    logging.error(
                        "Comment webhook missing user ID."
                    )
                    continue

                handle_comment(
                    username=username,
                    user_id=user_id,
                    comment_text=comment_text,
                    comment_id=comment_id,
                    media_id=media_id
                )

        # ====================================================
        # INSTAGRAM MESSAGE WEBHOOK
        # ====================================================

        for entry in data.get(
            "entry",
            []
        ):

            messaging_events = entry.get(
                "messaging",
                []
            )

            for event in messaging_events:

                sender = event.get(
                    "sender",
                    {}
                )

                user_id = sender.get(
                    "id"
                )

                if not user_id:
                    continue

                message = event.get(
                    "message"
                )

                if not message:
                    continue

                # ------------------------------------------------
                # POSTBACK FROM BUTTON
                # ------------------------------------------------

                quick_reply = message.get(
                    "quick_reply"
                )

                if quick_reply:

                    payload = quick_reply.get(
                        "payload"
                    )

                    if payload:
                        handle_postback(
                            user_id,
                            payload
                        )

                # ------------------------------------------------
                # POSTBACK DIRECTLY ON EVENT
                # ------------------------------------------------

                postback = event.get(
                    "postback"
                )

                if postback:

                    payload = postback.get(
                        "payload"
                    )

                    if payload:
                        handle_postback(
                            user_id,
                            payload
                        )

        return jsonify({
            "status": "ok"
        }), 200

    except Exception as e:

        logging.exception(
            "Webhook processing error: %s",
            e
        )

        # Always return 200 so Meta does not repeatedly
        # resend the webhook because of an internal exception.
        return jsonify({
            "status": "error"
        }), 200


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return jsonify({
        "status": "running",
        "service": "Instagram Comment Automation"
    })


# ============================================================
# LOCAL / RENDER ENTRY POINT
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
