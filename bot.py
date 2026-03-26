"""
bot.py — Bot 主程式

負責初始化 Telegram Bot、註冊 Handler 並啟動 polling。
Bot Token 透過環境變數 BOT_TOKEN 傳入。

輸入模式：
  1. 單一數字（如 60）：將該分數加入本期累計，自動計算
  2. {ID} {累計總分} {次數}：完整格式，直接計算
  /reset：清除本期累計紀錄
"""

import json
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

# user_data keys
KEY_SCORES = "scores"   # list[int]：本期每次輸入的分數
KEY_ID = "user_id"      # str：使用者 ID（從完整格式取得，預設用 Telegram 名稱）


def parse_full(text: str) -> tuple | str:
    """解析 '{ID} {累計總分} {次數}' 格式，成功回傳 (id_, score, count)，失敗回傳錯誤字串。"""
    parts = text.split()
    if len(parts) != 3:
        return "❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：小貓 528 4\n單筆格式：直接輸入分數，例如：60"

    id_, score_str, count_str = parts
    try:
        score = int(score_str)
    except ValueError:
        return "❌ 累計總分必須為整數，例如：528"
    try:
        count = int(count_str)
    except ValueError:
        return "❌ 次數必須為整數，例如：4"
    if score < 0:
        return "❌ 累計總分必須為非負整數"
    if count < 0 or count > 24:
        return "❌ 次數必須介於 0 至 24 之間"
    return (id_, score, count)


def _get_display_name(update: Update) -> str:
    """取得使用者顯示名稱。"""
    user = update.effective_user
    return user.username or user.first_name or str(user.id)


async def _send_result(update_or_query, data: dict, is_edit: bool = False) -> None:
    """發送摘要與目標稱號選擇按鈕。"""
    summary = format_summary(data)

    if is_edit:
        await update_or_query.edit_message_text(summary)
    else:
        await update_or_query.message.reply_text(summary)

    if data["title"] == "王者花匠" or data["remaining_slots"] == 0:
        return

    # 倒序：從最高稱號到最低，只列可達成的
    achievable = [
        name
        for _, name, _ in reversed(data["higher_titles"])
        if data["recommendations"].get(name) is not None
    ]
    if not achievable:
        return

    id_ = data["id"]
    score = data["score"]
    count = 24 - data["remaining_slots"]

    buttons = []
    for name in achievable:
        payload = json.dumps(
            {"id": id_, "score": score, "count": count, "target": name},
            ensure_ascii=False,
        )
        buttons.append([InlineKeyboardButton(f"🎯 {name}", callback_data=payload)])

    keyboard = InlineKeyboardMarkup(buttons)
    await update_or_query.message.reply_text("請選擇本期目標稱號：", reply_markup=keyboard)


async def handle_help(update: Update, context) -> None:
    """處理 /start 與 /help 指令。"""
    await update.message.reply_text(format_help())


async def handle_reset(update: Update, context) -> None:
    """清除本期累計紀錄。"""
    context.user_data[KEY_SCORES] = []
    await update.message.reply_text("✅ 已清除本期累計紀錄，可以重新開始輸入。")


async def handle_message(update: Update, context) -> None:
    """處理一般文字訊息。"""
    try:
        text = update.message.text.strip()
        user_data = context.user_data

        # 判斷是否為單一數字（單筆分數模式）
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            score_input = int(text)
            if score_input <= 0:
                await update.message.reply_text("❌ 分數必須為正整數")
                return

            # 累加到本期紀錄
            if KEY_SCORES not in user_data:
                user_data[KEY_SCORES] = []
            user_data[KEY_SCORES].append(score_input)

            scores = user_data[KEY_SCORES]
            total = sum(scores)
            count = len(scores)
            id_ = user_data.get(KEY_ID, _get_display_name(update))

            # 顯示本期累計明細
            detail = " + ".join(str(s) for s in scores)
            await update.message.reply_text(
                f"➕ 已記錄 {score_input} 分\n"
                f"📝 本期累計：{detail} = {total} 分（共 {count} 次）"
            )

            data = compute_result(id_, total, count)
            await _send_result(update, data)
            return

        # 完整格式 {ID} {累計總分} {次數}
        parsed = parse_full(text)
        if isinstance(parsed, str):
            await update.message.reply_text(parsed)
            return

        id_, score, count = parsed
        user_data[KEY_ID] = id_
        # 完整格式不覆蓋累計紀錄，直接用輸入值計算
        data = compute_result(id_, score, count)
        await _send_result(update, data)

    except Exception as e:
        logger.error("handle_message error: %s", e, exc_info=True)


async def handle_callback(update: Update, context) -> None:
    """處理使用者點選目標稱號按鈕。"""
    try:
        query = update.callback_query
        await query.answer()

        payload = json.loads(query.data)
        id_ = payload["id"]
        score = payload["score"]
        count = payload["count"]
        target = payload["target"]

        data = compute_result(id_, score, count)
        combos = data["recommendations"].get(target)
        reply = format_recommendation(data, target, combos)
        await query.edit_message_text(reply)

    except Exception as e:
        logger.error("handle_callback error: %s", e, exc_info=True)


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
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
