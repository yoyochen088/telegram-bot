"""
line_bot.py — LINE Bot 處理邏輯

使用 PostbackAction 讓按鈕點擊不顯示內部指令文字。

Postback data 格式：
  任務數選擇：    slots|{score}|{count}|{max_slots}
  最高分選擇：    maxscore|{score}|{count}|{max_slots}|{max_score}
  進階加成切換：  bonus|{score}|{count}|{max_slots}|{max_score}|{bonus}
  進階加成確認：  confirm|{score}|{count}|{max_slots}|{max_score}|{bonus}
  稱號選擇：      title|{target}|{score}|{count}|{max_slots}|{max_score}|{bonus}
"""

import asyncio
import logging

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
)
from linebot.v3.webhooks import MessageEvent, PostbackEvent, TextMessageContent

from calculator import compute_result, recommend_combinations
from formatter import format_summary, format_recommendation

logger = logging.getLogger(__name__)

TITLE_NAMES = ["無稱號", "青銅花匠", "白銀花匠", "黃金花匠", "大師花匠", "王者花匠"]
SLOT_OPTIONS = [18, 24]
MAX_SCORE_OPTIONS = [60, 56, 50, 46, 28]

_user_state: dict = {}
KEY_SCORES = "scores"
KEY_ID = "uid"
KEY_MAX_SLOTS = "max_slots"
KEY_MAX_SCORE = "max_score"


def _get_state(user_id: str) -> dict:
    if user_id not in _user_state:
        _user_state[user_id] = {KEY_SCORES: [], KEY_ID: None, KEY_MAX_SLOTS: None, KEY_MAX_SCORE: None}
    return _user_state[user_id]


def _build_slots_quick_reply(score: int, count: int) -> QuickReply:
    items = [
        QuickReplyItem(action=PostbackAction(
            label=f"📋 {n} 個任務",
            data=f"slots|{score}|{count}|{n}",
            display_text=f"{n} 個任務"
        ))
        for n in SLOT_OPTIONS
    ]
    return QuickReply(items=items)


def _build_max_score_quick_reply(score: int, count: int, max_slots: int) -> QuickReply:
    items = [
        QuickReplyItem(action=PostbackAction(
            label=str(n),
            data=f"maxscore|{score}|{count}|{max_slots}|{n}",
            display_text=str(n)
        ))
        for n in MAX_SCORE_OPTIONS
    ]
    return QuickReply(items=items)


def _build_bonus_quick_reply(score: int, count: int, max_slots: int, max_score: int, bonus: int) -> QuickReply:
    """進階加成選擇，依 max_score 決定顯示哪些選項。"""
    options = []
    if max_score >= 56:
        options += [(0, "56+1"), (1, "56+2")]
    if max_score >= 60:
        options += [(2, "60+1"), (3, "60+2")]

    checked_labels = {True: "✅", False: "⬜"}

    # 無加成直接確認
    items = [QuickReplyItem(action=PostbackAction(
        label="✔️無加成直接算",
        data=f"confirm|{score}|{count}|{max_slots}|{max_score}|0",
        display_text="無進階加成"
    ))]
    for bit, label in options:
        checked = bool(bonus & (1 << bit))
        new_bonus = bonus ^ (1 << bit)
        items.append(QuickReplyItem(action=PostbackAction(
            label=f"{checked_labels[checked]}{label}",
            data=f"bonus|{score}|{count}|{max_slots}|{max_score}|{new_bonus}",
            display_text=f"{checked_labels[checked]}{label}"
        )))
    # 若已勾選任何加成，加確認按鈕
    if bonus != 0:
        items.append(QuickReplyItem(action=PostbackAction(
            label="✔️確認加成繼續",
            data=f"confirm|{score}|{count}|{max_slots}|{max_score}|{bonus}",
            display_text="確認加成"
        )))
    return QuickReply(items=items)


def _build_title_quick_reply(data: dict, score: int, count: int, max_slots: int, max_score: int, bonus: int) -> QuickReply | None:
    achievable = [
        name
        for _, name, _ in reversed(data["higher_titles"])
        if data["recommendations"].get(name) is not None
    ]
    if not achievable:
        return None

    items = [
        QuickReplyItem(action=PostbackAction(
            label=name,
            data=f"title|{name}|{score}|{count}|{max_slots}|{max_score}|{bonus}",
            display_text=name
        ))
        for name in achievable
    ]
    return QuickReply(items=items)


async def _show_summary_and_titles(score: int, count: int, max_slots: int, max_score: int, bonus: int,
                                    user_id: str, reply_token: str, api: MessagingApi) -> None:
    """顯示摘要並詢問目標稱號（選完進階加成後呼叫）。"""
    state = _get_state(user_id)
    id_ = state.get(KEY_ID) or user_id

    data = compute_result(id_, score, count, max_slots, max_score)
    # 用實際 bonus 重新計算 recommendations
    from calculator import calc_remaining_slots
    remaining = calc_remaining_slots(count, max_slots)
    data["recommendations"] = {
        name: recommend_combinations(score, threshold, remaining, bonus=bonus, max_score=max_score)
        for threshold, name, _ in data["higher_titles"]
    } if remaining > 0 else {}

    summary = format_summary(data)
    quick_reply = _build_title_quick_reply(data, score, count, max_slots, max_score, bonus)

    msg_text = summary
    if quick_reply:
        msg_text += "\n\n請選擇本期目標稱號："

    await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text=msg_text, quick_reply=quick_reply)]
    ))


async def _process_postback(data: str, user_id: str, reply_token: str, api: MessagingApi) -> None:
    """處理 Postback 事件的核心邏輯。"""
    state = _get_state(user_id)
    parts = data.split("|")
    action = parts[0]

    if action == "slots":
        # 選完任務數 → 詢問最高可接分數
        score, count, max_slots = int(parts[1]), int(parts[2]), int(parts[3])
        state[KEY_MAX_SLOTS] = max_slots
        quick_reply = _build_max_score_quick_reply(score, count, max_slots)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"✅ 本週預計 {max_slots} 個任務\n\n請選擇你最高能接的加倍任務分數：",
                quick_reply=quick_reply
            )]
        ))

    elif action == "maxscore":
        # 選完最高分 → 若 ≥ 56 先問進階加成，否則直接顯示摘要
        score, count, max_slots, max_score = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
        state[KEY_MAX_SCORE] = max_score

        if max_score >= 56:
            quick_reply = _build_bonus_quick_reply(score, count, max_slots, max_score, 0)
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=f"✅ 最高可接 {max_score} 分任務\n\n是否有進階加成？（可複選）\n若沒有加成，請直接按「✔️無加成直接算」",
                    quick_reply=quick_reply
                )]
            ))
        else:
            await _show_summary_and_titles(score, count, max_slots, max_score, 0, user_id, reply_token, api)

    elif action == "bonus":
        # 切換進階加成選項（更新按鈕狀態）
        score, count, max_slots, max_score, bonus = (
            int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
        )
        quick_reply = _build_bonus_quick_reply(score, count, max_slots, max_score, bonus)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"✅ 最高可接 {max_score} 分任務\n\n是否有進階加成？（可複選）\n若沒有加成，請直接按「✔️無加成直接算」",
                quick_reply=quick_reply
            )]
        ))

    elif action == "confirm":
        # 確認進階加成 → 顯示摘要與目標稱號選擇
        score, count, max_slots, max_score, bonus = (
            int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
        )
        await _show_summary_and_titles(score, count, max_slots, max_score, bonus, user_id, reply_token, api)

    elif action == "title":
        # 選完稱號 → 直接計算並顯示推薦
        target, score, count, max_slots, max_score, bonus = (
            parts[1], int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
        )
        id_ = state.get(KEY_ID) or user_id
        data_result = compute_result(id_, score, count, max_slots, max_score)
        gap_entry = next((g for _, n, g in data_result["higher_titles"] if n == target), None)
        combos = recommend_combinations(score, score + gap_entry, data_result["remaining_slots"], bonus, max_score) if gap_entry is not None else None
        reply = format_recommendation(data_result, target, combos, bonus)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        ))


async def handle_line_event(event, api: MessagingApi) -> None:
    """處理 LINE 訊息與 Postback 事件。"""

    if isinstance(event, PostbackEvent):
        await _process_postback(
            event.postback.data,
            event.source.user_id,
            event.reply_token,
            api
        )
        return

    if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessageContent):
        return

    user_id = event.source.user_id
    text = event.message.text.strip()
    state = _get_state(user_id)
    reply_token = event.reply_token

    if text in ("/reset", "重置", "/重置"):
        state[KEY_SCORES] = []
        state[KEY_MAX_SLOTS] = None
        state[KEY_MAX_SCORE] = None
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="✅ 已清除本期累計紀錄，可以重新開始輸入。")]
        ))
        return

    if text in ("/help", "/start", "說明", "help"):
        from formatter import format_help
        max_slots = state.get(KEY_MAX_SLOTS)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=format_help(max_slots))]
        ))
        return

    if text.lstrip("-").isdigit():
        score_input = int(text)
        if score_input <= 0:
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="❌ 分數必須為正整數")]
            ))
            return

        state[KEY_SCORES].append(score_input)
        scores = state[KEY_SCORES]
        total = sum(scores)
        count = len(scores)

        detail = " + ".join(str(s) for s in scores)
        quick_reply = _build_slots_quick_reply(total, count)
        msg_text = (
            f"➕ 已記錄 {score_input} 分\n"
            f"📝 本期累計：{detail} = {total} 分（共 {count} 次）\n\n"
            f"請選擇本週預計要解的任務數："
        )
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=msg_text, quick_reply=quick_reply)]
        ))
        return

    parts = text.split()
    if len(parts) == 3:
        id_, score_str, count_str = parts
        try:
            score, count = int(score_str), int(count_str)
            if score < 0 or not (0 <= count <= 24):
                raise ValueError
        except ValueError:
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60")]
            ))
            return

        state[KEY_ID] = id_
        quick_reply = _build_slots_quick_reply(score, count)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text="請選擇本週預計要解的任務數：",
                quick_reply=quick_reply
            )]
        ))
        return

    await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60\n輸入「說明」查看完整說明")]
    ))


def create_line_handler(channel_secret: str, channel_access_token: str):
    parser = WebhookParser(channel_secret)
    configuration = Configuration(access_token=channel_access_token)

    async def line_webhook(request):
        from aiohttp import web
        signature = request.headers.get("X-Line-Signature", "")
        body = await request.text()

        try:
            events = parser.parse(body, signature)
        except Exception as e:
            logger.error("LINE webhook parse error: %s", e)
            return web.Response(status=400, text="Bad Request")

        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            for event in events:
                try:
                    await handle_line_event(event, api)
                except Exception as e:
                    logger.error("LINE event error: %s", e, exc_info=True)

        return web.Response(text="OK")

    return line_webhook
