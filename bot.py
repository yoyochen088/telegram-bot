"""
bot.py — Bot 主程式

輸入模式：
  1. 單一數字（如 60）：加入本期累計，自動計算
  2. {ID} {累計總分} {次數}：完整格式，直接計算
  /reset：清除本期累計紀錄

callback_data 格式：
  任務數選擇：    s_{score}_{count}_{max_slots}
  最高分選擇：    m_{score}_{count}_{max_slots}_{max_score}
  進階加成切換：  x_{score}_{count}_{max_slots}_{max_score}_{bonus}
  進階加成確認：  p_{score}_{count}_{max_slots}_{max_score}_{bonus}
  稱號選擇：      t_{score}_{count}_{max_slots}_{max_score}_{bonus}_{title_idx}
"""

import asyncio
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
KEY_MAX_SLOTS = "max_slots"
KEY_MAX_SCORE = "max_score"

TITLE_NAMES = ["無稱號", "青銅花匠", "白銀花匠", "黃金花匠", "大師花匠", "王者花匠"]
SLOT_OPTIONS = [18, 24]
MAX_SCORE_OPTIONS = [60, 56, 50, 46, 28]


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


def _build_slots_keyboard(score: int, count: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📋 {n} 個任務", callback_data=f"s_{score}_{count}_{n}")]
        for n in SLOT_OPTIONS
    ]
    return InlineKeyboardMarkup(buttons)


def _build_max_score_keyboard(score: int, count: int, max_slots: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(str(n), callback_data=f"m_{score}_{count}_{max_slots}_{n}")]
        for n in MAX_SCORE_OPTIONS
    ]
    return InlineKeyboardMarkup(buttons)


def _build_bonus_keyboard(score: int, count: int, max_slots: int, max_score: int, bonus: int) -> InlineKeyboardMarkup:
    """進階加成選擇，依 max_score 決定顯示哪些選項。
    四個選項獨立可複選：56+1、56+2、60+1、60+2 可同時存在。
    """
    options = []
    if max_score >= 56:
        options += [(0, "56+1（57分）"), (1, "56+2（58分）")]
    if max_score >= 60:
        options += [(2, "60+1（61分）"), (3, "60+2（62分）")]

    btn_confirm = InlineKeyboardButton(
        "✔️ 確認加成，繼續" if bonus != 0 else "✔️ 無進階加成，直接計算",
        callback_data=f"p_{score}_{count}_{max_slots}_{max_score}_{bonus}"
    )
    buttons = [[btn_confirm]]
    for bit, label in options:
        checked = bool(bonus & (1 << bit))
        new_bonus = bonus ^ (1 << bit)
        cb = f"x_{score}_{count}_{max_slots}_{max_score}_{new_bonus}"
        buttons.append([InlineKeyboardButton(
            f"{'✅' if checked else '⬜'} {label}",
            callback_data=cb
        )])
    return InlineKeyboardMarkup(buttons)


def _build_title_keyboard(data: dict, score: int, count: int, max_slots: int, max_score: int, bonus: int) -> InlineKeyboardMarkup | None:
    if data["title"] == "王者花匠" or data["remaining_slots"] == 0:
        return None

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
        cb = f"t_{score}_{count}_{max_slots}_{max_score}_{bonus}_{title_idx}"
        buttons.append([InlineKeyboardButton(f"🎯 {name}", callback_data=cb)])

    return InlineKeyboardMarkup(buttons)


async def handle_help(update: Update, context) -> None:
    max_slots = context.user_data.get(KEY_MAX_SLOTS)
    await update.message.reply_text(format_help(max_slots))


async def handle_reset(update: Update, context) -> None:
    context.user_data[KEY_SCORES] = []
    context.user_data.pop(KEY_MAX_SLOTS, None)
    context.user_data.pop(KEY_MAX_SCORE, None)
    await update.message.reply_text("✅ 已清除本期累計紀錄，可以重新開始輸入。")


async def handle_message(update: Update, context) -> None:
    try:
        text = update.message.text.strip()
        user_data = context.user_data

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

            detail = " + ".join(str(s) for s in scores)
            await update.message.reply_text(
                f"➕ 已記錄 {score_input} 分\n"
                f"📝 本期累計：{detail} = {total} 分（共 {count} 次）"
            )
            await update.message.reply_text(
                "請選擇本週預計要解的任務數：",
                reply_markup=_build_slots_keyboard(total, count)
            )
            return

        parsed = parse_full(text)
        if isinstance(parsed, str):
            await update.message.reply_text(parsed)
            return

        id_, score, count = parsed
        user_data[KEY_ID] = id_
        await update.message.reply_text(
            "請選擇本週預計要解的任務數：",
            reply_markup=_build_slots_keyboard(score, count)
        )

    except Exception as e:
        logger.error("handle_message error: %s", e, exc_info=True)


async def _show_summary_and_titles(query, score: int, count: int, max_slots: int, max_score: int, bonus: int, context) -> None:
    """顯示摘要並詢問目標稱號（選完進階加成後呼叫）。"""
    id_ = context.user_data.get(KEY_ID) or (
        query.from_user.username or query.from_user.first_name or str(query.from_user.id)
    )
    data = compute_result(id_, score, count, max_slots, max_score)
    # 用實際 bonus 重新計算 recommendations
    from calculator import recommend_combinations as _rc, get_higher_titles, calc_remaining_slots
    remaining = calc_remaining_slots(count, max_slots)
    data["recommendations"] = {
        name: _rc(score, threshold, remaining, bonus=bonus, max_score=max_score)
        for threshold, name, _ in data["higher_titles"]
    } if remaining > 0 else {}

    summary = format_summary(data)
    keyboard = _build_title_keyboard(data, score, count, max_slots, max_score, bonus)

    await query.edit_message_text(summary)
    if keyboard:
        await query.message.reply_text("請選擇本期目標稱號：", reply_markup=keyboard)


async def handle_callback(update: Update, context) -> None:
    try:
        query = update.callback_query
        await query.answer()

        parts = query.data.split("_")
        action = parts[0]

        if action == "s":
            # 選完任務數 → 詢問最高可接分數
            score, count, max_slots = int(parts[1]), int(parts[2]), int(parts[3])
            context.user_data[KEY_MAX_SLOTS] = max_slots
            await query.edit_message_text(
                f"✅ 本週預計 {max_slots} 個任務\n\n請選擇你最高能接的加倍任務分數：",
                reply_markup=_build_max_score_keyboard(score, count, max_slots)
            )

        elif action == "m":
            # 選完最高分 → 若 ≥ 56 先問進階加成，否則直接顯示摘要
            score, count, max_slots, max_score = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            context.user_data[KEY_MAX_SCORE] = max_score

            if max_score >= 56:
                keyboard = _build_bonus_keyboard(score, count, max_slots, max_score, bonus=0)
                await query.edit_message_text(
                    f"✅ 最高可接 {max_score} 分任務\n\n是否有進階加成？（可複選）\n若沒有加成，請直接按「✔️ 無進階加成，直接計算」",
                    reply_markup=keyboard
                )
            else:
                await _show_summary_and_titles(query, score, count, max_slots, max_score, bonus=0, context=context)

        elif action == "x":
            # 切換進階加成選項
            score, count, max_slots, max_score, bonus = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
            keyboard = _build_bonus_keyboard(score, count, max_slots, max_score, bonus)
            await query.edit_message_text(
                f"✅ 最高可接 {max_score} 分任務\n\n是否有進階加成？（可複選）\n若沒有加成，請直接按「✔️ 無進階加成，直接計算」",
                reply_markup=keyboard
            )

        elif action == "p":
            # 確認進階加成 → 顯示摘要與目標稱號選擇
            score, count, max_slots, max_score, bonus = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
            await _show_summary_and_titles(query, score, count, max_slots, max_score, bonus, context)

        elif action == "t":
            # 選完稱號 → 直接計算並顯示推薦
            score, count, max_slots, max_score, bonus, title_idx = (
                int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
            )
            target = TITLE_NAMES[title_idx]

            id_ = context.user_data.get(KEY_ID) or (
                query.from_user.username or query.from_user.first_name or str(query.from_user.id)
            )
            data = compute_result(id_, score, count, max_slots, max_score)
            gap_entry = next((g for _, n, g in data["higher_titles"] if n == target), None)
            combos = recommend_combinations(score, score + gap_entry, data["remaining_slots"], bonus, max_score) if gap_entry is not None else None
            await query.edit_message_text(format_recommendation(data, target, combos, bonus))

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

            await app.initialize()
            await app.bot.set_webhook(f"{webhook_url}/webhook")
            await app.start()
            logger.info("Bot started")

            async def keep_alive():
                import aiohttp as _aiohttp
                while True:
                    await asyncio.sleep(600)
                    try:
                        async with _aiohttp.ClientSession() as session:
                            await session.get(f"{webhook_url}/")
                        logger.info("Keep-alive ping sent")
                    except Exception as e:
                        logger.warning(f"Keep-alive ping failed: {e}")

            asyncio.create_task(keep_alive())
            await asyncio.Event().wait()

        try:
            asyncio.run(run_all())
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
