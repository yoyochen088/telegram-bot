"""
formatter.py — 回覆格式化（純函式）

將 compute_result 的結構化結果轉換為繁體中文回覆字串。
"""

MAX_RECOMMENDATIONS = 5


def _format_combo(combo: tuple) -> str:
    """將單一推薦組合格式化為可讀字串。"""
    sa, ca, sb, cb = combo
    if cb == 0 or sb == 0:
        total = ca * sa
        return f"接 {ca} 個 {sa}分 任務，共 {total} 分"
    if ca == 0 or sa == 0:
        total = cb * sb
        return f"接 {cb} 個 {sb}分 任務，共 {total} 分"
    total = ca * sa + cb * sb
    return f"接 {cb} 個 {sb}分 + {ca} 個 {sa}分 任務，共 {total} 分"


def format_summary(result: dict) -> str:
    """回覆基本摘要：ID、總分、稱號、剩餘任務、各稱號差距。"""
    id_ = result["id"]
    score = result["score"]
    title = result["title"]
    remaining_slots = result["remaining_slots"]
    higher_titles = result["higher_titles"]

    lines = [
        f"👤 ID：{id_}",
        f"📊 目前累計總分：{score} 分（{title}）",
    ]

    if title == "王者花匠":
        lines.append(f"🏆 恭喜！{id_} 已達最高稱號「王者花匠」！")
        return "\n".join(lines)

    if remaining_slots == 0:
        lines.append("⚠️ 本期任務名額已用盡（已完成 24 個任務）")
    else:
        lines.append(f"📋 本期剩餘任務：{remaining_slots} 個")

    if higher_titles:
        lines.append("")
        lines.append("🎯 距離各稱號差距：")
        for threshold, name, gap in reversed(higher_titles):
            lines.append(f"  ▸ {name}（{threshold}分）：還差 {gap} 分")

    return "\n".join(lines)


def format_recommendation(result: dict, target: str, combos: list | None, bonus: int = 0) -> str:
    """回覆指定目標稱號的推薦組合。"""
    id_ = result["id"]
    score = result["score"]
    remaining_slots = result["remaining_slots"]

    gap = next(
        (g for _, name, g in result["higher_titles"] if name == target), None
    )

    bonus_parts = []
    if bonus & 1:  bonus_parts.append("56+1")
    if bonus & 2:  bonus_parts.append("56+2")
    if bonus & 4:  bonus_parts.append("60+1")
    if bonus & 8:  bonus_parts.append("60+2")
    bonus_tag = f"（進階加成：{', '.join(bonus_parts)}）" if bonus_parts else ""

    lines = [
        f"👤 ID：{id_}  📊 總分：{score} 分  📋 剩餘任務：{remaining_slots} 個",
        "",
        f"🎯 目標：{target}（還差 {gap} 分）{bonus_tag}",
        "",
        "💡 推薦接法：",
    ]

    if combos is None:
        lines.append("  ⚠️ 剩餘任務不足，本期無法達成此稱號")
    else:
        for combo in combos[:MAX_RECOMMENDATIONS]:
            lines.append(f"  • {_format_combo(combo)}")

    return "\n".join(lines)


# 保留舊介面相容性
def format_reply(result: dict) -> str:
    return format_summary(result)


def format_help() -> str:
    """回傳 /start 與 /help 的使用說明字串。"""
    return (
        "🌸 公會競賽分數計算 Bot\n"
        "\n"
        "📌 功能說明：\n"
        "  輸入任務分數，Bot 會累計本期總分並推薦最省接法。\n"
        "\n"
        "📝 輸入方式：\n"
        "  【單筆模式】直接輸入分數，例如：60\n"
        "    → Bot 自動累加本期分數，每次輸入都會更新\n"
        "  【完整模式】{ID} {累計總分} {次數}，例如：蜜桃香檳 528 4\n"
        "    → 直接用指定數值計算\n"
        "\n"
        "🔄 指令：\n"
        "  /reset — 清除本期累計紀錄，重新開始\n"
        "  /help  — 顯示此說明\n"
        "\n"
        "🎮 任務說明：\n"
        "  基本任務分數：14、21、23、25、28、30 分\n"
        "  每個任務可選擇是否加倍（×2）：28、42、46、50、56、60 分\n"
        "  每期每人最多承接 24 個任務\n"
        "\n"
        "🏅 稱號級距：\n"
        "  0–499 分：無稱號\n"
        "  500–699 分：青銅花匠\n"
        "  700–999 分：白銀花匠\n"
        "  1000–1299 分：黃金花匠\n"
        "  1300–1399 分：大師花匠\n"
        "  1400 分以上：王者花匠"
    )
