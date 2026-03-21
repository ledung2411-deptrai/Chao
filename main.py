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
BOT_TOKEN        = os.getenv("8504510484:AAFp55RNutB0bzATABwiuW5pAKtYgKS5hL0")
ADMIN_ID         = int(os.getenv("8175673206", "0"))
ADMIN_IDS        = [ADMIN_ID]

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://chao-6sag.onrender.com")
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

def init_db():
    with db_lock:
        conn = get_conn()
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            last_daily TEXT DEFAULT ''
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS vuotlink_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            link_type TEXT,
            reward INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS device_limits (
            ip TEXT,
            link_type TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY(ip, link_type)
        )""")

        conn.commit()
        conn.close()

init_db()

def add_user(user_id, username=""):
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))
        conn.commit()
        conn.close()

def make_token(user_id, link_type):
    raw = f"{user_id}:{link_type}:{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_real_ip():
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return ip or request.remote_addr or "unknown"

# ── Flask routes ──────────────────────────────────────────────────────────────
@flask_app.route("/")
def index():
    return {"status": "running"}

@flask_app.route("/done/<token>")
def done(token):
    ip = get_real_ip()

    # FIX 3 & 4: dùng một conn/cursor duy nhất cho toàn bộ hàm,
    # đảm bảo conn luôn được đóng dù return ở bất kỳ đâu
    with db_lock:
        conn = get_conn()
        try:
            c = conn.cursor()

            c.execute("SELECT * FROM vuotlink_tokens WHERE token=?", (token,))
            row = c.fetchone()

            if not row:
                return "Invalid token", 404

            if row["status"] == "approved":
                return "Already used"

            created_at = datetime.datetime.fromisoformat(row["created_at"])
            # FIX 5: dùng total_seconds() thay vì .seconds
            # .seconds chỉ trả về phần giây (0-59), không phải tổng giây
            if (datetime.datetime.now() - created_at).total_seconds() > 600:
                return "Expired"

            link_type = row["link_type"]
            limit = VUOTLINK1_LIMIT if link_type == "vuotlink1" else VUOTLINK2_LIMIT

            c.execute("SELECT count FROM device_limits WHERE ip=? AND link_type=?", (ip, link_type))
            r = c.fetchone()
            count = r["count"] if r else 0

            if count >= limit:
                return "Limit reached"

            if r:
                c.execute(
                    "UPDATE device_limits SET count=count+1 WHERE ip=? AND link_type=?",
                    (ip, link_type)
                )
            else:
                c.execute(
                    "INSERT INTO device_limits (ip,link_type,count) VALUES(?,?,1)",
                    (ip, link_type)
                )

            c.execute("UPDATE vuotlink_tokens SET status='approved' WHERE token=?", (token,))
            c.execute("INSERT OR IGNORE INTO users (user_id) VALUES(?)", (row["user_id"],))
            c.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (row["reward"], row["user_id"])
            )
            conn.commit()
        finally:
            conn.close()   # FIX 3: luôn đóng conn dù có exception hay return sớm

    return "OK"

# ── Telegram handlers ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username)
    await update.message.reply_text("Bot đã hoạt động!")

async def vuotlink(update: Update, context: ContextTypes.DEFAULT_TYPE, link_type, reward):
    user = update.effective_user
    add_user(user.id, user.username)

    token = make_token(user.id, link_type)
    destination = f"{WEBHOOK_BASE_URL}/done/{token}"

    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO vuotlink_tokens (token,user_id,link_type,reward) VALUES(?,?,?,?)",
            (token, user.id, link_type, reward)
        )
        conn.commit()
        conn.close()

    await update.message.reply_text(f"Link của bạn: {destination}")

async def vuotlink1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await vuotlink(update, context, "vuotlink1", VUOTLINK1_REWARD)

async def vuotlink2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await vuotlink(update, context, "vuotlink2", VUOTLINK2_REWARD)

# ── Bot runner ────────────────────────────────────────────────────────────────
def run_bot():
    # FIX 6: PTB v20 không cho phép run_polling() bên trong asyncio.run() ở thread phụ
    # vì nó cố đăng ký signal handler (chỉ hoạt động ở main thread).
    # Giải pháp: tạo event loop riêng và điều khiển vòng đời bot thủ công.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("vuotlink1", vuotlink1))
        app.add_handler(CommandHandler("vuotlink2", vuotlink2))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Giữ bot chạy mãi (cho đến khi process bị kill)
        await asyncio.Event().wait()

    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()

# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # FIX 7: kiểm tra BOT_TOKEN trước khi khởi động để tránh lỗi tối nghĩa
    if not BOT_TOKEN:
        raise RuntimeError("Biến môi trường BOT_TOKEN chưa được đặt!")

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    # use_reloader=False bắt buộc khi chạy cùng thread phụ,
    # tránh Flask spawn process thứ 2 làm bot chạy đôi
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS tokens(
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        reward INTEGER,
        status TEXT,
        created TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS limits(
        ip TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ===== UI =====
SUCCESS = """
<h1>🎉 Thành công</h1>
<p>+{{ reward }}đ</p>
<p>Số dư: {{ balance }}đ</p>
"""

ERROR = """
<h1>❌ Lỗi</h1>
<p>Link không hợp lệ</p>
"""

# ===== HELPER =====
def create_token(uid):
    return hashlib.sha256(f"{uid}{secrets.token_hex(8)}".encode()).hexdigest()

def get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)

# ===== ROUTE =====
@app.route("/")
def home():
    return "BOT RUNNING"

@app.route("/done/<token>")
def done(token):
    ip = get_ip()

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM tokens WHERE token=?", (token,))
    row = c.fetchone()

    if not row:
        return render_template_string(ERROR)

    if row["status"] == "done":
        return "Đã dùng"

    created = datetime.datetime.fromisoformat(row["created"])
    if (datetime.datetime.now() - created).total_seconds() > 600:
        return "Hết hạn"

    c.execute("SELECT count FROM limits WHERE ip=?", (ip,))
    r = c.fetchone()
    count = r["count"] if r else 0

    if count >= LIMIT:
        return "Giới hạn"

    if r:
        c.execute("UPDATE limits SET count=count+1 WHERE ip=?", (ip,))
    else:
        c.execute("INSERT INTO limits VALUES (?,1)", (ip,))

    c.execute("UPDATE tokens SET status='done' WHERE token=?", (token,))
    c.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (row["user_id"],))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (row["reward"], row["user_id"]))

    conn.commit()

    c.execute("SELECT balance FROM users WHERE user_id=?", (row["user_id"],))
    balance = c.fetchone()["balance"]

    conn.close()

    return render_template_string(SUCCESS, reward=row["reward"], balance=balance)

# ===== TELEGRAM =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot chạy ngon 😎")

async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    token = create_token(user.id)
    url = f"{WEBHOOK_BASE_URL}/done/{token}"

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO tokens VALUES (?,?,?,?,?)",
              (token, user.id, REWARD, "pending", datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Link của bạn:\n{url}")

def run_bot():
    async def main():
        bot = Application.builder().token(BOT_TOKEN).build()
        bot.add_handler(CommandHandler("start", start))
        bot.add_handler(CommandHandler("link", link))
        await bot.run_polling()

    asyncio.run(main())

# ===== RUN =====
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)VUOTLINK2_LIMIT   = 1000

# ══════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════

import os
import asyncio
import sqlite3
import datetime
import hashlib
import secrets
import threading
import requests

import aiohttp
from flask import Flask, request, render_template_string
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

flask_app = Flask(__name__)

# ══════════════════════════════════════════
#  DATABASE — tự tạo khi khởi động
# ══════════════════════════════════════════

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT,
    balance INTEGER DEFAULT 0, points INTEGER DEFAULT 0,
    last_daily TEXT DEFAULT "")''')

c.execute("DROP TABLE IF EXISTS tasks")
c.execute('''CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY, title TEXT,
    description TEXT, reward INTEGER DEFAULT 0,
    task_type TEXT DEFAULT "normal")''')

FIXED_TASKS = [
    (1, "Tham Gia Nhóm Telegram", "t.me/hqhteam",                        500,  "normal"),
    (2, "Đăng Ký Kênh Youtube",   "https://youtube.com/@plahuydzvcl",     200,  "normal"),
    (3, "Theo Dõi Tiktok",        "https://tiktok.com/@plah.infinity",    200,  "normal"),
    (4, "Vượt Link 1",            f"Gõ /vuotlink1 — +{VUOTLINK1_REWARD}đ/lần (tối đa {VUOTLINK1_LIMIT} lần/thiết bị)", VUOTLINK1_REWARD, "vuot_link_1"),
    (5, "Vượt Link 2",            f"Gõ /vuotlink2 — +{VUOTLINK2_REWARD}đ/lần (tối đa {VUOTLINK2_LIMIT} lần/thiết bị)", VUOTLINK2_REWARD, "vuot_link_2"),
]
for t in FIXED_TASKS:
    c.execute("INSERT OR IGNORE INTO tasks (task_id,title,description,reward,task_type) VALUES(?,?,?,?,?)", t)

c.execute('''CREATE TABLE IF NOT EXISTS user_tasks (
    user_id INTEGER, task_id INTEGER, status TEXT DEFAULT "pending",
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, task_id))''')

c.execute('''CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY, reward INTEGER, is_active INTEGER DEFAULT 1)''')

c.execute('''CREATE TABLE IF NOT EXISTS user_codes (
    user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code))''')

c.execute('''CREATE TABLE IF NOT EXISTS withdraws (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
    status TEXT DEFAULT "pending", created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

c.execute('''CREATE TABLE IF NOT EXISTS vuotlink_tokens (
    token TEXT PRIMARY KEY, user_id INTEGER, link_type TEXT,
    reward INTEGER, status TEXT DEFAULT "pending",
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

c.execute('''CREATE TABLE IF NOT EXISTS device_limits (
    ip TEXT, link_type TEXT, count INTEGER DEFAULT 0,
    PRIMARY KEY(ip, link_type))''')

conn.commit()
print("[DB] ✅ Database sẵn sàng!")

# ══════════════════════════════════════════
#  HÀM HỖ TRỢ CHUNG
# ══════════════════════════════════════════

def add_user(user_id: int, username):
    c.execute("INSERT OR IGNORE INTO users (user_id,username) VALUES(?,?)", (user_id, username or ""))
    conn.commit()

def get_user(user_id: int):
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return c.fetchone()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def make_token(user_id: int, link_type: str) -> str:
    raw = f"{user_id}:{link_type}:{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]

def vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def notify_telegram(chat_id: int, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG Error] {e}")

# ══════════════════════════════════════════
#  FLASK — WEBHOOK (trang đích vượt link)
# ══════════════════════════════════════════

_CSS = """
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;
  background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:rgba(255,255,255,.07);backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.13);border-radius:26px;
  padding:44px;text-align:center;max-width:440px;width:100%;
  box-shadow:0 28px 72px rgba(0,0,0,.55);color:#fff}
.icon{font-size:70px;margin-bottom:10px;line-height:1}
h1{font-size:23px;font-weight:700;margin-bottom:6px}
.sub{color:rgba(255,255,255,.62);font-size:14px;line-height:1.65;margin:8px 0}
.reward{font-size:52px;font-weight:800;
  background:linear-gradient(90deg,#f9c74f,#f3722c);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:14px 0 6px}
.balance-box{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.28);
  border-radius:14px;padding:14px 20px;margin:16px 0;font-size:15px}
.balance-box strong{color:#4ade80;font-size:22px}
.progress-wrap{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);
  border-radius:14px;padding:13px 18px;margin:0 0 16px;font-size:13px;color:rgba(255,255,255,.55)}
.progress-wrap b{color:#fff}
.bar-track{background:rgba(255,255,255,.1);border-radius:99px;height:8px;margin-top:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#667eea,#764ba2)}
.btn{display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);
  color:#fff;text-decoration:none;padding:14px 36px;border-radius:50px;
  font-size:15px;font-weight:600;margin-top:12px;box-shadow:0 6px 24px rgba(102,126,234,.4)}
hr{border:none;border-top:1px solid rgba(255,255,255,.1);margin:20px 0}
.foot{margin-top:20px;font-size:11px;color:rgba(255,255,255,.25)}
.badge{display:inline-block;padding:3px 12px;border-radius:99px;font-size:12px;font-weight:600;margin-bottom:12px}
.green{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.3);color:#4ade80}
.yellow{background:rgba(251,191,36,.12);border:1px solid rgba(251,191,36,.3);color:#fbbf24}
.red{background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);color:#f87171}
</style>"""

PAGE_SUCCESS = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nhận Thưởng Thành Công</title>"""+_CSS+"""</head>
<body><div class="card">
  <div class="icon">🎉</div>
  <span class="badge green">✅ XÁC NHẬN THÀNH CÔNG</span>
  <h1 style="color:#4ade80">Nhận Thưởng Thành Công!</h1>
  <div class="reward">+{{ reward }}đ</div>
  <div class="balance-box">💰 Số dư tài khoản<br><strong>{{ balance }}đ</strong></div>
  <div class="progress-wrap">
    Lượt {{ lname }} đã dùng: <b>{{ used }}/{{ limit }}</b>
    <div class="bar-track"><div class="bar-fill" style="width:{{ pct }}%"></div></div>
    {% if used >= limit %}
    <div style="margin-top:7px;color:#f87171;font-size:12px">⚠️ Đã đạt giới hạn loại link này</div>
    {% endif %}
  </div>
  <p class="sub">Tiền thưởng đã cộng tự động vào tài khoản Telegram.<br>Quay lại bot để tiếp tục!</p>
  <hr><a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_USED = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đã Sử Dụng</title>"""+_CSS+"""</head>
<body><div class="card">
  <div class="icon">⚠️</div><span class="badge yellow">ĐÃ SỬ DỤNG</span>
  <h1 style="color:#f59e0b">Link Đã Được Dùng Rồi</h1>
  <p class="sub" style="margin-top:14px">Token này đã nhận thưởng rồi.<br>
  Mỗi link chỉ dùng <strong style="color:#fff">1 lần</strong>.<br><br>Tạo link mới trong bot!</p>
  <hr><a class="btn" href="https://t.me/{{ bot }}">🤖 Tạo Link Mới</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_LIMIT = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đã Đạt Giới Hạn</title>"""+_CSS+"""</head>
<body><div class="card">
  <div class="icon">🚫</div><span class="badge red">GIỚI HẠN THIẾT BỊ</span>
  <h1 style="color:#f87171">Đã Đạt Giới Hạn!</h1>
  <p class="sub" style="margin-top:14px">Thiết bị này đã vượt tối đa<br>
  <strong style="color:#fff;font-size:22px">{{ limit }} lần</strong><br>
  cho <strong style="color:#fff">{{ lname }}</strong>.<br><br>Thử loại link khác hoặc liên hệ admin.</p>
  <hr><a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_ERROR = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lỗi</title>"""+_CSS+"""</head>
<body><div class="card">
  <div class="icon">❌</div><span class="badge red">LỖI TOKEN</span>
  <h1 style="color:#f87171">Link Không Hợp Lệ</h1>
  <p class="sub" style="margin-top:14px">Link không tồn tại hoặc đã hết hạn.<br>Vui lòng tạo link mới từ bot.</p>
  <hr><a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

def get_real_ip():
    return (request.headers.get("X-Forwarded-For","").split(",")[0].strip()
            or request.remote_addr or "unknown")

def check_limit(ip, link_type):
    limit = VUOTLINK1_LIMIT if link_type == "vuotlink1" else VUOTLINK2_LIMIT
    c.execute("SELECT count FROM device_limits WHERE ip=? AND link_type=?", (ip, link_type))
    row   = c.fetchone()
    count = row["count"] if row else 0
    if count >= limit:
        return False, count, limit
    if row:
        c.execute("UPDATE device_limits SET count=count+1 WHERE ip=? AND link_type=?", (ip, link_type))
    else:
        c.execute("INSERT INTO device_limits (ip,link_type,count) VALUES(?,?,1)", (ip, link_type))
    conn.commit()
    return True, count + 1, limit

BOT_USERNAME = "your_bot"
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
    BOT_USERNAME = r.json()["result"]["username"]
    print(f"[BOT] ✅ @{BOT_USERNAME}")
except Exception:
    pass

@flask_app.route("/done/<token>")
def done(token):
    ip = get_real_ip()

    c.execute("SELECT user_id,link_type,reward,status FROM vuotlink_tokens WHERE token=?", (token,))
    row = c.fetchone()
    if not row:
        return render_template_string(PAGE_ERROR, bot=BOT_USERNAME), 404

    user_id   = row["user_id"]
    link_type = row["link_type"]
    reward    = row["reward"]
    status    = row["status"]
    lname     = "Vượt Link 1" if link_type == "vuotlink1" else "Vượt Link 2"

    if status == "approved":
        return render_template_string(PAGE_USED, bot=BOT_USERNAME), 200

    allowed, used, limit = check_limit(ip, link_type)
    if not allowed:
        return render_template_string(PAGE_LIMIT, limit=limit, lname=lname, bot=BOT_USERNAME), 429

    # Cộng tiền
    c.execute("UPDATE vuotlink_tokens SET status='approved' WHERE token=?", (token,))
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES(?)", (user_id,))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, user_id))
    conn.commit()

    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance = c.fetchone()["balance"]
    pct     = min(100, round(used / limit * 100))

    notify_telegram(
        user_id,
        f"✅ *Vượt link thành công!*\n"
        f"💰 Nhận: *+{vnd(reward)}đ*\n"
        f"🏦 Số dư: *{vnd(balance)}đ*\n"
        f"📊 Lượt: *{used}/{limit}*\n\n"
        f"👉 Gõ /vuotlink1 hoặc /vuotlink2 để tiếp tục!"
    )
    print(f"✅ IP={ip} | user={user_id} | {link_type} | +{reward}đ | {used}/{limit}")

    return render_template_string(
        PAGE_SUCCESS,
        reward=vnd(reward), balance=vnd(balance),
        used=used, limit=limit, pct=pct,
        lname=lname, bot=BOT_USERNAME,
    ), 200

@flask_app.route("/")
def index():
    return {"status": "running", "bot": f"@{BOT_USERNAME}", "version": "6.0"}

# ══════════════════════════════════════════
#  TELEGRAM BOT
# ══════════════════════════════════════════

async def _vuotlink(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    link_type, reward, api_url, api_key, limit):
    user = update.effective_user
    add_user(user.id, user.username)

    token       = make_token(user.id, link_type)
    destination = f"{WEBHOOK_BASE_URL}/done/{token}"

    c.execute(
        "INSERT OR REPLACE INTO vuotlink_tokens (token,user_id,link_type,reward,status) VALUES(?,?,?,?,'pending')",
        (token, user.id, link_type, reward),
    )
    conn.commit()

    await update.message.reply_text("⏳ Đang tạo link, vui lòng chờ...")

    try:
        params = {"api": api_key, "url": destination}
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json(content_type=None)

        ok   = data.get("status") in ("success", 1, "1", True, "true")
        link = (data.get("shortenedUrl") or data.get("short_link")
                or data.get("result") or data.get("url"))

        if ok and link:
            num = link_type[-1]
            await update.message.reply_text(
                f"🔗 *Link Vượt {num} của bạn:*\n\n"
                f"{link}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👆 Click → hoàn thành các bước\n"
                f"✅ *+{reward:,}đ tự động cộng* ngay sau khi xong!\n"
                f"⚠️ Giới hạn *{limit} lần* / thiết bị",
                parse_mode="Markdown",
            )
        else:
            err = data.get("message") or data.get("error") or str(data)
            await update.message.reply_text(f"❌ Tạo link thất bại: `{err}`\n\nLiên hệ /support",
                                            parse_mode="Markdown")
            c.execute("DELETE FROM vuotlink_tokens WHERE token=?", (token,))
            conn.commit()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Lỗi API: `{e}`", parse_mode="Markdown")
        c.execute("DELETE FROM vuotlink_tokens WHERE token=?", (token,))
        conn.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username)
    if context.args and context.args[0].isdigit():
        ref_id = int(context.args[0])
        if ref_id != user.id:
            c.execute("SELECT user_id FROM users WHERE user_id=?", (ref_id,))
            if c.fetchone():
                c.execute("UPDATE users SET balance=balance+100 WHERE user_id=?", (ref_id,))
                conn.commit()
                try:
                    notify_telegram(ref_id, f"🎉 Bạn vừa giới thiệu *{user.first_name}*! +100đ thưởng.")
                except Exception: pass
    await update.message.reply_text(
        f"👋 Xin chào *{user.first_name}*!\n\n"
        "🎉 Chào mừng đến với *BOT KIẾM TIỀN ONLINE*\n"
        "© Phát triển bởi *Lê Trung Dũng*\n\n"
        "⚡ Làm nhiệm vụ, vượt link để nhận tiền.\n"
        "💸 Rút tiền khi đạt tối thiểu *20.000đ*.\n\n"
        "📜 Gõ /menu để xem danh sách lệnh.",
        parse_mode="Markdown",
    )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Menu — Lê Trung Dũng Bot*\n\n"
        "👤 *Tài khoản:*\n"
        "  /start — Bắt đầu\n"
        "  /profile — Thông tin & số dư\n"
        "  /rules — Nội quy\n\n"
        "🎁 *Kiếm tiền:*\n"
        "  /diemdanh — Điểm danh hàng ngày (+100đ)\n"
        "  /code `<MÃ>` — Nhập code thưởng\n"
        "  /gioithieu — Link giới thiệu (+100đ/người)\n\n"
        "📌 *Nhiệm vụ:*\n"
        "  /nhiemvu — Xem danh sách nhiệm vụ\n"
        f"  /vuotlink1 — Vượt Link 1 (+{VUOTLINK1_REWARD:,}đ | tối đa {VUOTLINK1_LIMIT} lần)\n"
        f"  /vuotlink2 — Vượt Link 2 (+{VUOTLINK2_REWARD:,}đ | tối đa {VUOTLINK2_LIMIT} lần)\n\n"
        "💸 *Rút tiền:*\n"
        "  /rut `<số tiền>` — Yêu cầu rút (min 20.000đ)\n\n"
        "📞 *Hỗ trợ:*\n"
        "  /support — Liên hệ CSKH\n",
        parse_mode="Markdown",
    )

async def rules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 *Nội Quy & Luật Lệ*\n\n"
        "1. Không spam, gian lận hoặc dùng tool cheat.\n"
        "2. Nhiệm vụ phải hoàn thành thật, đúng yêu cầu.\n"
        "3. Vi phạm → khoá tài khoản, mất toàn bộ số dư.\n"
        "4. Rút tối thiểu 20.000đ.\n"
        "5. Admin có toàn quyền xử lý tranh chấp.\n\n"
        "© Lê Trung Dũng", parse_mode="Markdown",
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = get_user(user.id)
    if not data:
        add_user(user.id, user.username)
        data = get_user(user.id)
    await update.message.reply_text(
        f"👤 *Thông tin tài khoản*\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"📛 Tên: {user.first_name}\n"
        f"💰 Số dư: *{data['balance']:,}đ*\n"
        f"⭐ Điểm: {data['points']}",
        parse_mode="Markdown",
    )

async def diemdanh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    today = datetime.date.today().isoformat()
    data  = get_user(user.id)
    if not data:
        add_user(user.id, user.username)
        data = get_user(user.id)
    if data["last_daily"] == today:
        await update.message.reply_text("📅 Bạn đã điểm danh hôm nay rồi!")
        return
    c.execute("UPDATE users SET balance=balance+100,points=points+100,last_daily=? WHERE user_id=?",
              (today, user.id))
    conn.commit()
    await update.message.reply_text("✅ Điểm danh thành công! *+100đ* 🎉", parse_mode="Markdown")

async def nhiemvu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT * FROM tasks")
    tasks = c.fetchall()
    if not tasks:
        await update.message.reply_text("📭 Chưa có nhiệm vụ nào."); return
    msg = "🎯 *Danh sách nhiệm vụ:*\n\n"
    for t in tasks:
        if t["task_type"] in ("vuot_link_1","vuot_link_2"):
            cmd = "/vuotlink1" if t["task_type"] == "vuot_link_1" else "/vuotlink2"
            msg += f"🔗 *{t['title']}* — {t['reward']:,}đ/lần\n📝 {t['description']}\n▶️ {cmd}\n\n"
        else:
            msg += f"📝 *{t['title']}* — {t['reward']:,}đ\n🌐 {t['description']}\n✅ /hoanthanh_{t['task_id']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def submit_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        task_id = int(update.message.text.split("_")[1])
    except Exception:
        await update.message.reply_text("❌ Lệnh không hợp lệ."); return
    c.execute("SELECT title,reward FROM tasks WHERE task_id=?", (task_id,))
    task = c.fetchone()
    if not task:
        await update.message.reply_text("❌ Nhiệm vụ không tồn tại."); return
    c.execute("INSERT OR REPLACE INTO user_tasks (user_id,task_id,status) VALUES(?,?,'pending')", (user_id,task_id))
    conn.commit()
    await update.message.reply_text("📬 Đã gửi! Chờ admin duyệt.")
    for admin in ADMIN_IDS:
        try:
            notify_telegram(admin,
                f"📌 *{update.effective_user.first_name}* (ID:{user_id})\n"
                f"Hoàn thành nhiệm vụ #{task_id} ({task['title']})\n"
                f"✅ /duyet_task {user_id} {task_id}")
        except Exception: pass

async def vuotlink1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _vuotlink(update, context, "vuotlink1", VUOTLINK1_REWARD,
                    VUOTLINK1_API_URL, VUOTLINK1_API_KEY, VUOTLINK1_LIMIT)

async def vuotlink2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _vuotlink(update, context, "vuotlink2", VUOTLINK2_REWARD,
                    VUOTLINK2_API_URL, VUOTLINK2_API_KEY, VUOTLINK2_LIMIT)

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: `/code CODE2025`", parse_mode="Markdown"); return
    code = context.args[0].strip().upper()
    c.execute("SELECT reward,is_active FROM codes WHERE code=?", (code,))
    row = c.fetchone()
    if not row: await update.message.reply_text("❌ Code không tồn tại."); return
    if not row["is_active"]: await update.message.reply_text("⚠️ Code đã hết hạn."); return
    c.execute("SELECT 1 FROM user_codes WHERE user_id=? AND code=?", (user.id, code))
    if c.fetchone(): await update.message.reply_text("⚠️ Bạn đã dùng code này rồi."); return
    reward = row["reward"]
    c.execute("INSERT INTO user_codes (user_id,code) VALUES(?,?)", (user.id, code))
    c.execute("UPDATE users SET balance=balance+?,points=points+? WHERE user_id=?", (reward,reward,user.id))
    conn.commit()
    await update.message.reply_text(f"✅ Nhập code thành công! *+{reward:,}đ* 🎉", parse_mode="Markdown")

async def gioithieu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    await update.message.reply_text(
        f"🔗 *Link giới thiệu của bạn:*\n{ref_link}\n\n"
        "👉 Mỗi người mời thành công nhận *+100đ*!", parse_mode="Markdown")

async def rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("📌 Cú pháp: /rut <số tiền>\nVí dụ: /rut 20000"); return
    amount = int(context.args[0])
    if amount < 20000: await update.message.reply_text("⚠️ Rút tối thiểu 20.000đ."); return
    data = get_user(user.id)
    if not data or data["balance"] < amount: await update.message.reply_text("⚠️ Số dư không đủ."); return
    c.execute("INSERT INTO withdraws (user_id,amount) VALUES(?,?)", (user.id, amount))
    conn.commit()
    await update.message.reply_text(f"✅ Yêu cầu rút *{amount:,}đ* đã gửi admin.", parse_mode="Markdown")
    for admin in ADMIN_IDS:
        notify_telegram(admin,
            f"💸 *Yêu cầu rút tiền*\n👤 {user.first_name} (ID:{user.id})\n💵 {amount:,}đ\n\n"
            f"✅ /duyet_rut {user.id} {amount}\n❌ /huy_rut {user.id} {amount}")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 *Hỗ trợ CSKH*\n\nLiên hệ admin Telegram.\n\n© Lê Trung Dũng",
                                    parse_mode="Markdown")

# ADMIN
async def approve_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) != 2: await update.message.reply_text("Cú pháp: /duyet_task <user_id> <task_id>"); return
    try: user_id, task_id = int(context.args[0]), int(context.args[1])
    except ValueError: return
    c.execute("SELECT reward FROM tasks WHERE task_id=?", (task_id,))
    row = c.fetchone()
    if not row: await update.message.reply_text("Task không tồn tại."); return
    reward = row["reward"]
    c.execute("UPDATE user_tasks SET status='approved' WHERE user_id=? AND task_id=?", (user_id,task_id))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward,user_id))
    conn.commit()
    await update.message.reply_text(f"✅ Duyệt task #{task_id} cho user {user_id}. +{reward:,}đ")
    notify_telegram(user_id, f"🎉 Nhiệm vụ #{task_id} được duyệt! *+{reward:,}đ*")

async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    c.execute("SELECT user_id,task_id FROM user_tasks WHERE status='pending'")
    rows = c.fetchall()
    if not rows: await update.message.reply_text("📭 Không có nhiệm vụ chờ duyệt."); return
    msg = "📋 *Nhiệm vụ chờ duyệt:*\n\n"
    for r in rows: msg += f"User: {r['user_id']} | Task: {r['task_id']}\n✅ /duyet_task {r['user_id']} {r['task_id']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def duyet_rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2: await update.message.reply_text("Cú pháp: /duyet_rut <user_id> <amount>"); return
    try: user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError: return
    data = get_user(user_id)
    if not data or data["balance"] < amount: await update.message.reply_text("⚠️ Số dư không đủ."); return
    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount,user_id))
    c.execute("UPDATE withdraws SET status='approved' WHERE user_id=? AND amount=? AND status='pending'", (user_id,amount))
    conn.commit()
    await update.message.reply_text(f"✅ Đã duyệt rút {amount:,}đ cho user {user_id}.")
    notify_telegram(user_id, f"✅ Yêu cầu rút *{amount:,}đ* đã được duyệt!")

async def huy_rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2: return
    try: user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError: return
    c.execute("UPDATE withdraws SET status='rejected' WHERE user_id=? AND amount=? AND status='pending'", (user_id,amount))
    conn.commit()
    await update.message.reply_text(f"❌ Đã từ chối rút {amount:,}đ của user {user_id}.")
    notify_telegram(user_id, f"⚠️ Yêu cầu rút {amount:,}đ bị từ chối.")

async def add_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2: await update.message.reply_text("Cú pháp: /add_code <CODE> <reward>"); return
    code = context.args[0].upper()
    try: reward = int(context.args[1])
    except ValueError: return
    c.execute("INSERT OR REPLACE INTO codes (code,reward,is_active) VALUES(?,?,1)", (code,reward))
    conn.commit()
    await update.message.reply_text(f"✅ Code *{code}* (+{reward:,}đ).", parse_mode="Markdown")

async def thongbao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args: await update.message.reply_text("Cú pháp: /thongbao <nội dung>"); return
    msg = " ".join(context.args)
    c.execute("SELECT user_id FROM users")
    count = 0
    for (uid,) in [(r["user_id"],) for r in c.fetchall()]:
        try: notify_telegram(uid, f"📢 *Thông báo:*\n\n{msg}"); count += 1
        except Exception: pass
    await update.message.reply_text(f"✅ Đã gửi đến {count} người dùng.")

# ══════════════════════════════════════════
#  KHỞI ĐỘNG — Bot + Flask cùng lúc
# ══════════════════════════════════════════

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Flask webhook chạy tại port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("menu",        menu_handler))
    app.add_handler(CommandHandler("rules",       rules_handler))
    app.add_handler(CommandHandler("luat",        rules_handler))
    app.add_handler(CommandHandler("profile",     profile))
    app.add_handler(CommandHandler("diemdanh",    diemdanh))
    app.add_handler(CommandHandler("nhiemvu",     nhiemvu))
    app.add_handler(CommandHandler("hoanthanh_1", submit_task))
    app.add_handler(CommandHandler("hoanthanh_2", submit_task))
    app.add_handler(CommandHandler("hoanthanh_3", submit_task))
    app.add_handler(CommandHandler("vuotlink1",   vuotlink1))
    app.add_handler(CommandHandler("vuotlink2",   vuotlink2))
    app.add_handler(CommandHandler("code",        code_handler))
    app.add_handler(CommandHandler("gioithieu",   gioithieu))
    app.add_handler(CommandHandler("ref",         gioithieu))
    app.add_handler(CommandHandler("rut",         rut))
    app.add_handler(CommandHandler("support",     support))
    app.add_handler(CommandHandler("duyet_tasks", list_pending))
    app.add_handler(CommandHandler("duyet_task",  approve_task))
    app.add_handler(CommandHandler("duyet_rut",   duyet_rut))
    app.add_handler(CommandHandler("huy_rut",     huy_rut))
    app.add_handler(CommandHandler("add_code",    add_code_handler))
    app.add_handler(CommandHandler("thongbao",    thongbao_handler))

    print("🤖 Bot Lê Trung Dũng v6.0 đang chạy...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Chạy Flask trong thread riêng
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    # Chạy Bot trong main thread
    asyncio.run(run_bot())
