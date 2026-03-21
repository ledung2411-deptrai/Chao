#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════╗
║  WEBHOOK SERVER — Trang Đích Vượt Link   ║
║  © Lê Trung Dũng                         ║
╚══════════════════════════════════════════╝

Cài:  pip install flask requests
Chạy: python webhook.py
"""

# ══════════════════════════════════════════
#  CẤU HÌNH — phải khớp với bot.py
# ══════════════════════════════════════════

BOT_TOKEN = "8504510484:AAFp55RNutB0bzATABwiuW5pAKtYgKS5hL0"
DB_PATH   = "vipbot.db"
PORT      = 5000

LIMIT_VUOTLINK1 = 5
LIMIT_VUOTLINK2 = 1000

# ══════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════

import sqlite3
import requests
import threading
from flask import Flask, request, render_template_string

app = Flask(__name__)

# Dùng threading.local để mỗi thread có connection riêng — tránh lỗi SQLite thread
_local = threading.local()

def get_db():
    """Lấy connection SQLite cho thread hiện tại."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn

def get_cursor():
    return get_db().cursor()

# Tạo bảng device_limits nếu chưa có
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS device_limits (
            ip        TEXT,
            link_type TEXT,
            count     INTEGER DEFAULT 0,
            PRIMARY KEY(ip, link_type)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ══════════════════════════════════════════
#  HÀM HỖ TRỢ
# ══════════════════════════════════════════

def send_telegram(chat_id: int, text: str) -> bool:
    """Gửi tin nhắn Telegram. Trả về True nếu thành công."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        result = r.json()
        if not result.get("ok"):
            print(f"[Telegram FAIL] chat_id={chat_id} | {result.get('description')}")
            return False
        print(f"[Telegram OK] chat_id={chat_id}")
        return True
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return False

def get_balance(user_id: int) -> int:
    cur = get_cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row["balance"] if row else 0

def real_ip() -> str:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )

def check_limit(ip: str, link_type: str, limit: int):
    """
    Kiểm tra & tăng bộ đếm theo IP.
    Trả về (được_phép, số_lượt_hiện_tại).
    """
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT count FROM device_limits WHERE ip=? AND link_type=?", (ip, link_type))
    row   = cur.fetchone()
    count = row["count"] if row else 0

    if count >= limit:
        return False, count

    if row:
        cur.execute("UPDATE device_limits SET count=count+1 WHERE ip=? AND link_type=?",
                    (ip, link_type))
    else:
        cur.execute("INSERT INTO device_limits (ip,link_type,count) VALUES(?,?,1)",
                    (ip, link_type))
    db.commit()
    return True, count + 1

def credit_user(token: str, user_id: int, reward: int):
    """Cộng tiền & đánh dấu token đã dùng. Trả về balance mới."""
    db  = get_db()
    cur = db.cursor()
    cur.execute("UPDATE vuotlink_tokens SET status='approved' WHERE token=?", (token,))
    cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, user_id))
    db.commit()
    return get_balance(user_id)

def vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def get_bot_username() -> str:
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10)
        return r.json()["result"]["username"]
    except Exception:
        return "your_bot"

BOT_USERNAME = get_bot_username()
print(f"[INFO] Bot username: @{BOT_USERNAME}")

# ══════════════════════════════════════════
#  TEMPLATES HTML
# ══════════════════════════════════════════

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
  background:rgba(255,255,255,.07);
  backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.13);
  border-radius:26px;padding:44px 46px;
  text-align:center;max-width:440px;width:100%;
  box-shadow:0 28px 70px rgba(0,0,0,.55);color:#fff
}
.icon{font-size:72px;margin-bottom:10px;line-height:1.1}
.badge{
  display:inline-block;font-size:11.5px;font-weight:700;
  padding:4px 14px;border-radius:99px;margin-bottom:10px;letter-spacing:.5px
}
.bg{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);color:#4ade80}
.by{background:rgba(251,191,36,.12);border:1px solid rgba(251,191,36,.3);color:#fbbf24}
.br{background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);color:#f87171}
h1{font-size:24px;font-weight:800;margin-bottom:6px}
p{color:rgba(255,255,255,.65);font-size:14.5px;line-height:1.7;margin:6px 0}
.reward{
  font-size:52px;font-weight:900;
  background:linear-gradient(90deg,#f9c74f,#f3722c);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin:12px 0 4px
}
.balance-box{
  background:rgba(74,222,128,.1);
  border:1px solid rgba(74,222,128,.25);
  border-radius:14px;padding:14px 20px;margin:16px 0;font-size:15px
}
.balance-box strong{color:#4ade80;font-size:21px}
.progress-wrap{
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.1);
  border-radius:14px;padding:12px 18px;margin:10px 0 16px;font-size:13px;
  color:rgba(255,255,255,.55)
}
.bar-track{background:rgba(255,255,255,.1);border-radius:99px;height:8px;margin-top:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#667eea,#764ba2)}
hr{border:none;border-top:1px solid rgba(255,255,255,.1);margin:22px 0}
.btn{
  display:inline-block;text-decoration:none;color:#fff;font-size:15px;font-weight:700;
  padding:14px 38px;border-radius:50px;margin-top:6px;
  background:linear-gradient(135deg,#667eea,#764ba2);
  box-shadow:0 8px 28px rgba(102,126,234,.4);
  transition:opacity .2s,transform .15s
}
.btn:hover{opacity:.88;transform:translateY(-2px)}
.copy{margin-top:24px;font-size:11px;color:rgba(255,255,255,.25)}
</style>
"""

PAGE_SUCCESS = """<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nhận Thưởng Thành Công ✅</title>""" + _CSS + """</head><body>
<div class="card">
  <div class="icon">🎉</div>
  <span class="badge bg">✅ XÁC NHẬN THÀNH CÔNG</span>
  <h1 style="color:#4ade80">Nhận Thưởng Thành Công!</h1>
  <div class="reward">+{{ reward }}đ</div>
  <div class="balance-box">
    💰 Số dư tài khoản: <strong>{{ balance }}đ</strong>
  </div>
  <div class="progress-wrap">
    Lượt đã vượt:&nbsp;<b style="color:#fff">{{ used }}/{{ limit }}</b>
    <div class="bar-track">
      <div class="bar-fill" style="width:{{ pct }}%"></div>
    </div>
    {% if used >= limit %}
    <div style="color:#f87171;margin-top:6px;font-size:12px">
      ⚠️ Đã đạt giới hạn thiết bị cho loại link này.
    </div>
    {% endif %}
  </div>
  <p>Tiền thưởng đã được <b style="color:#fff">cộng tự động</b><br>vào tài khoản Telegram của bạn.</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="copy">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_USED = """<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đã Sử Dụng</title>""" + _CSS + """</head><body>
<div class="card">
  <div class="icon">⚠️</div>
  <span class="badge by">LINK ĐÃ DÙNG</span>
  <h1 style="color:#fbbf24">Link Đã Được Sử Dụng</h1>
  <p style="margin-top:10px">Token này đã nhận thưởng rồi.<br>
  Mỗi link chỉ dùng được <b style="color:#fff">1 lần</b>.</p>
  <p>Vui lòng tạo link mới từ bot.</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Tạo link mới</a>
  <div class="copy">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_LIMIT = """<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đạt Giới Hạn</title>""" + _CSS + """</head><body>
<div class="card">
  <div class="icon">🚫</div>
  <span class="badge br">GIỚI HẠN THIẾT BỊ</span>
  <h1 style="color:#f87171">Đã Đạt Giới Hạn</h1>
  <p style="margin-top:10px">
    Thiết bị này đã vượt tối đa <b style="color:#fff">{{ limit }} lần</b>
    cho <b style="color:#fff">{{ name }}</b>.
  </p>
  <p>Thử loại link khác hoặc liên hệ admin.</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="copy">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

PAGE_ERROR = """<!DOCTYPE html><html lang="vi"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lỗi</title>""" + _CSS + """</head><body>
<div class="card">
  <div class="icon">❌</div>
  <span class="badge br">TOKEN KHÔNG HỢP LỆ</span>
  <h1 style="color:#f87171">Link Không Hợp Lệ</h1>
  <p style="margin-top:10px">Link không tồn tại hoặc đã hết hạn.<br>
  Vui lòng tạo link mới từ bot.</p>
  <hr>
  <a class="btn" href="https://t.me/{{ bot }}">🤖 Quay lại Bot</a>
  <div class="copy">© Bot Kiếm Tiền Online — Lê Trung Dũng</div>
</div></body></html>"""

# ══════════════════════════════════════════
#  ROUTE CHÍNH: /done/<token>
# ══════════════════════════════════════════

@app.route("/done/<token>")
def done(token: str):
    ip  = real_ip()
    cur = get_cursor()

    # 1. Tra token
    cur.execute("SELECT user_id,link_type,reward,status FROM vuotlink_tokens WHERE token=?", (token,))
    row = cur.fetchone()

    if not row:
        print(f"[WARN] Token không tồn tại: {token[:10]}...")
        return render_template_string(PAGE_ERROR, bot=BOT_USERNAME), 404

    user_id   = row["user_id"]
    link_type = row["link_type"]
    reward    = row["reward"]
    status    = row["status"]

    print(f"[INFO] /done token={token[:10]}... | user={user_id} | type={link_type} | status={status}")

    # 2. Đã nhận rồi
    if status == "approved":
        return render_template_string(PAGE_USED, bot=BOT_USERNAME), 200

    # 3. Kiểm tra giới hạn IP
    limit   = LIMIT_VUOTLINK1 if link_type == "vuotlink1" else LIMIT_VUOTLINK2
    allowed, used = check_limit(ip, link_type, limit)

    if not allowed:
        name = "Vượt Link 1" if link_type == "vuotlink1" else "Vượt Link 2"
        print(f"[LIMIT] IP={ip} đã đạt giới hạn {limit} lần cho {link_type}")
        return render_template_string(PAGE_LIMIT, limit=limit, name=name,
                                      bot=BOT_USERNAME), 429

    # 4. Cộng tiền vào DB
    balance = credit_user(token, user_id, reward)
    pct     = min(100, round(used / limit * 100))

    print(f"[✅ CREDITED] user={user_id} | +{reward}đ | balance={balance}đ | lượt={used}/{limit}")

    # 5. Gửi thông báo Telegram cho user
    ok = send_telegram(
        user_id,
        f"✅ *Vượt link thành công!*\n"
        f"💰 Bạn nhận: *+{vnd(reward)}đ*\n"
        f"🏦 Số dư: *{vnd(balance)}đ*\n"
        f"📊 Lượt đã dùng: *{used}/{limit}*\n\n"
        f"👉 Tiếp tục: /vuotlink1 hoặc /vuotlink2"
    )
    if not ok:
        print(f"[WARN] Gửi Telegram thất bại cho user_id={user_id}")

    # 6. Trả trang thành công
    return render_template_string(
        PAGE_SUCCESS,
        reward  = vnd(reward),
        balance = vnd(balance),
        used    = used,
        limit   = limit,
        pct     = pct,
        bot     = BOT_USERNAME,
    ), 200


# ══════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════

@app.route("/")
def index():
    return {"status": "running", "bot": f"@{BOT_USERNAME}",
            "project": "Bot Kiếm Tiền — Lê Trung Dũng v5.1"}


@app.route("/ping")
def ping():
    return "pong", 200


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║  Webhook — Lê Trung Dũng Bot v5.1        ║")
    print(f"║  Port: {PORT}                               ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Callback URL: https://chao-6sag.onrender.com/done/<token>")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
from flask import Flask, request, jsonify

app = Flask(__name__)

# ══════════════════════════════════════════
#  KẾT NỐI DATABASE
# ══════════════════════════════════════════

def get_db():
    """Mở kết nối SQLite — thread-safe mỗi request."""
    db_path = os.environ.get("DB_PATH", DB_PATH)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ══════════════════════════════════════════
#  GỬI TIN NHẮN TELEGRAM
# ══════════════════════════════════════════

def send_telegram(chat_id: int, text: str) -> bool:
    """Gọi Bot API để gửi thông báo cho user."""
    token = os.environ.get("BOT_TOKEN", BOT_TOKEN)
    url   = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[TG ERROR] {e}")
        return False


# ══════════════════════════════════════════
#  HTML RESPONSE TEMPLATES
# ══════════════════════════════════════════

HTML_SUCCESS = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>✅ Vượt Link Thành Công</title>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:'Segoe UI',sans-serif;background:#0f172a;
         display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#1e293b;border-radius:16px;padding:40px 32px;
           max-width:420px;width:90%;text-align:center;
           box-shadow:0 20px 60px rgba(0,0,0,.5)}}
    .icon{{font-size:64px;margin-bottom:16px}}
    h1{{color:#22c55e;font-size:1.6rem;margin-bottom:12px}}
    p{{color:#94a3b8;font-size:1rem;line-height:1.6;margin-bottom:8px}}
    .reward{{color:#facc15;font-size:1.3rem;font-weight:700;margin:16px 0}}
    .footer{{margin-top:24px;color:#475569;font-size:.8rem}}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🎉</div>
    <h1>Vượt Link Thành Công!</h1>
    <p>Phần thưởng đã được cộng vào tài khoản của bạn.</p>
    <div class="reward">+{reward:,}đ</div>
    <p>Kiểm tra số dư bằng lệnh <strong>/profile</strong> trên Telegram.</p>
    <div class="footer">© Lê Trung Dũng Bot v4.0</div>
  </div>
</body>
</html>"""

HTML_ERROR = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>⚠️ Lỗi Xác Thực</title>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:'Segoe UI',sans-serif;background:#0f172a;
         display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#1e293b;border-radius:16px;padding:40px 32px;
           max-width:420px;width:90%;text-align:center;
           box-shadow:0 20px 60px rgba(0,0,0,.5)}}
    .icon{{font-size:64px;margin-bottom:16px}}
    h1{{color:#ef4444;font-size:1.6rem;margin-bottom:12px}}
    p{{color:#94a3b8;font-size:1rem;line-height:1.6}}
    .footer{{margin-top:24px;color:#475569;font-size:.8rem}}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h1>{title}</h1>
    <p>{message}</p>
    <div class="footer">© Lê Trung Dũng Bot v4.0</div>
  </div>
</body>
</html>"""


def ok_page(reward: int):
    return HTML_SUCCESS.format(reward=reward), 200, {"Content-Type": "text/html; charset=utf-8"}


def err_page(title: str, message: str, status: int = 400):
    return HTML_ERROR.format(title=title, message=message), status, {"Content-Type": "text/html; charset=utf-8"}


# ══════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════

@app.route("/")
def index():
    """Health-check cho Render."""
    return jsonify({"status": "ok", "service": "LeTrungDung Webhook v4.0"}), 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/done/<token>", methods=["GET"])
def done(token: str):
    """
    Endpoint được gọi sau khi user hoàn thành vượt link.

    Quy trình:
      1. Kiểm tra token tồn tại và còn 'pending'
      2. Cộng reward vào balance
      3. Đánh dấu token 'completed'
      4. Gửi thông báo Telegram
      5. Trả HTML thành công
    """

    if not token or len(token) != 40:
        return err_page("Token Không Hợp Lệ",
                        "Token không đúng định dạng. Vui lòng thử lại hoặc liên hệ /support.", 400)

    con = get_db()
    try:
        cur = con.cursor()

        # ── Tra cứu token ──
        cur.execute(
            "SELECT user_id, link_type, reward, status FROM vuotlink_tokens WHERE token = ?",
            (token,)
        )
        row = cur.fetchone()

        if not row:
            return err_page("Token Không Tồn Tại",
                            "Link này không hợp lệ hoặc đã hết hạn. Vui lòng tạo link mới.", 404)

        user_id, link_type, reward, status = row["user_id"], row["link_type"], row["reward"], row["status"]

        # ── Kiểm tra trùng lặp ──
        if status == "completed":
            return err_page("Đã Được Xử Lý",
                            "Link này đã được ghi nhận trước đó. Số tiền chỉ được cộng 1 lần.", 409)

        if status == "expired":
            return err_page("Link Hết Hạn",
                            "Token đã hết hạn. Vui lòng tạo link mới bằng /vuotlink1 hoặc /vuotlink2.", 410)

        # ── Cộng tiền ──
        cur.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (reward, user_id)
        )

        # ── Đánh dấu hoàn thành ──
        cur.execute(
            "UPDATE vuotlink_tokens SET status = 'completed' WHERE token = ?",
            (token,)
        )

        con.commit()
        print(f"[DONE] user={user_id} | type={link_type} | reward={reward}đ | token={token[:10]}...")

        # ── Gửi Telegram ──
        link_num = "1" if link_type == "vuotlink1" else "2"
        send_telegram(
            user_id,
            f"✅ *Vượt Link {link_num} thành công!*\n\n"
            f"💰 Phần thưởng: *+{reward:,}đ*\n"
            f"📊 Kiểm tra số dư: /profile\n\n"
            f"© Lê Trung Dũng Bot v4.0",
        )

        # ── Thông báo Admin ──
        admin_id = int(os.environ.get("ADMIN_ID", ADMIN_ID))
        send_telegram(
            admin_id,
            f"📥 *Webhook nhận thành công*\n"
            f"👤 User ID: `{user_id}`\n"
            f"🔗 Loại link: {link_type}\n"
            f"💵 Reward: +{reward:,}đ",
        )

        return ok_page(reward)

    except sqlite3.Error as e:
        print(f"[DB ERROR] {e}")
        return err_page("Lỗi Hệ Thống",
                        "Có lỗi xảy ra khi xử lý. Vui lòng liên hệ /support.", 500)
    finally:
        con.close()


# ══════════════════════════════════════════
#  MAIN — chạy trực tiếp hoặc qua gunicorn
# ══════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", PORT))
    print(f"🚀 Webhook server khởi động tại port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
