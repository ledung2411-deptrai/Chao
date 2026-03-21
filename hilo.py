#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════╗
║     BOT TELEGRAM KIẾM TIỀN ONLINE        ║
║     © Bản quyền thuộc về Lê Trung Dũng  ║
║     Phiên bản: 4.1                        ║
╚══════════════════════════════════════════╝

Luồng vượt link:
  1. User gõ /vuotlink1  (không cần nhập URL gì)
  2. Bot tạo token → callback_url = WEBHOOK_BASE_URL/done/<token>
  3. Gọi API với url = callback_url
  4. API bọc quảng cáo → trả về monetized_link
  5. Bot gửi monetized_link cho user
  6. User click → xem quảng cáo → API redirect về callback_url
  7. webhook.py cộng tiền + hiển thị trang thông báo
"""

# ══════════════════════════════════════════
#  CẤU HÌNH
# ══════════════════════════════════════════

TOKEN     = "8504510484:AAFp55RNutB0bzATABwiuW5pAKtYgKS5hL0"
ADMIN_ID  = 8175673206
ADMIN_IDS = [ADMIN_ID]

# URL ngrok (trang đích sau khi vượt link xong)
WEBHOOK_BASE_URL = "https://chao-6sag.onrender.com"

# --- Vượt Link 1 — link4m.co (400đ | tối đa 5 lần/IP) ---
VUOTLINK1_REWARD  = 400
VUOTLINK1_API_KEY = "699f355d4aaa8e53c471d356"
VUOTLINK1_API_URL = "https://link4m.co/api-shorten/v2"
VUOTLINK1_LIMIT   = 5

# --- Vượt Link 2 — uptolink.one (300đ | tối đa 1000 lần/IP) ---
VUOTLINK2_REWARD  = 300
VUOTLINK2_API_KEY = "f7e837884a890d2fb5536785b1dd2208b11afd4e"
VUOTLINK2_API_URL = "https://uptolink.one/api"
VUOTLINK2_LIMIT   = 1000

# ══════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════

import asyncio
import sqlite3
import datetime
import hashlib
import secrets
import nest_asyncio
import aiohttp

nest_asyncio.apply()

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ══════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════

conn = sqlite3.connect("vipbot.db", check_same_thread=False)
c    = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT,
    balance INTEGER DEFAULT 0, points INTEGER DEFAULT 0,
    last_daily TEXT DEFAULT ""
)''')

c.execute("DROP TABLE IF EXISTS tasks")
c.execute('''CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY, title TEXT,
    description TEXT, reward INTEGER DEFAULT 0, task_type TEXT DEFAULT "normal"
)''')

FIXED_TASKS = [
    (1, "Tham Gia Nhóm Telegram", "t.me/hqhteam",                          500, "normal"),
    (2, "Đăng Ký Kênh Youtube",   "https://youtube.com/@plahuydzvcl",       200, "normal"),
    (3, "Theo Dõi Tiktok",        "https://tiktok.com/@plah.infinity",      200, "normal"),
    (4, "Vượt Link 1",
        f"Gõ /vuotlink1 → nhận link → click → nhận {VUOTLINK1_REWARD}đ (tối đa {VUOTLINK1_LIMIT} lần/thiết bị)",
        VUOTLINK1_REWARD, "vuot_link_1"),
    (5, "Vượt Link 2",
        f"Gõ /vuotlink2 → nhận link → click → nhận {VUOTLINK2_REWARD}đ (tối đa {VUOTLINK2_LIMIT} lần/thiết bị)",
        VUOTLINK2_REWARD, "vuot_link_2"),
]
for t in FIXED_TASKS:
    c.execute("INSERT OR IGNORE INTO tasks (task_id,title,description,reward,task_type) VALUES(?,?,?,?,?)", t)

c.execute('''CREATE TABLE IF NOT EXISTS user_tasks (
    user_id INTEGER, task_id INTEGER, status TEXT DEFAULT "pending",
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, task_id)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT,
    description TEXT, reward INTEGER, is_active INTEGER DEFAULT 1
)''')

c.execute('''CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY, reward INTEGER, is_active INTEGER DEFAULT 1
)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_codes (
    user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS withdraws (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
    status TEXT DEFAULT "pending", created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

# Token table: mỗi lần user gọi /vuotlink → tạo 1 token mới
c.execute('''CREATE TABLE IF NOT EXISTS vuotlink_tokens (
    token TEXT PRIMARY KEY, user_id INTEGER, link_type TEXT,
    reward INTEGER, status TEXT DEFAULT "pending",
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

conn.commit()

# ══════════════════════════════════════════
#  HÀM HỖ TRỢ
# ══════════════════════════════════════════

def add_user(user_id: int, username):
    c.execute("INSERT OR IGNORE INTO users (user_id,username) VALUES(?,?)", (user_id, username or ""))
    conn.commit()

def get_user(user_id: int):
    c.execute("SELECT user_id,username,balance,points,last_daily FROM users WHERE user_id=?", (user_id,))
    return c.fetchone()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def add_code(code, reward):
    c.execute("INSERT OR REPLACE INTO codes (code,reward,is_active) VALUES(?,?,1)", (code, reward))
    conn.commit()

def generate_token(user_id: int, link_type: str) -> str:
    """Token duy nhất gắn với user_id — dùng làm URL đích."""
    raw = f"{user_id}:{link_type}:{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]

# ══════════════════════════════════════════
#  XỬ LÝ VƯỢT LINK CHUNG
# ══════════════════════════════════════════

async def _handle_vuotlink(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    link_type: str, reward: int, api_url: str, api_key: str, limit: int,
):
    """
    Không yêu cầu user nhập URL.
    Tự động tạo link quảng cáo với destination = webhook/done/<token>.
    """
    user = update.effective_user
    add_user(user.id, user.username)

    link_num = "1" if link_type == "vuotlink1" else "2"

    # ── Tạo token & URL đích ──
    token        = generate_token(user.id, link_type)
    callback_url = f"{WEBHOOK_BASE_URL}/done/{token}"

    # ── Lưu token ──
    c.execute(
        "INSERT OR REPLACE INTO vuotlink_tokens (token,user_id,link_type,reward,status) VALUES(?,?,?,?,'pending')",
        (token, user.id, link_type, reward),
    )
    conn.commit()

    await update.message.reply_text("⏳ Đang tạo link, vui lòng chờ giây lát...")

    try:
        # ── Gọi API: url = callback_url (trang đích sau quảng cáo) ──
        params = {"api": api_key, "url": callback_url}

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json(content_type=None)

        # Parse kết quả API
        # link4m  → {"status":"success","shortenedUrl":"https://link4m.co/xxxxx"}
        # uptolink → {"status":"success","shortenedUrl":"https://uptolink.one/xxxxx"}
        ok         = str(data.get("status", "")).lower() in ("success", "1", "true")
        money_link = (data.get("shortenedUrl")
                      or data.get("short_link")
                      or data.get("result")
                      or data.get("url"))

        if ok and money_link:
            await update.message.reply_text(
                f"🔗 *Link Vượt {link_num} của bạn:*\n"
                f"`{money_link}`\n\n"
                f"👆 *Nhấn vào link* → xem qua quảng cáo → hoàn thành.\n"
                f"✅ Hệ thống sẽ *tự động cộng {reward:,}đ* ngay sau khi bạn vượt xong!\n\n"
                f"⚠️ Giới hạn *{limit} lần* mỗi thiết bị.",
                parse_mode="Markdown",
            )
        else:
            err = data.get("message") or data.get("error") or str(data)
            await update.message.reply_text(
                f"❌ Tạo link thất bại: `{err}`\n\nLiên hệ /support",
                parse_mode="Markdown",
            )
            c.execute("DELETE FROM vuotlink_tokens WHERE token=?", (token,))
            conn.commit()

    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Lỗi kết nối API: `{e}`\n\nLiên hệ /support",
            parse_mode="Markdown",
        )
        c.execute("DELETE FROM vuotlink_tokens WHERE token=?", (token,))
        conn.commit()


# ══════════════════════════════════════════
#  HANDLERS NGƯỜI DÙNG
# ══════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username)
    # Referral
    if context.args and context.args[0].isdigit():
        ref_id = int(context.args[0])
        if ref_id != user.id:
            c.execute("SELECT user_id FROM users WHERE user_id=?", (ref_id,))
            if c.fetchone():
                c.execute("UPDATE users SET balance=balance+100 WHERE user_id=?", (ref_id,))
                conn.commit()
                try:
                    await context.bot.send_message(
                        chat_id=ref_id,
                        text=f"🎉 Bạn vừa giới thiệu thành công *{user.first_name}*! +100đ thưởng.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
    await update.message.reply_text(
        f"👋 Xin chào *{user.first_name}*!\n\n"
        "🎉 Chào mừng đến với *BOT KIẾM TIỀN ONLINE*\n"
        "© Phát triển bởi *Lê Trung Dũng*\n\n"
        "⚡ Làm nhiệm vụ, vượt link để nhận tiền thưởng.\n"
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
        f"  /vuotlink1 — Vượt Link 1 (+{VUOTLINK1_REWARD:,}đ | max {VUOTLINK1_LIMIT} lần)\n"
        f"  /vuotlink2 — Vượt Link 2 (+{VUOTLINK2_REWARD:,}đ | max {VUOTLINK2_LIMIT} lần)\n\n"
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
        "👉 Sử dụng bot = đồng ý với điều khoản trên.\n"
        "© Lê Trung Dũng",
        parse_mode="Markdown",
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = get_user(user.id)
    if not data:
        add_user(user.id, user.username)
        data = get_user(user.id)
    _, _, balance, points, _ = data
    await update.message.reply_text(
        f"👤 *Thông tin tài khoản*\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"📛 Tên: {user.first_name}\n"
        f"💰 Số dư: *{balance:,}đ*\n"
        f"⭐ Điểm: {points}",
        parse_mode="Markdown",
    )


async def diemdanh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    today = datetime.date.today().isoformat()
    data  = get_user(user.id)
    if not data:
        add_user(user.id, user.username)
        data = get_user(user.id)
    if data[4] == today:
        await update.message.reply_text("📅 Bạn đã điểm danh hôm nay rồi, quay lại ngày mai nhé!")
        return
    c.execute("UPDATE users SET balance=balance+100,points=points+100,last_daily=? WHERE user_id=?",
              (today, user.id))
    conn.commit()
    await update.message.reply_text("✅ Điểm danh thành công! *+100đ* 🎉", parse_mode="Markdown")


async def nhiemvu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT task_id,title,description,reward,task_type FROM tasks")
    tasks = c.fetchall()
    if not tasks:
        await update.message.reply_text("📭 Chưa có nhiệm vụ nào."); return
    msg = "🎯 *Danh sách nhiệm vụ:*\n\n"
    for tid, title, desc, reward, ttype in tasks:
        if ttype in ("vuot_link_1", "vuot_link_2"):
            cmd = "/vuotlink1" if ttype == "vuot_link_1" else "/vuotlink2"
            msg += f"🔗 *{title}* — {reward:,}đ/lần\n📝 {desc}\n👉 Gõ: {cmd}\n\n"
        else:
            msg += f"📝 *{title}* — {reward:,}đ\n🌐 {desc}\n✅ /hoanthanh_{tid}\n\n"
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
    c.execute("INSERT OR REPLACE INTO user_tasks (user_id,task_id,status) VALUES(?,?,'pending')",
              (user_id, task_id))
    conn.commit()
    await update.message.reply_text("📬 Đã gửi! Chờ admin duyệt.")
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin,
                text=(f"📌 *{update.effective_user.first_name}* (ID:{user_id})\n"
                      f"Hoàn thành nhiệm vụ #{task_id} ({task[0]})\n"
                      f"✅ /duyet_task {user_id} {task_id}"),
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def vuotlink1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_vuotlink(update, context, "vuotlink1",
                           VUOTLINK1_REWARD, VUOTLINK1_API_URL, VUOTLINK1_API_KEY, VUOTLINK1_LIMIT)


async def vuotlink2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_vuotlink(update, context, "vuotlink2",
                           VUOTLINK2_REWARD, VUOTLINK2_API_URL, VUOTLINK2_API_KEY, VUOTLINK2_LIMIT)


async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: `/code CODE2025`", parse_mode="Markdown"); return
    code = context.args[0].strip().upper()
    c.execute("SELECT reward,is_active FROM codes WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ Code không tồn tại."); return
    reward, is_active = row
    if not is_active:
        await update.message.reply_text("⚠️ Code đã hết hạn."); return
    c.execute("SELECT 1 FROM user_codes WHERE user_id=? AND code=?", (user.id, code))
    if c.fetchone():
        await update.message.reply_text("⚠️ Bạn đã dùng code này rồi."); return
    c.execute("INSERT INTO user_codes (user_id,code) VALUES(?,?)", (user.id, code))
    c.execute("UPDATE users SET balance=balance+?,points=points+? WHERE user_id=?", (reward, reward, user.id))
    conn.commit()
    await update.message.reply_text(f"✅ Nhập code thành công! *+{reward:,}đ* 🎉", parse_mode="Markdown")


async def gioithieu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    await update.message.reply_text(
        f"🔗 *Link giới thiệu của bạn:*\n{ref_link}\n\n"
        "👉 Mỗi người bạn mời thành công nhận *+100đ*!",
        parse_mode="Markdown",
    )


async def rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("📌 Cú pháp: /rut <số tiền>\nVí dụ: /rut 20000"); return
    amount = int(context.args[0])
    if amount < 20000:
        await update.message.reply_text("⚠️ Rút tối thiểu 20.000đ."); return
    data = get_user(user.id)
    if not data or data[2] < amount:
        await update.message.reply_text("⚠️ Số dư không đủ."); return
    c.execute("INSERT INTO withdraws (user_id,amount) VALUES(?,?)", (user.id, amount))
    conn.commit()
    await update.message.reply_text(
        f"✅ Yêu cầu rút *{amount:,}đ* đã gửi admin. Vui lòng chờ duyệt.",
        parse_mode="Markdown",
    )
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin,
                text=(f"💸 *Yêu cầu rút tiền*\n"
                      f"👤 {user.first_name} (ID:{user.id})\n"
                      f"💵 {amount:,}đ\n\n"
                      f"✅ /duyet_rut {user.id} {amount}\n"
                      f"❌ /huy_rut {user.id} {amount}"),
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *Hỗ trợ / CSKH*\n\n"
        "Gặp vấn đề? Liên hệ admin:\n"
        "• Telegram: *(thay username admin của bạn)*\n\n"
        "© Lê Trung Dũng",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════
#  HANDLERS ADMIN
# ══════════════════════════════════════════

async def approve_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) != 2:
        await update.message.reply_text("Cú pháp: /duyet_task <user_id> <task_id>"); return
    try: user_id, task_id = int(context.args[0]), int(context.args[1])
    except ValueError: return
    c.execute("SELECT reward FROM tasks WHERE task_id=?", (task_id,))
    row = c.fetchone()
    if not row: await update.message.reply_text("Task không tồn tại."); return
    reward = row[0]
    c.execute("UPDATE user_tasks SET status='approved' WHERE user_id=? AND task_id=?", (user_id, task_id))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, user_id))
    conn.commit()
    await update.message.reply_text(f"✅ Duyệt task #{task_id} cho user {user_id}. +{reward:,}đ")
    try:
        await context.bot.send_message(chat_id=user_id,
                                       text=f"🎉 Nhiệm vụ #{task_id} được duyệt! *+{reward:,}đ*",
                                       parse_mode="Markdown")
    except Exception: pass


async def list_pending_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    c.execute("SELECT user_id,task_id FROM user_tasks WHERE status='pending'")
    rows = c.fetchall()
    if not rows: await update.message.reply_text("📭 Không có nhiệm vụ nào chờ duyệt."); return
    msg = "📋 *Nhiệm vụ chờ duyệt:*\n\n"
    for uid, tid in rows:
        msg += f"User: {uid} | Task: {tid}\n✅ /duyet_task {uid} {tid}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def duyet_rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("Cú pháp: /duyet_rut <user_id> <amount>"); return
    try: user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError: return
    data = get_user(user_id)
    if not data or data[2] < amount:
        await update.message.reply_text("⚠️ Số dư user không đủ."); return
    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
    c.execute("UPDATE withdraws SET status='approved' WHERE user_id=? AND amount=? AND status='pending'",
              (user_id, amount))
    conn.commit()
    await update.message.reply_text(f"✅ Đã duyệt rút {amount:,}đ cho user {user_id}.")
    try:
        await context.bot.send_message(chat_id=user_id,
                                       text=f"✅ Yêu cầu rút *{amount:,}đ* đã được duyệt!",
                                       parse_mode="Markdown")
    except Exception: pass


async def huy_rut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("Cú pháp: /huy_rut <user_id> <amount>"); return
    try: user_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError: return
    c.execute("UPDATE withdraws SET status='rejected' WHERE user_id=? AND amount=? AND status='pending'",
              (user_id, amount))
    conn.commit()
    await update.message.reply_text(f"❌ Đã từ chối rút {amount:,}đ của user {user_id}.")
    try:
        await context.bot.send_message(chat_id=user_id,
                                       text=f"⚠️ Yêu cầu rút {amount:,}đ bị từ chối. Liên hệ /support.")
    except Exception: pass


async def addnv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Cú pháp: /addnv <tiêu đề> | <mô tả> | <thưởng>"); return
    try:
        title, desc, reward = [x.strip() for x in " ".join(context.args).split("|")]
        reward = int(reward)
    except Exception:
        await update.message.reply_text("Sai cú pháp."); return
    c.execute("INSERT INTO missions (title,description,reward) VALUES(?,?,?)", (title, desc, reward))
    conn.commit()
    await update.message.reply_text(f"✅ Đã thêm: *{title}* (+{reward:,}đ)", parse_mode="Markdown")


async def delnhiemvu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Cú pháp: /delnhiemvu <task_id>"); return
    c.execute("DELETE FROM tasks WHERE task_id=?", (int(context.args[0]),))
    conn.commit()
    await update.message.reply_text(f"🗑️ Đã xoá nhiệm vụ #{context.args[0]}")


async def listnhiemvu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    c.execute("SELECT task_id,title,reward FROM tasks")
    tasks = c.fetchall()
    if not tasks: await update.message.reply_text("Chưa có nhiệm vụ nào."); return
    msg = "📋 *Danh sách nhiệm vụ:*\n\n"
    for tid, title, reward in tasks:
        msg += f"• #{tid} {title} — {reward:,}đ\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def add_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("Cú pháp: /add_code <CODE> <reward>"); return
    code = context.args[0].upper()
    try: reward = int(context.args[1])
    except ValueError: return
    add_code(code, reward)
    await update.message.reply_text(f"✅ Code *{code}* (+{reward:,}đ).", parse_mode="Markdown")


async def thongbao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Cú pháp: /thongbao <nội dung>"); return
    msg = " ".join(context.args)
    c.execute("SELECT user_id FROM users")
    count = 0
    for (uid,) in c.fetchall():
        try:
            await context.bot.send_message(chat_id=uid,
                                           text=f"📢 *Thông báo:*\n\n{msg}", parse_mode="Markdown")
            count += 1
        except Exception: pass
    await update.message.reply_text(f"✅ Đã gửi đến {count} người dùng.")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("menu",         menu_handler))
    app.add_handler(CommandHandler("rules",        rules_handler))
    app.add_handler(CommandHandler("luat",         rules_handler))
    app.add_handler(CommandHandler("profile",      profile))
    app.add_handler(CommandHandler("diemdanh",     diemdanh))
    app.add_handler(CommandHandler("nhiemvu",      nhiemvu))
    app.add_handler(CommandHandler("hoanthanh_1",  submit_task))
    app.add_handler(CommandHandler("hoanthanh_2",  submit_task))
    app.add_handler(CommandHandler("hoanthanh_3",  submit_task))
    app.add_handler(CommandHandler("vuotlink1",    vuotlink1))
    app.add_handler(CommandHandler("vuotlink2",    vuotlink2))
    app.add_handler(CommandHandler("code",         code_handler))
    app.add_handler(CommandHandler("gioithieu",    gioithieu))
    app.add_handler(CommandHandler("ref",          gioithieu))
    app.add_handler(CommandHandler("rut",          rut))
    app.add_handler(CommandHandler("support",      support))

    app.add_handler(CommandHandler("duyet_tasks",  list_pending_tasks))
    app.add_handler(CommandHandler("duyet_task",   approve_task))
    app.add_handler(CommandHandler("duyet_rut",    duyet_rut))
    app.add_handler(CommandHandler("huy_rut",      huy_rut))
    app.add_handler(CommandHandler("addnv",        addnv_handler))
    app.add_handler(CommandHandler("delnhiemvu",   delnhiemvu))
    app.add_handler(CommandHandler("listnhiemvu",  listnhiemvu))
    app.add_handler(CommandHandler("add_code",     add_code_handler))
    app.add_handler(CommandHandler("thongbao",     thongbao_handler))

    print("🤖 Bot Lê Trung Dũng v4.1 đang chạy...")
    await app.run_polling()


if __name__ == "__main__":
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
