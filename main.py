#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔥 Super‑fast Twilio ⇆ Telegram bot (Bengali)

✓ যেকোনো ফরম্যাটের নাম্বার বুঝে নাম্বার কেনা
✓ Bangla message system
✓ Auto OTP receive
✓ Manual View SMS button
✓ Twilio number auto-delete on new purchase or logout
✓ Works great on Termux + nohup
✓ skip_pending=True so old updates are ignored at startup
✓ Designed for up to ~5k concurrent users
"""

import re
import random
import threading
import time
from datetime import datetime, timedelta

import telebot
from telebot import types
from twilio.rest import Client

BOT_TOKEN = "7948853748:AAEMvSWQbNcTOJKrQq52afyLFtRlqixfW5M"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

user_session: dict[int, dict] = {}
GROUP_ID = -1002762500349
CANADA_AREA_CODES = [
    "204", "236", "249", "250", "289", "306", "343", "365", "387", "403", "416",
    "418", "431", "437", "438", "450", "506", "514", "519", "548", "579", "581",
    "587", "604", "613", "639", "647", "672", "705", "709", "742", "778", "780",
    "782", "807", "819", "825", "867", "873", "902", "905",
]

def extract_otp(text: str) -> str:
    m = re.search(r"\b(\d{3}-\d{3}|\d{6})\b", text)
    return m.group(1) if m else "N/A"

def forward_to_group(html_text: str) -> None:
    try:
        bot.send_message(GROUP_ID, html_text)
    except Exception as exc:
        print("[WARN] গ্রুপে ফরওয়ার্ড করতে সমস্যা:", exc)

def run_async(func):
    def wrapper(*args, **kwargs):
        threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True).start()
    return wrapper

def is_user_logged_in(uid: int) -> bool:
    return uid in user_session and "twilio_client" in user_session[uid]

def _stop_sms_listener(sess: dict):
    stopper = sess.get("sms_stop_evt")
    if stopper:
        stopper.set()
    sess.pop("sms_thread", None)
    sess.pop("sms_stop_evt", None)
    sess.pop("last_msg_sid", None)

def _start_sms_listener(uid: int, chat_id: int):
    sess = user_session[uid]
    _stop_sms_listener(sess)
    stop_evt = threading.Event()
    sess["sms_stop_evt"] = stop_evt
    sess["last_msg_sid"] = None
    client: Client = sess["twilio_client"]
    number = sess["purchased_number"]

    def poll():
        while not stop_evt.is_set():
            try:
                msgs = client.messages.list(to=number, limit=1)
                if msgs:
                    latest = msgs[0]
                    if sess.get("last_msg_sid") != latest.sid:
                        sess["last_msg_sid"] = latest.sid
                        _send_formatted_sms(chat_id, latest, number)
            except Exception as e:
                print("[SMS‑Poll] Error:", e)
            finally:
                stop_evt.wait(5)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    sess["sms_thread"] = t

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    bot.reply_to(msg, "🧾 আপনার Twilio SID এবং Token এইভাবে পাঠান:\nACxxxx tokenxxxx\n\n🔏 উদাহরণ:\nAC123... token123...")

@bot.message_handler(commands=["login"])
def cmd_login(msg):
    bot.reply_to(msg, "🔏 অনুগ্রহ করে Twilio SID এবং Token পাঠান এইভাবে:\nACxxx tokenxxx")

@bot.message_handler(commands=["logout"])
@run_async
def cmd_logout(msg):
    uid = msg.from_user.id
    if not is_user_logged_in(uid):
        bot.reply_to(msg, "❗️ আপনি এখনও লগইন করেননি।")
        return

    sess = user_session[uid]
    client: Client = sess["twilio_client"]
    old_num = sess.get("purchased_number")
    _stop_sms_listener(sess)

    try:
        if old_num:
            for num in client.incoming_phone_numbers.list():
                if num.phone_number == old_num:
                    client.incoming_phone_numbers(num.sid).delete()
                    break
    except Exception:
        pass

    user_session.pop(uid, None)
    bot.send_message(msg.chat.id, "😀 লগআউট সফল\n/login দিয়ে আবার লগইন করুন। 🤔")

@bot.message_handler(commands=["buy"])
def cmd_buy(msg):
    if not is_user_logged_in(msg.from_user.id):
        bot.reply_to(msg, "🔏 প্রথমে SID দিয়ে লগইন করুন। 🤒 ")
        return
    bot.send_message(msg.chat.id, "📟 ৩ সংখ্যার এরিয়া কোড দিন (যেমনঃ 825):")

@bot.message_handler(commands=["random"])
def cmd_random(msg):
    if not is_user_logged_in(msg.from_user.id):
        bot.reply_to(msg, "🔏 প্রথমে SID দিয়ে লগইন করুন। 🤒 ")
        return
    area_code = random.choice(CANADA_AREA_CODES)
    bot.send_message(msg.chat.id, f"🎰 র‍্যান্ডম এরিয়া কোড: {area_code} ☺️ ")
    _send_area_code_numbers(msg.from_user.id, msg.chat.id, area_code)

@bot.message_handler(commands=["returnsms"])
@run_async
def cmd_returnsms(msg):
    uid = msg.from_user.id
    if not is_user_logged_in(uid):
        bot.reply_to(msg, "🔏 প্রথমে /login করুন।")
        return
    sess = user_session[uid]
    client: Client = sess["twilio_client"]
    number = sess.get("purchased_number")
    if not number:
        bot.reply_to(msg, "❗️ আপনি এখনো কোনো নাম্বার কিনেননি।")
        return
    try:
        since = datetime.utcnow() - timedelta(hours=1)
        messages = client.messages.list(to=number, date_sent_after=since)
        if not messages:
            bot.send_message(msg.chat.id, "📭 মেসেজ পাওয়া যায়নি অপেক্ষা করুন। 😋 ")
            return
        _send_formatted_sms(msg.chat.id, messages[0], number)
    except Exception:
        bot.send_message(msg.chat.id, "😭 আপনার Twilio Sid নষ্ট হয়ে গেছে।")

cred_pattern = re.compile(r"^(AC[a-zA-Z0-9]{32})\s+([a-zA-Z0-9]{32,})$")

@bot.message_handler(func=lambda m: cred_pattern.match(m.text or ""))
@run_async
def handle_login(msg):
    try:
        sid, token = msg.text.strip().split()
        client = Client(sid, token)
        client.api.accounts(sid).fetch()
        user_session[msg.from_user.id] = {
            "twilio_client": client,
            "sid": sid,
            "token": token,
            "purchased_number": None,
        }
        bot.send_message(msg.chat.id, "💐 লগইন হয়েছে!\nএখন নাম্বার পেতে /buy লিখুন অথবা শুধু এরিয়া কোড পাঠান। 🫠 ")
    except Exception:
        bot.send_message(msg.chat.id, "🚫 লগইন ব্যর্থ হয়েছে। SID নষ্ট হয়ে গেছে দয়াকরে অন্য SID দিন। 😏 ")

@bot.message_handler(func=lambda m: re.fullmatch(r"\d{3}", m.text or ""))
def handle_area_code(msg):
    if not is_user_logged_in(msg.from_user.id):
        bot.reply_to(msg, "🔏 আগে /login দিয়ে লগইন করুন। 🥱 ")
        return
    _send_area_code_numbers(msg.from_user.id, msg.chat.id, msg.text.strip())

def convert_bangla_digits(text):
    bangla_digits = "০১২৩৪৫৬৭৮৯"
    eng_digits = "0123456789"
    return text.translate(str.maketrans(bangla_digits, eng_digits))

@bot.message_handler(func=lambda m: True)
def handle_number_or_fallback(msg):
    if not is_user_logged_in(msg.from_user.id):
        bot.reply_to(msg, "🔏 আগে /login দিয়ে লগইন করুন। 🥱 ")
        return

    text = convert_bangla_digits(msg.text or "")
    digits_only = re.sub(r"\D", "", text)

    if len(digits_only) < 10:
        bot.reply_to(msg, "🌟 দয়া করে সঠিক তথ্য দিন।\nTwilio SID/Token, এরিয়া কোড, বা নাম্বার দিন ❣️")
        return

    digits_only = digits_only[-11:] if len(digits_only) > 11 else digits_only
    if not digits_only.startswith("1"):
        digits_only = "1" + digits_only

    if len(digits_only) != 11:
        bot.reply_to(msg, "❌ সঠিক নাম্বার নয়। অনুগ্রহ করে একটি বৈধ কানাডিয়ান নাম্বার দিন।")
        return

    number = "+" + digits_only
    user_session[msg.from_user.id]["pending_number"] = number
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🛍️ BUY", callback_data="buy_manual"))
    bot.send_message(msg.chat.id, f"📞 আপনি নাম্বারটি কিনতে চান: {number}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "buy_manual")
@run_async
def cb_buy_manual(call):
    if not is_user_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❣️ দয়াকরে লগইন করুন। 🤫 ")
        return
    sess = user_session[call.from_user.id]
    client: Client = sess["twilio_client"]
    number = sess.get("pending_number")
    _stop_sms_listener(sess)
    old = sess.get("purchased_number")

    try:
        if old:
            for n in client.incoming_phone_numbers.list():
                if n.phone_number == old:
                    client.incoming_phone_numbers(n.sid).delete()
                    break
    except Exception:
        pass

    try:
        client.incoming_phone_numbers.create(phone_number=number)
        sess["purchased_number"] = number
        _start_sms_listener(call.from_user.id, call.message.chat.id)

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 View SMS", callback_data="viewsms"))
        bot.send_message(call.message.chat.id, f"🍀 অভিনন্দন! আপনি সফলভাবে নাম্বারটি ক্রয় করেছেন 🌟 : {number}", reply_markup=kb)
    except Exception as exc:
        bot.send_message(call.message.chat.id, f"🍁 নাম্বার কেনা যায়নি 😝।\n{exc}")

@bot.callback_query_handler(func=lambda c: c.data == "viewsms")
@run_async
def cb_viewsms(call):
    if not is_user_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 লগইন নেই দয়াকরে লগইন করুন। 🥺 ")
        return
    sess = user_session[call.from_user.id]
    client: Client = sess["twilio_client"]
    number = sess.get("purchased_number")
    try:
        msgs = client.messages.list(to=number, limit=1)
        if not msgs:
            bot.send_message(call.message.chat.id, "📭 কোনো মেসেজ পাওয়া যায়নি অপেক্ষা করুন। 😋 ")
            return
        _send_formatted_sms(call.message.chat.id, msgs[0], number)
    except Exception:
        bot.send_message(call.message.chat.id, "😭 আপনার Twilio Sid নষ্ট হয়ে গেছে। 😝 ")

@run_async
def _send_area_code_numbers(uid: int, chat_id: int, area_code: str):
    sess = user_session[uid]
    client: Client = sess["twilio_client"]
    try:
        numbers = client.available_phone_numbers("CA").local.list(area_code=area_code, limit=30)
        if not numbers:
            bot.send_message(chat_id, f"🫠 এরিয়া কোডের {area_code} জন্য কোনো নাম্বার পাওয়া যায়নি। 🥴 ")
            return
        bot.send_message(chat_id, f"🧮 ৩০টি নাম্বার ({area_code} পাওয়া গেছে): 🫣 ")
        for num in numbers:
            bot.send_message(chat_id, num.phone_number)
        bot.send_message(chat_id, "")
    except Exception as exc:
        bot.send_message(chat_id, f"🤗 এরিয়া কোডের নাম্বার পাওয়া যাচ্ছে না 🥲।\n{exc}")

def _send_formatted_sms(chat_id: int, msg_obj, number: str):
    otp = extract_otp(msg_obj.body)
    html = (
        f"⏰ Time: {msg_obj.date_sent}\n"
        f"☎ Number: <code>{number}</code>\n"
        f"🌐 Country: 🌟 🇨🇦 🌟 \n"
        f"🔑 Main OTP: <code>{otp}</code>\n"
        f"📮 Full Message:\n<blockquote>{msg_obj.body}</blockquote>\n\n"
        "👑 BOT OWNER: @ShrabonAhmed"
    )
    bot.send_message(chat_id, html)
    forward_to_group(html)

print("🤖 Bot is running…")
if __name__ == "__main__":
    bot.infinity_polling(none_stop=True, timeout=0, skip_pending=True)