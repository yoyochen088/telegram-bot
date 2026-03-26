"""
bot.py — Bot 主程式

輸入模式：
  1. 單一數字（如 60）：加入本期累計，自動計算
  2. {ID} {累計總分} {次數}：完整格式，直接計算
  /reset：清除本期累計紀錄
"""

import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from calculator import compute_result
from formatter import format_help, format_recommendation, format_summary

logger = logging.getLogger(__name__)

KEY_SCORES = "scores"
KEY_ID = "uid"

# 稱號索引對照（用於短 callback_data）
TITLE_NAMES = ["無稱號", "青銅花匠", "白銀花匠", "黃金花匠", "大師花匠", "王者花匠"]


def parse_full(text: str) -> tuple | str:
    parts = text.split()
    if len(parts) != 3:
        return "❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：小貓 528 4\n單筆格式：直接輸入分數，例如：60"
    id_, score_str, count_str = parts
    try:
        score = int(score_str)
    except ValueError:
        return "❌ 累計總分必須為整數"
    try:
        count = int(count_str)
    except ValueError:
        return "❌ 次數必須為整數"
    if score < 0:
        return "❌ 累計總分必須為非負整數"
    if count < 0 or count > 24:
        return "❌ 次數必須介於 0 至 24 之間"
    return (id_, score, count)


def _get_display_name(update: Update) -> str:
    user = update.effective_user
    return user.username or user.first_name or str(user.id)


def _build_keyboard(data: dict) -> InlineKeyboardMarkup | None:
    """建立目標稱號選擇按鈕，callback_data 格式：{score}_{count}_{title_index}"""
    if data["title"] == "王者花匠" or data["remaining_slots"] == 0:
        return None

    score = data["score"]
    count = 24 - data["remaining_slots"]

    achievable = [
        name
        for _, name, _ in reversed(data["higher_titles"])
        if data["recommendations"].get(name) is not None
    ]
    if not achievable:
        return None

    buttons = []
    for name in achievable:
        title_idx = TITLE_NAMES.index(name)
        cb = f"{score}_{count}_{title_idx}"  # 最短格式，遠低於 64 bytes
        buttons.append([InlineKeyboardButton(f"🎯 {name}", callback_data=cb)])

    return InlineKeyboardMarkup(buttons)


async def _send_result(update: Update, data: dict) -> None:
    await update.message.reply_text(format_summary(data))
    keyboard = _build_keyboard(data)
    if keyboard:
        await update.message.reply_text("請選擇本期目標稱號：", reply_markup=keyboard)


async def handle_help(update: Update, context) -> None:
    await update.message.reply_text(format_help())


async def handle_reset(update: Update, context) -> None:
    context.user_data[KEY_SCORES] = []
    await update.message.reply_text("✅ 已清除本期累計紀錄，可以重新開始輸入。")


async def handle_message(update: Update, context) -> None:
    try:
        text = update.message.text.strip()
        user_data = context.user_data

        # 單筆數字模式
        if text.lstrip("-").isdigit():
            score_input = int(text)
            if score_input <= 0:
                await update.message.reply_text("❌ 分數必須為正整數")
                return

            if KEY_SCORES not in user_data:
                user_data[KEY_SCORES] = []
            user_data[KEY_SCORES].append(score_input)

            scores = user_data[KEY_SCORES]
            total = sum(scores)
            count = len(scores)
            id_ = user_data.get(KEY_ID, _get_display_name(update))

            detail = " + ".join(str(s) for s in scores)
            await update.message.reply_text(
                f"➕ 已記錄 {score_input} 分\n"
                f"📝 本期累計：{detail} = {total} 分（共 {count} 次）"
            )
            data = compute_result(id_, total, count)
            await _send_result(update, data)
            return

        # 完整格式
        parsed = parse_full(text)
        if isinstance(parsed, str):
            await update.message.reply_text(parsed)
            return

        id_, score, count = parsed
        user_data[KEY_ID] = id_
        data = compute_result(id_, score, count)
        await _send_result(update, data)

    except Exception as e:
        logger.error("handle_message error: %s", e, exc_info=True)


async def handle_callback(update: Update, context) -> None:
    try:
        query = update.callback_query
        await query.answer()

        # 解析短格式 callback_data：{score}_{count}_{title_index}
        parts = query.data.split("_")
        score = int(parts[0])
        count = int(parts[1])
        title_idx = int(parts[2])
        target = TITLE_NAMES[title_idx]

        # 從 user_data 取 ID，若無則用 Telegram 名稱
        id_ = context.user_data.get(KEY_ID) or (
            query.from_user.username or query.from_user.first_name or str(query.from_user.id)
        )

        data = compute_result(id_, score, count)
        combos = data["recommendations"].get(target)
        reply = format_recommendation(data, target, combos)
        await query.edit_message_text(reply)

    except Exception as e:
        logger.error("handle_callback error: %s", e, exc_info=True)


def main() -> None:
    load_dotenv()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("錯誤：未設定環境變數 BOT_TOKEN")
        raise SystemExit(1)

    logging.basicConfig(level=logging.INFO)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_help))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
