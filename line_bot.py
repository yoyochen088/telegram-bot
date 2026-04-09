"""
line_bot.py — LINE Bot 處理邏輯

使用 PostbackAction 讓按鈕點擊不顯示內部指令文字。
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

_user_state: dict = {}
KEY_SCORES = "scores"
KEY_ID = "uid"
KEY_WIZARD = "wizard"  # 引導式輸入狀態

# wizard 步驟
WIZARD_STEPS = ["name", "score", "count", "max_count"]


def _get_state(user_id: str) -> dict:
    if user_id not in _user_state:
        _user_state[user_id] = {KEY_SCORES: [], KEY_ID: None, KEY_WIZARD: None}
    return _user_state[user_id]


def _main_quick_reply() -> QuickReply:
    """常駐主選單 Quick Reply：直接計算、說明、重置。"""
    return QuickReply(items=[
        QuickReplyItem(action=PostbackAction(
            label="🧮直接計算",
            data="menu|calc",
            display_text="計算分數"
        )),
        QuickReplyItem(action=PostbackAction(
            label="📖說明",
            data="menu|help",
            display_text="說明"
        )),
        QuickReplyItem(action=PostbackAction(
            label="🔄重置",
            data="menu|reset",
            display_text="重置"
        )),
    ])


def _build_title_quick_reply(data: dict, score: int, count: int, max_count: int = 24) -> QuickReply | None:
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
            data=f"title|{name}|{score}|{count}|{max_count}",
            display_text=name
        ))
        for name in achievable
    ]
    return QuickReply(items=items)


def _build_bonus_quick_reply(target: str, score: int, count: int, bonus: int, max_count: int = 24) -> QuickReply:
    options = [
        (0, "56+1"),
        (1, "56+2"),
        (2, "60+1"),
        (3, "60+2"),
    ]
    checked_labels = {True: "✅", False: "⬜"}
    items = [QuickReplyItem(action=PostbackAction(
        label="✔️直接計算",
        data=f"calc|{target}|{score}|{count}|{bonus}|{max_count}",
        display_text="直接計算"
    ))]
    for bit, label in options:
        checked = bool(bonus & (1 << bit))
        new_bonus = bonus ^ (1 << bit)
        items.append(QuickReplyItem(action=PostbackAction(
            label=f"{checked_labels[checked]}{label}",
            data=f"bonus|{target}|{score}|{count}|{new_bonus}|{max_count}",
            display_text=f"{checked_labels[checked]}{label}"
        )))
    return QuickReply(items=items)


async def _process_postback(data: str, user_id: str, reply_token: str, api: MessagingApi) -> None:
    """處理 Postback 事件的核心邏輯。"""
    state = _get_state(user_id)
    parts = data.split("|")
    action = parts[0]

    # Rich Menu 按鈕
    if action == "menu":
        if parts[1] == "help":
            from formatter import format_help
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=format_help(), quick_reply=_main_quick_reply())]
            ))
        elif parts[1] == "calc":
            state[KEY_WIZARD] = {"step": "name", "data": {}}
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text="🧮 開始計算分數\n\n請輸入你的名稱（ID）：",
                    quick_reply=_main_quick_reply()
                )]
            ))
        elif parts[1] == "reset":
            state[KEY_SCORES] = []
            state[KEY_WIZARD] = None
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text="✅ 已清除本期累計紀錄，可以重新開始輸入。",
                    quick_reply=_main_quick_reply()
                )]
            ))
        return

    if action == "title":
        target, score, count = parts[1], int(parts[2]), int(parts[3])
        max_count = int(parts[4]) if len(parts) > 4 else 24
        quick_reply = _build_bonus_quick_reply(target, score, count, 0, max_count)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"🎯 目標：{target}\n\n是否有競賽進階加成？（可複選）\n若沒有加成，請直接按「✔️直接計算」",
                quick_reply=quick_reply
            )]
        ))

    elif action == "bonus":
        target, score, count, bonus = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
        max_count = int(parts[5]) if len(parts) > 5 else 24
        quick_reply = _build_bonus_quick_reply(target, score, count, bonus, max_count)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"🎯 目標：{target}\n\n是否有競賽進階加成？（可複選）\n若沒有加成，請直接按「✔️直接計算」",
                quick_reply=quick_reply
            )]
        ))

    elif action == "calc":
        target, score, count, bonus = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
        max_count = int(parts[5]) if len(parts) > 5 else 24
        remaining = max(0, max_count - count)
        id_ = state.get(KEY_ID) or user_id
        data_result = compute_result(id_, score, count)
        data_result["remaining_slots"] = remaining
        # 重新計算 recommendations 用正確的 remaining
        if remaining > 0:
            data_result["recommendations"] = {
                name: recommend_combinations(score, threshold, remaining)
                for threshold, name, _ in data_result["higher_titles"]
            }
        else:
            data_result["recommendations"] = {}
        gap_entry = next((g for _, n, g in data_result["higher_titles"] if n == target), None)
        if gap_entry is not None:
            combos = recommend_combinations(score, score + gap_entry, remaining, bonus)
        else:
            combos = None
        reply = format_recommendation(data_result, target, combos, bonus)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        ))

    elif action == "full_max":
        # 完整格式輸入後選擇最大任務數
        id_, score, count, max_count = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
        remaining = max(0, max_count - count)
        state[KEY_ID] = id_
        data_result = compute_result(id_, score, count)
        data_result["remaining_slots"] = remaining
        if remaining > 0:
            data_result["recommendations"] = {
                name: recommend_combinations(score, threshold, remaining)
                for threshold, name, _ in data_result["higher_titles"]
            }
        else:
            data_result["recommendations"] = {}
        summary = format_summary(data_result)
        quick_reply = _build_title_quick_reply(data_result, score, count, max_count)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"📋 本期上限：{max_count} 個任務，剩餘 {remaining} 個\n\n{summary}",
                quick_reply=quick_reply
            )]
        ))

    elif action == "wizard_max":
        # 引導式輸入最後一步：選擇最大任務數
        max_count = int(parts[1])
        wizard = state.get(KEY_WIZARD)
        if not wizard or "data" not in wizard:
            return
        wdata = wizard["data"]
        id_ = wdata.get("name", user_id)
        score = wdata.get("score", 0)
        count = wdata.get("count", 0)
        state[KEY_ID] = id_
        state[KEY_WIZARD] = None  # 清除 wizard 狀態

        # 用 max_count 覆蓋剩餘名額計算
        # 重新計算：剩餘名額 = max_count - count
        remaining = max_count - count
        if remaining < 0:
            remaining = 0

        data_result = compute_result(id_, score, count)
        # 覆蓋 remaining_slots
        data_result["remaining_slots"] = remaining
        # 重新計算 recommendations
        from calculator import recommend_combinations as rc
        if remaining > 0:
            data_result["recommendations"] = {
                name: rc(score, threshold, remaining)
                for threshold, name, _ in data_result["higher_titles"]
            }
        else:
            data_result["recommendations"] = {}

        summary = format_summary(data_result)
        quick_reply = _build_title_quick_reply(data_result, score, count, max_count)
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"📋 本期上限：{max_count} 個任務，剩餘 {remaining} 個\n\n{summary}",
                quick_reply=quick_reply
            )]
        ))


async def handle_line_event(event, api: MessagingApi) -> None:
    """處理 LINE 訊息與 Postback 事件。"""

    # Postback 事件
    if isinstance(event, PostbackEvent):
        await _process_postback(
            event.postback.data,
            event.source.user_id,
            event.reply_token,
            api
        )
        return

    # 文字訊息事件
    if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessageContent):
        return

    user_id = event.source.user_id
    text = event.message.text.strip()
    state = _get_state(user_id)
    reply_token = event.reply_token

    # 引導式輸入 wizard 流程
    wizard = state.get(KEY_WIZARD)
    if wizard:
        step = wizard["step"]
        wdata = wizard["data"]

        if step == "name":
            wdata["name"] = text
            wizard["step"] = "score"
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=f"👤 名稱：{text}\n\n請輸入目前累計總分：")]
            ))
            return

        elif step == "score":
            try:
                wdata["score"] = int(text)
                if wdata["score"] < 0:
                    raise ValueError
            except ValueError:
                await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text="❌ 請輸入有效的非負整數分數：")]
                ))
                return
            wizard["step"] = "count"
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=f"📊 目前總分：{wdata['score']} 分\n\n請輸入目前已完成的任務數（0–24）：")]
            ))
            return

        elif step == "count":
            try:
                wdata["count"] = int(text)
                if not (0 <= wdata["count"] <= 24):
                    raise ValueError
            except ValueError:
                await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text="❌ 請輸入 0 到 24 之間的整數：")]
                ))
                return
            wizard["step"] = "max_count"
            # 顯示 18 或 24 的選擇按鈕
            quick_reply = QuickReply(items=[
                QuickReplyItem(action=PostbackAction(
                    label="18 個任務",
                    data=f"wizard_max|18",
                    display_text="18 個任務"
                )),
                QuickReplyItem(action=PostbackAction(
                    label="24 個任務",
                    data=f"wizard_max|24",
                    display_text="24 個任務"
                )),
            ])
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=f"✅ 已完成任務數：{wdata['count']} 個\n\n本期預計承接幾個任務？",
                    quick_reply=quick_reply
                )]
            ))
            return

    if text in ("/reset", "重置", "/重置"):
        state[KEY_SCORES] = []
        state[KEY_WIZARD] = None
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="✅ 已清除本期累計紀錄，可以重新開始輸入。", quick_reply=_main_quick_reply())]
        ))
        return

    if text in ("/help", "/start", "說明", "help"):
        from formatter import format_help
        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=format_help(), quick_reply=_main_quick_reply())]
        ))
        return

    # 單筆數字模式
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
        id_ = state.get(KEY_ID) or user_id

        detail = " + ".join(str(s) for s in scores)
        data = compute_result(id_, total, count)
        summary = format_summary(data)
        quick_reply = _build_title_quick_reply(data, total, count)
        msg_text = f"➕ 已記錄 {score_input} 分\n📝 本期累計：{detail} = {total} 分（共 {count} 次）\n\n{summary}"

        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=msg_text, quick_reply=quick_reply)]
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
            await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60", quick_reply=_main_quick_reply())]
            ))
            return

        state[KEY_ID] = id_
        # 詢問 18 或 24
        quick_reply = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(
                label="18 個任務",
                data=f"full_max|{id_}|{score}|{count}|18",
                display_text="18 個任務"
            )),
            QuickReplyItem(action=PostbackAction(
                label="24 個任務",
                data=f"full_max|{id_}|{score}|{count}|24",
                display_text="24 個任務"
            )),
        ])        await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(
                text=f"👤 {id_}  📊 {score} 分  已完成 {count} 次\n\n本期預計承接幾個任務？",
                quick_reply=quick_reply
            )]
        ))
        return

    await asyncio.to_thread(api.reply_message, ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="❌ 格式錯誤！\n完整格式：{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n單筆格式：直接輸入分數，例如：60\n輸入「說明」查看完整說明", quick_reply=_main_quick_reply())]
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
