#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════╗
║  WEBHOOK SERVER — Lê Trung Dũng Bot      ║
║  Trang đích sau khi vượt link xong       ║
╚══════════════════════════════════════════╝

Cài thư viện:  pip install flask requests
Chạy:          python webhook.py
"""

# ══════════════════════════════════════════
#  CẤU HÌNH — khớp với bot.py
# ══════════════════════════════════════════

BOT_TOKEN = "8267142566:AAFJOpcVA1Js9VwFjbAwhJHQ35xWS55seRs"
DB_PATH   = "vipbot.db"   # cùng file DB với bot.py
PORT      = 5000

# Giới hạn lượt / IP (khớp với bot.py)
LIMIT = {
    "vuotlink1": 5,
    "vuotlink2": 1000,
}

# ══════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════

import sqlite3
import requests
from flask import Flask, request, render_template_string

app  = Flask(__name__)
db   = sqlite3.connect(DB_PATH, check_same_thread=False)
cur  = db.cursor()

# Bảng đếm lượt theo IP
cur.execute('''
CREATE TABLE IF NOT EXISTS device_limits (
    ip        TEXT,
    link_type TEXT,
    count     INTEGER DEFAULT 0,
    PRIMARY KEY (ip, link_type)
)
''')
db.commit()

# ══════════════════════════════════════════
#  HÀM HỖ TRỢ
# ══════════════════════════════════════════

def get_ip() -> str:
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "unknown")

def check_limit(ip: str, link_type: str) -> tuple[bool, int, int]:
    """Trả về (được_phép, đã_dùng, giới_hạn)."""
    limit = LIMIT.get(link_type, 9999)
    cur.execute("SELECT count FROM device_limits WHERE ip=? AND link_type=?", (ip, link_type))
    row   = cur.fetchone()
    count = row[0] if row else 0
    if count >= limit:
        return False, count, limit
    if row:
        cur.execute("UPDATE device_limits SET count=count+1 WHERE ip=? AND link_type=?", (ip, link_type))
    else:
        cur.execute("INSERT INTO device_limits (ip,link_type,count) VALUES(?,?,1)", (ip, link_type))
    db.commit()
    return True, count + 1, limit

def get_balance(user_id: int) -> int:
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def vnd(n: int) -> str:
    """Format kiểu Việt: 1.500"""
    return f"{n:,}".replace(",", ".")

def notify_telegram(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text,
                                 "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"[TG Error] {e}")

def get_bot_username() -> str:
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        return r.json()["result"]["username"]
    except Exception:
        return "your_bot"

BOT_USER = get_bot_username()

# ══════════════════════════════════════════
#  TEMPLATE — trang đích
# ══════════════════════════════════════════

# CSS chung cho tất cả trang
_CSS = """
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:'Segoe UI',Tahoma,sans-serif;
  background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
  min-height:100vh;display:flex;align-items:center;
  justify-content:center;padding:20px
}
.card{
  background:rgba(255,255,255,.07);backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.13);border-radius:26px;
  padding:46px 48px;text-align:center;max-width:440px;
  width:100%;box-shadow:0 28px 72px rgba(0,0,0,.55);color:#fff
}
.icon{font-size:72px;margin-bottom:10px;line-height:1}
h1{font-size:24px;font-weight:700;margin-bottom:6px}
.sub{color:rgba(255,255,255,.6);font-size:14px;line-height:1.6;margin:8px 0}
.reward{
  font-size:52px;font-weight:800;
  background:linear-gradient(90deg,#f9c74f,#f3722c);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin:14px 0 4px
}
.balance-box{
  background:rgba(74,222,128,.1);
  border:1px solid rgba(74,222,128,.28);
  border-radius:14px;padding:14px 20px;margin:18px 0;font-size:15px
}
.balance-box strong{color:#4ade80;font-size:22px}
.progress-wrap{
  background:rgba(255,255,255,.07);
  border:1px solid rgba(255,255,255,.11);
  border-radius:14px;padding:14px 20px;
  margin:0 0 18px;font-size:13px;color:rgba(255,255,255,.55)
}
.progress-wrap b{color:#fff}
.bar-track{
  background:rgba(255,255,255,.1);border-radius:99px;
  height:8px;margin-top:8px;overflow:hidden
}
.bar-fill{
  height:100%;border-radius:99px;
  background:linear-gradient(90deg,#667eea,#764ba2);
  transition:width .6s ease
}
.btn{
  display:inline-block;
  background:linear-gradient(135deg,#667eea,#764ba2);
  color:#fff;text-decoration:none;padding:14px 36px;
  border-radius:50px;font-size:15px;font-weight:600;
  margin-top:12px;box-shadow:0 6px 24px rgba(102,126,234,.4);
  transition:opacity .2s,transform .15s
}
.btn:hover{opacity:.88;transform:translateY(-2px)}
hr{border:none;border-top:1px solid rgba(255,255,255,.1);margin:22px 0}
.foot{margin-top:22px;font-size:11px;color:rgba(255,255,255,.25)}
.badge{
  display:inline-block;
  background:rgba(74,222,128,.15);
  border:1px solid rgba(74,222,128,.3);
  color:#4ade80;font-size:12px;font-weight:600;
  padding:3px 12px;border-radius:99px;margin-bottom:12px
}
.badge-warn{
  background:rgba(251,191,36,.12);
  border-color:rgba(251,191,36,.3);color:#fbbf24
}
.badge-err{
  background:rgba(248,113,113,.12);
  border-color:rgba(248,113,113,.3);color:#f87171
}
</style>
"""

# ── Trang thành công ─────────────────────
PAGE_SUCCESS = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nhận Thưởng Thành Công</title>""" + _CSS + """</head>
<body><div class="card">
  <div class="icon">🎉</div>
  <span class="badge">✅ XÁC NHẬN THÀNH CÔNG</span>
  <h1 style="color:#4ade80">Nhận Thưởng Thành Công!</h1>
  <div class="reward">+{{ reward }}đ</div>
  <div class="balance-box">
    💰 Số dư tài khoản của bạn<br>
    <strong>{{ balance }}đ</strong>
  </div>
  <div class="progress-wrap">
    Lượt {{ lname }} đã dùng: <b>{{ used }}/{{ limit }}</b>
    <div class="bar-track"><div class="bar-fill" style="width:{{ pct }}%"></div></div>
    {% if used >= limit %}
    <div style="margin-top:8px;color:#f87171;font-size:12px">⚠️ Đã đạt giới hạn cho loại link này</div>
    {% endif %}
  </div>
  <p class="sub">💬 Tiền thưởng đã được cộng tự động vào tài khoản Telegram.<br>
  Quay lại bot để tiếp tục kiếm tiền!</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

# ── Trang đã dùng rồi ────────────────────
PAGE_USED = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đã Sử Dụng</title>""" + _CSS + """</head>
<body><div class="card">
  <div class="icon">⚠️</div>
  <span class="badge badge-warn">ĐÃ SỬ DỤNG</span>
  <h1 style="color:#f59e0b">Link Đã Được Dùng Rồi</h1>
  <p class="sub" style="margin-top:14px">Token này đã nhận thưởng trước đó.<br>
  Mỗi link chỉ dùng được <strong style="color:#fff">1 lần</strong>.<br><br>
  Tạo link mới trong bot để tiếp tục kiếm tiền!</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Tạo Link Mới</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

# ── Trang đã đạt giới hạn thiết bị ───────
PAGE_LIMIT = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đã Đạt Giới Hạn</title>""" + _CSS + """</head>
<body><div class="card">
  <div class="icon">🚫</div>
  <span class="badge badge-err">GIỚI HẠN THIẾT BỊ</span>
  <h1 style="color:#f87171">Đã Đạt Giới Hạn!</h1>
  <p class="sub" style="margin-top:14px">
    Thiết bị này đã vượt tối đa<br>
    <strong style="color:#fff;font-size:22px">{{ limit }} lần</strong><br>
    cho <strong style="color:#fff">{{ lname }}</strong>.<br><br>
    Hãy thử loại link khác hoặc liên hệ admin.
  </p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

# ── Trang lỗi token ───────────────────────
PAGE_ERROR = """<!DOCTYPE html><html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lỗi</title>""" + _CSS + """</head>
<body><div class="card">
  <div class="icon">❌</div>
  <span class="badge badge-err">LỖI TOKEN</span>
  <h1 style="color:#f87171">Link Không Hợp Lệ</h1>
  <p class="sub" style="margin-top:14px">Link không tồn tại hoặc đã hết hạn.<br>
  Vui lòng tạo link mới từ bot.</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="foot">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

# ══════════════════════════════════════════
#  ROUTE CHÍNH: /done/<token>
#  API redirect user tới đây sau khi vượt xong
# ══════════════════════════════════════════

@app.route("/done/<token>")
def done(token: str):
    ip = get_ip()

    # 1️⃣ Tra token
    cur.execute("SELECT user_id,link_type,reward,status FROM vuotlink_tokens WHERE token=?", (token,))
    row = cur.fetchone()
    if not row:
        return render_template_string(PAGE_ERROR, bot=BOT_USER), 404

    user_id, link_type, reward, status = row
    lname = "Vượt Link 1" if link_type == "vuotlink1" else "Vượt Link 2"

    # 2️⃣ Đã nhận thưởng rồi
    if status == "approved":
        return render_template_string(PAGE_USED, bot=BOT_USER), 200

    # 3️⃣ Kiểm tra giới hạn IP
    allowed, used, limit = check_limit(ip, link_type)
    if not allowed:
        return render_template_string(PAGE_LIMIT, limit=limit, lname=lname, bot=BOT_USER), 429

    # 4️⃣ Cộng tiền
    cur.execute("UPDATE vuotlink_tokens SET status='approved' WHERE token=?", (token,))
    cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, user_id))
    db.commit()

    balance = get_balance(user_id)
    pct     = min(100, round(used / limit * 100))

    # 5️⃣ Thông báo Telegram
    notify_telegram(
        user_id,
        f"✅ *Vượt link thành công!*\n"
        f"💰 Nhận: *+{vnd(reward)}đ*\n"
        f"🏦 Số dư: *{vnd(balance)}đ*\n"
        f"📊 Lượt: *{used}/{limit}*\n\n"
        f"👉 Gõ /vuotlink1 hoặc /vuotlink2 để tiếp tục!"
    )

    print(f"✅ IP={ip} | user={user_id} | {link_type} | +{reward}đ | lượt={used}/{limit}")

    # 6️⃣ Hiển thị trang thành công
    return render_template_string(
        PAGE_SUCCESS,
        reward=vnd(reward),
        balance=vnd(balance),
        used=used, limit=limit, pct=pct,
        lname=lname, bot=BOT_USER,
    ), 200


# ══════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════

@app.route("/")
def index():
    return {"status": "running", "bot": f"@{BOT_USER}", "version": "5.0"}


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

if __name__ == "__main__":
    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║  Webhook Server — Lê Trung Dũng Bot v5.0         ║")
    print(f"║  Port : {PORT}                                       ║")
    print(f"║  Bot  : @{BOT_USER:<39}║")
    print(f"╚══════════════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=PORT, debug=False)
