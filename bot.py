"""
bot.py — Bot 主程式

負責初始化 Telegram Bot、註冊 Handler 並啟動 polling。
Bot Token 透過環境變數 BOT_TOKEN 傳入。
"""

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from calculator import compute_result
from formatter import format_help, format_reply

logger = logging.getLogger(__name__)


def parse_input(text: str) -> tuple | str:
    """
    解析 '{ID} {累計總分} {次數}' 格式的輸入字串。
    成功時回傳 (id_, score, count)，失敗時回傳錯誤訊息字串。
    """
    parts = text.split()
    if len(parts) != 3:
        return "❌ 格式錯誤！請使用格式：{ID} {累計總分} {次數}\n例如：小貓 232 4"

    id_, score_str, count_str = parts

    try:
        score = int(score_str)
    except ValueError:
        return "❌ 累計總分必須為整數，例如：232"

    try:
        count = int(count_str)
    except ValueError:
        return "❌ 次數必須為整數，例如：4"

    if score < 0:
        return "❌ 累計總分必須為非負整數"

    if count < 0 or count > 24:
        return "❌ 次數必須介於 0 至 24 之間"

    return (id_, score, count)


async def handle_help(update: Update, context) -> None:
    """處理 /start 與 /help 指令。"""
    await update.message.reply_text(format_help())


async def handle_message(update: Update, context) -> None:
    """處理一般文字訊息。"""
    try:
        text = update.message.text
        result = parse_input(text)
        if isinstance(result, str):
            await update.message.reply_text(result)
        else:
            id_, score, count = result
            data = compute_result(id_, score, count)
            await update.message.reply_text(format_reply(data))
    except Exception as e:
        logger.error("Telegram API error: %s", e, exc_info=True)


def main() -> None:
    """初始化 Application，註冊 Handler，啟動 polling。"""
    load_dotenv()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("錯誤：未設定環境變數 BOT_TOKEN")
        raise SystemExit(1)

    logging.basicConfig(level=logging.INFO)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_help))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
