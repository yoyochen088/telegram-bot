"""
formatter.py — 回覆格式化（純函式）

將 compute_result 的結構化結果轉換為繁體中文回覆字串。
"""

MAX_RECOMMENDATIONS = 5


def _format_combo(combo: tuple) -> str:
    """將單一推薦組合格式化為可讀字串。"""
    low_score, low_count, high_score, high_count, is_doubled = combo
    tag = "（加倍）" if is_doubled else "（不加倍）"
    if low_count == 0 or low_score == 0:
        total = high_count * high_score
        return f"接 {high_count} 個 {high_score}分 任務，共 {total} 分 {tag}"
    total = low_count * low_score + high_count * high_score
    return (
        f"接 {high_count} 個 {high_score}分 + {low_count} 個 {low_score}分 任務，"
        f"共 {total} 分 {tag}"
    )


def format_reply(result: dict) -> str:
    """將 compute_result 的結果格式化為繁體中文回覆字串。"""
    id_ = result["id"]
    score = result["score"]
    title = result["title"]
    remaining_slots = result["remaining_slots"]
    higher_titles = result["higher_titles"]
    recommendations = result["recommendations"]

    lines = []

    # 基本資訊
    lines.append(f"👤 ID：{id_}")
    lines.append(f"📊 目前累計總分：{score} 分（{title}）")

    # 王者花匠特殊情境
    if title == "王者花匠":
        lines.append(f"🏆 恭喜！{id_} 已達最高稱號「王者花匠」！")
        return "\n".join(lines)

    # 剩餘名額
    if remaining_slots == 0:
        lines.append("⚠️ 本週期任務名額已用盡（已完成 24 個任務）")
    else:
        lines.append(f"📋 本週期剩餘名額：{remaining_slots} 個")

    # 距離各稱號差距
    if higher_titles:
        lines.append("")
        lines.append("🎯 距離各稱號差距：")
        for threshold, name, gap in higher_titles:
            lines.append(f"  ▸ {name}（{threshold}分）：還差 {gap} 分")

    # 推薦組合（名額為 0 時不顯示）從最高稱號開始，略過拿不到的
    if remaining_slots > 0 and higher_titles:
        # 找出最高可達成的稱號（recommendations 不為 None）
        achievable = [
            (threshold, name, gap)
            for threshold, name, gap in reversed(higher_titles)
            if recommendations.get(name) is not None
        ]
        if achievable:
            lines.append("")
            lines.append("💡 任務推薦：")
            for threshold, name, gap in achievable:
                combos = recommendations.get(name)
                lines.append(f"【{name} — 還差 {gap} 分】")
                for combo in combos[:MAX_RECOMMENDATIONS]:
                    lines.append(f"  • {_format_combo(combo)}")

    return "\n".join(lines)


def format_help() -> str:
    """回傳 /start 與 /help 的使用說明字串。"""
    return (
        "🌸 公會競賽分數計算 Bot\n"
        "\n"
        "📌 功能說明：\n"
        "  輸入你的 ID、目前累計總分與已完成任務次數，\n"
        "  Bot 會顯示目前稱號、距離各更高稱號還差多少分，\n"
        "  並推薦剩餘名額可接的任務組合。\n"
        "\n"
        "📝 輸入格式：\n"
        "  {ID} {累計總分} {次數}\n"
        "\n"
        "📖 範例：\n"
        "  小貓 232 4\n"
        "  （表示 ID 為「小貓」，目前累計總分 232 分，已完成 4 次任務）\n"
        "\n"
        "🎮 任務說明：\n"
        "  基本任務分數：25、28、30 分\n"
        "  每個任務可選擇是否加倍（×2）：50、56、60 分\n"
        "  每週期每人最多承接 24 個任務\n"
        "  （不推薦 25 分以下的任務）\n"
        "\n"
        "🏅 稱號級距：\n"
        "  0–499 分：無稱號\n"
        "  500–699 分：青銅花匠\n"
        "  700–999 分：白銀花匠\n"
        "  1000–1299 分：黃金花匠\n"
        "  1300–1399 分：大師花匠\n"
        "  1400 分以上：王者花匠"
    )
