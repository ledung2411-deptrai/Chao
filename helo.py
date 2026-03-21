"""
bot.py — Telegram bot xử lý lệnh /vuotlink1
Flow: user gõ lệnh → bot tạo token → gọi API rút gọn → gửi link cho user
"""

import os
import uuid
import aiohttp
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── CẤU HÌNH ────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://yourdomain.com")   # không có / cuối
SHRINK_API_KEY   = os.getenv("SHRINK_API_KEY", "YOUR_SHRINK_API_KEY")        # shrinkme.io hoặc tương tự
SHRINK_API_URL   = "https://shrinkme.io/api"                                 # đổi nếu dùng API khác
REWARD_AMOUNT    = float(os.getenv("REWARD_AMOUNT", "0.005"))                # số tiền thưởng mỗi lượt (USD)
# ─────────────────────────────────────────────────────────────────────────────


async def shorten_url(destination: str) -> str | None:
    """Gọi API rút gọn link có quảng cáo, trả về short URL hoặc None nếu lỗi."""
    params = {
        "api":  SHRINK_API_KEY,
        "url":  destination,
        "format": "json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(SHRINK_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.error("Shrink API HTTP %s", resp.status)
                return None
            data = await resp.json()
            # shrinkme trả về {"status":"success","shortenedUrl":"https://..."}
            if data.get("status") == "success":
                return data.get("shortenedUrl") or data.get("short_url")
            logger.error("Shrink API lỗi: %s", data)
            return None


async def cmd_vuotlink1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /vuotlink1"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # 1. Tạo token duy nhất cho user + lần này
    token = str(uuid.uuid4()).replace("-", "")

    # 2. Đặt link đích là webhook /done/<token>
    #    webhook.py sẽ nhận request này sau khi user xem quảng cáo xong
    destination = f"{WEBHOOK_BASE_URL}/done/{token}"

    # 3. Gọi API rút gọn
    await update.message.reply_text("⏳ Đang tạo link, vui lòng chờ...")
    short_url = await shorten_url(destination)

    if not short_url:
        await update.message.reply_text("❌ Không thể tạo link lúc này. Thử lại sau!")
        return

    # 4. Lưu token vào bot_data để webhook xác nhận sau
    #    bot_data["pending_tokens"][token] = {"user_id": ..., "chat_id": ...}
    pending: dict = context.bot_data.setdefault("pending_tokens", {})
    pending[token] = {
        "user_id":  user.id,
        "chat_id":  chat_id,
        "username": user.username or user.full_name,
        "amount":   REWARD_AMOUNT,
    }

    # 5. Gửi link cho user
    msg = (
        f"🔗 *Link vượt quảng cáo của bạn:*\n\n"
        f"`{short_url}`\n\n"
        f"👆 Click vào link, xem quảng cáo đến hết.\n"
        f"💰 Sau khi hoàn thành bạn sẽ nhận được *${REWARD_AMOUNT:.4f}*!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    logger.info("Tạo link cho user %s | token=%s | short=%s", user.id, token, short_url)


def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("vuotlink1", cmd_vuotlink1))
    logger.info("Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
