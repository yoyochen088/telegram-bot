"""
line_bot.py — LINE Bot 處理邏輯

與 bot.py 共用 calculator.py 和 formatter.py 的核心邏輯。
使用 aiohttp 接收 LINE Webhook，整合進同一個 HTTP server。
"""

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
    MessageAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from calculator import compute_result, recommend_combinations
from formatter import format_summary, format_recommendation

logger = logging.getLogger(__name__)

TITLE_NAMES = ["無稱號", "青銅花匠", "白銀花匠", "黃金花匠", "大師花匠", "王者花匠"]

# 每個使用者的狀態：{user_id: {"scores": [], "uid": str, "pending": {...}}}
_user_state: dict = {}

KEY_SCORES = "scores"
KEY_ID = "uid"
KEY_PENDING = "pending"  # 等待使用者選擇稱號/技能時暫存資料


def _get_state(user_id: str) -> dict:
    if user_id not in _user_state:
        _user_state[user_id] = {KEY_SCORES: [], KEY_ID: None, KEY_PENDING: None}
    return _user_state[user_id]


def _build_title_quick_reply(data: dict, score: int, count: int) -> QuickReply | None:
    """建立目標稱號選擇的 Quick Reply 按鈕。"""
    achievable = [
        name
        for _, name, _ in reversed(data["higher_titles"])
        if data["recommendations"].get(name) is not None
    ]
    if not achievable:
        return None

    items = [
        QuickReplyItem(action=MessageAction(label=name, text=f"__title__{name}__{score}__{count}"))
        for name in achievable
    ]
    return QuickReply(items=items)


def _build_bonus_quick_reply(target: str, score: int, count: int, bonus: int) -> QuickReply:
    """建立技能加成選擇的 Quick Reply 按鈕。"""
    options = [
        (0, "56+1"),
        (1, "56+2"),
        (2, "60+1"),
        (3, "60+2"),
    ]
    items = []
    for bit, label in options:
        checked = "✅" if (bonus & (1 << bit)) else "⬜"
        new_bonus = bonus ^ (1 << bit)
        items.append(QuickReplyItem(
            action=MessageAction(
                label=f"{checked}{label}",
                text=f"__bonus__{target}__{score}__{count}__{new_bonus}"
            )
        ))
    items.append(QuickReplyItem(
        action=MessageAction(label="✔️ 計算", text=f"__calc__{target}__{score}__{count}__{bonus}")
    ))
    return QuickReply(items=items)


async def handle_line_event(event: MessageEvent, api: MessagingApi) -> None:
    """處理 LINE 文字訊息事件。"""
    if not isinstance(event.message, TextMessageContent):
        return

    user_id = event.source.user_id
    text = event.message.text.strip()
    state = _get_state(user_id)

    reply_token = event.reply_token

    # 內部指令：選擇稱號
    if text.startswith("__title__"):
        parts = text.split("__")
        # __title__{name}__{score}__{count}
        target = parts[2]
        score = int(parts[3])
        count = int(parts[4])
        bonus = 0
        quick_reply = _build_bonus_quick_reply(target, score, count, bonus)
        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"🎯 目標：{target}\n\n請選擇是否有競賽技能加成（可複選）：",
                quick_reply=quick_reply
            )]
        ))
        return

    # 內部指令：切換技能
    if text.startswith("__bonus__"):
        parts = text.split("__")
        target = parts[2]
        score = int(parts[3])
        count = int(parts[4])
        bonus = int(parts[5])
        quick_reply = _build_bonus_quick_reply(target, score, count, bonus)
        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"🎯 目標：{target}\n\n請選擇是否有競賽技能加成（可複選）：",
                quick_reply=quick_reply
            )]
        ))
        return

    # 內部指令：確認計算
    if text.startswith("__calc__"):
        parts = text.split("__")
        target = parts[2]
        score = int(parts[3])
        count = int(parts[4])
        bonus = int(parts[5])
        id_ = state.get(KEY_ID) or user_id
        data = compute_result(id_, score, count)
        gap_entry = next((g for _, n, g in data["higher_titles"] if n == target), None)
        if gap_entry is not None:
            combos = recommend_combinations(score, score + gap_entry, data["remaining_slots"], bonus)
        else:
            combos = None
        reply = format_recommendation(data, target, combos, bonus)
        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        ))
        return

    # /reset 或 重置
    if text in ("/reset", "重置", "/重置"):
        state[KEY_SCORES] = []
        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="✅ 已清除本期累計紀錄，可以重新開始輸入。")]
        ))
        return

    # /help 或 說明
    if text in ("/help", "/start", "說明", "help"):
        from formatter import format_help
        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=format_help())]
        ))
        return

    # 單筆數字模式
    if text.lstrip("-").isdigit():
        score_input = int(text)
        if score_input <= 0:
            await api.reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="❌ 分數必須為正整數")]
            ))
            return

        state[KEY_SCORES].append(score_input)
        scores = state[KEY_SCORES]
        total = sum(scores)
        count = len(scores)
        id_ = state.get(KEY_ID) or user_id

        detail = " + ".join(str(s) for s in scores)
        data = compute_result(id_, total, count)
        summary = format_summary(data)

        quick_reply = _build_title_quick_reply(data, total, count)
        msg_text = f"➕ 已記錄 {score_input} 分\n📝 本期累計：{detail} = {total} 分（共 {count} 次）\n\n{summary}"

        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=msg_text,
                quick_reply=quick_reply
            )]
        ))
        return

    # 完整格式 {ID} {累計總分} {次數}
    parts = text.split()
    if len(parts) == 3:
        id_, score_str, count_str = parts
        try:
            score, count = int(score_str), int(count_str)
            if score < 0 or not (0 <= count <= 24):
                raise ValueError
        except ValueError:
            await api.reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60")]
            ))
            return

        state[KEY_ID] = id_
        data = compute_result(id_, score, count)
        summary = format_summary(data)
        quick_reply = _build_title_quick_reply(data, score, count)

        await api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=summary, quick_reply=quick_reply)]
        ))
        return

    # 無法識別的輸入
    await api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60\n輸入「說明」查看完整說明")]
    ))


def create_line_handler(channel_secret: str, channel_access_token: str):
    """建立 LINE webhook handler，回傳 aiohttp request handler。"""
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
                if isinstance(event, MessageEvent):
                    try:
                        await handle_line_event(event, api)
                    except Exception as e:
                        logger.error("LINE event error: %s", e, exc_info=True)

        return web.Response(text="OK")

    return line_webhook
