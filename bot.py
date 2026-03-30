"""
bot.py — Bot 主程式

輸入模式：
  1. 單一數字（如 60）：加入本期累計，自動計算
  2. {ID} {累計總分} {次數}：完整格式，直接計算
  /reset：清除本期累計紀錄

callback_data 格式：
  稱號選擇：  t_{score}_{count}_{title_idx}
  技能確認：  b_{score}_{count}_{title_idx}_{bonus}
  技能切換：  x_{score}_{count}_{title_idx}_{bonus}
"""

import asyncio
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

from calculator import compute_result, recommend_combinations
from formatter import format_help, format_recommendation, format_summary

logger = logging.getLogger(__name__)

KEY_SCORES = "scores"
KEY_ID = "uid"

TITLE_NAMES = ["無稱號", "青銅花匠", "白銀花匠", "黃金花匠", "大師花匠", "王者花匠"]

# bonus 位元：bit0 = +1技能, bit1 = +2技能
BONUS_LABELS = {0: "無加成", 1: "+1 技能", 2: "+2 技能", 3: "+1 & +2 技能"}


def parse_full(text: str) -> tuple | str:
    parts = text.split()
    if len(parts) != 3:
        return "❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60"
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


def _build_title_keyboard(data: dict) -> InlineKeyboardMarkup | None:
    """建立目標稱號選擇按鈕。callback_data: t_{score}_{count}_{title_idx}"""
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
        cb = f"t_{score}_{count}_{title_idx}"
        buttons.append([InlineKeyboardButton(f"🎯 {name}", callback_data=cb)])

    return InlineKeyboardMarkup(buttons)


def _build_bonus_keyboard(score: int, count: int, title_idx: int, bonus: int) -> InlineKeyboardMarkup:
    """建立技能加成選擇按鈕（4個獨立選項）。
    bonus 為 4-bit 旗標：bit0=56+1, bit1=56+2, bit2=60+1, bit3=60+2
    """
    options = [
        (0, "56+1（57分）"),
        (1, "56+2（58分）"),
        (2, "60+1（61分）"),
        (3, "60+2（62分）"),
    ]
    buttons = []
    for bit, label in options:
        checked = bool(bonus & (1 << bit))
        new_bonus = bonus ^ (1 << bit)
        cb = f"x_{score}_{count}_{title_idx}_{new_bonus}"
        buttons.append([InlineKeyboardButton(
            f"{'✅' if checked else '⬜'} {label}",
            callback_data=cb
        )])

    btn_confirm = InlineKeyboardButton(
        "✔️ 計算",
        callback_data=f"b_{score}_{count}_{title_idx}_{bonus}"
    )
    buttons.append([btn_confirm])
    return InlineKeyboardMarkup(buttons)


async def _send_result(update: Update, data: dict) -> None:
    await update.message.reply_text(format_summary(data))
    keyboard = _build_title_keyboard(data)
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

        parts = query.data.split("_")
        action = parts[0]

        if action == "t":
            # 選完稱號 → 顯示技能加成選項
            score, count, title_idx = int(parts[1]), int(parts[2]), int(parts[3])
            target = TITLE_NAMES[title_idx]
            keyboard = _build_bonus_keyboard(score, count, title_idx, bonus=0)
            await query.edit_message_text(
                f"🎯 目標：{target}\n\n請選擇是否有競賽技能加成（可複選）：\n若沒有加成，請直接按「✔️ 計算」",
                reply_markup=keyboard
            )

        elif action == "x":
            # 切換技能選項（更新按鈕狀態）
            score, count, title_idx, bonus = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            target = TITLE_NAMES[title_idx]
            keyboard = _build_bonus_keyboard(score, count, title_idx, bonus)
            await query.edit_message_text(
                f"🎯 目標：{target}\n\n請選擇是否有競賽技能加成（可複選）：\n若沒有加成，請直接按「✔️ 計算」",
                reply_markup=keyboard
            )

        elif action == "b":
            # 確認計算
            score, count, title_idx, bonus = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            target = TITLE_NAMES[title_idx]

            id_ = context.user_data.get(KEY_ID) or (
                query.from_user.username or query.from_user.first_name or str(query.from_user.id)
            )

            data = compute_result(id_, score, count)
            # 用 bonus 重新計算推薦組合
            gap_entry = next((g for _, n, g in data["higher_titles"] if n == target), None)
            if gap_entry is not None:
                remaining_slots = data["remaining_slots"]
                combos = recommend_combinations(score, score + gap_entry, remaining_slots, bonus)
            else:
                combos = None

            reply = format_recommendation(data, target, combos, bonus)
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

    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", 8443))

    if webhook_url:
        async def run_all():
            from aiohttp import web
            from line_bot import create_line_handler

            line_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
            line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

            async def health(request):
                return web.Response(text="OK")

            async def webhook_handler(request):
                data = await request.json()
                from telegram import Update as TGUpdate
                update = TGUpdate.de_json(data, app.bot)
                await app.process_update(update)
                return web.Response(text="OK")

            # 先啟動 HTTP server，讓 Render health check 通過
            http_app = web.Application()
            http_app.router.add_get("/", health)
            http_app.router.add_post("/webhook", webhook_handler)
            if line_secret and line_token:
                http_app.router.add_post("/line-webhook", create_line_handler(line_secret, line_token))
                logger.info("LINE webhook registered at /line-webhook")

            runner = web.AppRunner(http_app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info(f"HTTP server started on port {port}")

            # 再初始化 Bot
            await app.initialize()
            await app.bot.set_webhook(f"{webhook_url}/webhook")
            await app.start()
            logger.info("Bot started")

            await asyncio.Event().wait()

        asyncio.run(run_all())
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
