#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import sqlite3
import datetime
import hashlib
import secrets
import threading
import time
import json
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === Cau hinh ===
BOT_TOKEN        = os.getenv("BOT_TOKEN")
ADMIN_ID         = int(os.getenv("ADMIN_ID", "0"))
ADMIN_IDS        = [ADMIN_ID]

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://your-render-url.onrender.com")
DB_PATH          = "vipbot.db"

VUOTLINK1_REWARD = 400
VUOTLINK1_LIMIT  = 5
VUOTLINK2_REWARD = 300
VUOTLINK2_LIMIT  = 1000

flask_app = Flask(__name__)
db_lock   = threading.Lock()

# Bien toan cuc cho bot loop va PTB app
bot_loop = None
ptb_app  = None


# === Database ===

def get_conn():
    # FIX: check_same_thread=False bat buoc khi dung SQLite da luong
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                balance    INTEGER DEFAULT 0,
                points     INTEGER DEFAULT 0,
                last_daily TEXT    DEFAULT ''
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS vuotlink_tokens (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER,
                link_type  TEXT,
                reward     INTEGER,
                status     TEXT      DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS device_limits (
                ip        TEXT,
                link_type TEXT,
                count     INTEGER DEFAULT 0,
                PRIMARY KEY(ip, link_type)
            )"""
        )
        conn.commit()
        conn.close()


init_db()


def add_user(user_id, username=""):
    # FIX: username co the la None, ep ve chuoi rong
    if username is None:
        username = ""
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
            (user_id, username)
        )
        conn.commit()
        conn.close()


def make_token(user_id, link_type):
    raw = "{}:{}:{}".format(user_id, link_type, secrets.token_hex(16))
    return hashlib.sha256(raw.encode()).hexdigest()


def get_real_ip():
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return ip or request.remote_addr or "unknown"


# === Flask routes ===

@flask_app.route("/")
def index():
    return jsonify({"status": "running"})


@flask_app.route("/done/<token>")
def done(token):
    ip = get_real_ip()

    # FIX: dong conn ngay sau khi doc xong, tranh connection leak
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM vuotlink_tokens WHERE token=?", (token,))
        row = c.fetchone()
        conn.close()

    if not row:
        return "Invalid token", 404

    if row["status"] == "approved":
        return "Already used", 200

    # FIX: dung total_seconds() thay vi .seconds
    # .seconds chi tra 0-59 nen khong bao gio > 600
    created_at = datetime.datetime.fromisoformat(str(row["created_at"]))
    elapsed = (datetime.datetime.now() - created_at).total_seconds()
    if elapsed > 600:
        return "Expired", 200

    link_type = row["link_type"]
    if link_type == "vuotlink1":
        limit = VUOTLINK1_LIMIT
    else:
        limit = VUOTLINK2_LIMIT

    with db_lock:
        conn = get_conn()
        c = conn.cursor()

        c.execute(
            "SELECT count FROM device_limits WHERE ip=? AND link_type=?",
            (ip, link_type)
        )
        r = c.fetchone()
        count = r["count"] if r else 0

        if count >= limit:
            conn.close()
            return "Limit reached", 200

        if r:
            c.execute(
                "UPDATE device_limits SET count=count+1 WHERE ip=? AND link_type=?",
                (ip, link_type)
            )
        else:
            c.execute(
                "INSERT INTO device_limits (ip, link_type, count) VALUES (?,?,1)",
                (ip, link_type)
            )

        c.execute(
            "UPDATE vuotlink_tokens SET status='approved' WHERE token=?",
            (token,)
        )
        c.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (row["user_id"],)
        )
        c.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (row["reward"], row["user_id"])
        )
        conn.commit()
        conn.close()

    return "OK", 200


# FIX: Nhan update tu Telegram qua webhook (thay vi polling)
@flask_app.route("/webhook", methods=["POST"])
def webhook():
    global ptb_app, bot_loop
    if ptb_app is None or bot_loop is None:
        return "Bot not ready", 503
    data   = request.get_json(force=True)
    update = Update.de_json(data, ptb_app.bot)
    # Day coroutine vao event loop cua bot thread mot cach an toan
    future = asyncio.run_coroutine_threadsafe(
        ptb_app.process_update(update),
        bot_loop
    )
    future.result(timeout=30)
    return "OK", 200


# === Bot handlers ===

async def start(update, context):
    user = update.effective_user
    add_user(user.id, user.username)
    await update.message.reply_text("Bot da hoat dong!")


async def vuotlink_handler(update, context, link_type, reward):
    user = update.effective_user
    add_user(user.id, user.username)

    token       = make_token(user.id, link_type)
    destination = "{}/done/{}".format(WEBHOOK_BASE_URL, token)

    with db_lock:
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "INSERT INTO vuotlink_tokens (token, user_id, link_type, reward) VALUES (?,?,?,?)",
            (token, user.id, link_type, reward)
        )
        conn.commit()
        conn.close()

    await update.message.reply_text("Link cua ban: {}".format(destination))


async def vuotlink1(update, context):
    await vuotlink_handler(update, context, "vuotlink1", VUOTLINK1_REWARD)


async def vuotlink2(update, context):
    await vuotlink_handler(update, context, "vuotlink2", VUOTLINK2_REWARD)


# === Khoi dong bot trong thread rieng ===

async def _start_ptb():
    global ptb_app, bot_loop
    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start",     start))
    ptb_app.add_handler(CommandHandler("vuotlink1", vuotlink1))
    ptb_app.add_handler(CommandHandler("vuotlink2", vuotlink2))

    await ptb_app.initialize()
    # Dang ky webhook voi Telegram
    webhook_url = "{}/webhook".format(WEBHOOK_BASE_URL)
    await ptb_app.bot.set_webhook(url=webhook_url)
    await ptb_app.start()
    print("[BOT] Webhook da duoc dat: {}".format(webhook_url))


def run_bot_thread():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(_start_ptb())
    # Giu loop song de xu ly update lien tuc
    bot_loop.run_forever()


# === Entry point ===

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("Thieu bien moi truong BOT_TOKEN!")

    t = threading.Thread(target=run_bot_thread, daemon=True)
    t.start()

    # Cho PTB khoi tao xong truoc khi Flask nhan request
    time.sleep(3)

    port = int(os.environ.get("PORT", 5000))
    # use_reloader=False: tranh Flask fork process thu 2 lam bot chay doi
    # threaded=True: Flask xu ly nhieu request dong thoi
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
