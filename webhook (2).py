#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════╗
║     WEBHOOK SERVER — Lê Trung Dũng       ║
║     Phiên bản: 4.0 — Render Deploy       ║
║     Route: GET /done/<token>             ║
╚══════════════════════════════════════════╝

Luồng hoạt động:
  1. User click monetized_link → xem quảng cáo xong
  2. API (link4m / uptolink) redirect → GET /done/<token>
  3. Webhook tra DB → xác thực token còn "pending"
  4. Cộng tiền vào balance + đánh dấu "completed"
  5. Gửi thông báo Telegram cho user
  6. Trả về trang HTML thông báo thành công
"""

# ══════════════════════════════════════════
#  CẤU HÌNH — giữ đồng bộ với anhdung.py
# ══════════════════════════════════════════

BOT_TOKEN      = "8267142566:AAFJOpcVA1Js9VwFjbAwhJHQ35xWS55seRs"
ADMIN_ID       = 6993504486
WEBHOOK_SECRET = "LeTrungDung_SecretKey_2025"   # chỉ dùng nếu cần xác thực thêm
DB_PATH        = "vipbot.db"                     # cùng thư mục với anhdung.py
PORT           = 8080                            # Render tự inject qua biến PORT

# ══════════════════════════════════════════
#  IMPORT
# ══════════════════════════════════════════

import os
import sqlite3
import requests
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
