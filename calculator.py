"""
calculator.py — 核心計算邏輯（純函式，無副作用）

負責稱號判斷、差距計算、剩餘名額計算與推薦任務組合。
"""

from math import ceil

TITLE_THRESHOLDS: list[tuple[int, str]] = [
    (0,    "無稱號"),
    (500,  "青銅花匠"),
    (700,  "白銀花匠"),
    (1000, "黃金花匠"),
    (1300, "大師花匠"),
    (1400, "王者花匠"),
]

TASK_SCORES: list[int] = [25, 28, 30, 50, 56, 60]
LOW_SCORES:  list[int] = [25, 28, 30]
HIGH_SCORES: list[int] = [50, 56, 60]


def get_title(score: int) -> str:
    """依累計總分回傳目前稱號。"""
    title = TITLE_THRESHOLDS[0][1]
    for threshold, name in TITLE_THRESHOLDS:
        if score >= threshold:
            title = name
    return title


def get_higher_titles(score: int) -> list[tuple[int, str, int]]:
    """回傳所有比目前稱號更高的 (門檻分數, 稱號, 差距) 清單（升序）。"""
    current_threshold = 0
    for threshold, _ in TITLE_THRESHOLDS:
        if score >= threshold:
            current_threshold = threshold
    return [
        (threshold, name, threshold - score)
        for threshold, name in TITLE_THRESHOLDS
        if threshold > current_threshold
    ]


def calc_remaining_slots(count: int, max_slots: int = 24) -> int:
    """回傳剩餘名額 = max_slots - count。"""
    return max(0, max_slots - count)


def recommend_combinations(
    current_score: int,
    target_score: int,
    remaining_slots: int,
    bonus: int = 0,
    max_score: int = 60,
) -> list[tuple[int, int, int, int]] | None:
    """
    針對單一目標稱號，計算混合任務推薦組合。
    目標：恰好用完 remaining_slots 個任務，總分 >= need。
    排序：最高分任務數最少優先（次要：總分最低）。

    bonus 為 4-bit 旗標：
      bit0 = 56+1（57分）, bit1 = 56+2（58分）
      bit2 = 60+1（61分）, bit3 = 60+2（62分）
    max_score：玩家能接的最高加倍任務分數（28/46/50/56/60），
      超過此分數的任務不納入計算。

    回傳 list of (score_a, count_a, score_b, count_b)，
    或 None 表示剩餘名額不足以達成。
    """
    need = target_score - current_score
    if need <= 0:
        return []

    # 一般任務（不加倍）
    NORMAL = [14, 21, 23, 25, 28, 30]

    # 加倍任務，依 bonus 旗標與 max_score 決定實際可用分數
    doubled_base = [28, 42, 46, 50]
    if max_score >= 56:
        if bonus & 1:       doubled_base.append(57)
        elif bonus & 2:     doubled_base.append(58)
        else:               doubled_base.append(56)
    if max_score >= 60:
        if bonus & 4:       doubled_base.append(61)
        elif bonus & 8:     doubled_base.append(62)
        else:               doubled_base.append(60)
    DOUBLED = sorted(s for s in set(doubled_base) if s <= max_score + 2)  # +2 容許進階加成

    ALL_SCORES = sorted(set(NORMAL + DOUBLED))

    seen: set[tuple[int, int, int, int]] = set()
    results: list[tuple[int, int, int, int]] = []

    # 枚舉所有兩種分數的組合 (sa <= sb)，恰好用完 remaining_slots 個任務
    for i, sa in enumerate(ALL_SCORES):
        for sb in ALL_SCORES[i:]:
            for cb in range(0, remaining_slots + 1):
                ca = remaining_slots - cb
                total = ca * sa + cb * sb
                if total >= need:
                    if sa == sb:
                        combo = (sa, ca + cb, 0, 0)
                    elif ca == 0:
                        combo = (sb, cb, 0, 0)
                    elif cb == 0:
                        combo = (sa, ca, 0, 0)
                    else:
                        combo = (sa, ca, sb, cb)
                    if combo not in seen:
                        seen.add(combo)
                        results.append(combo)

    if not results:
        return None

    # 排序：最高分任務數最少優先，次要總分最低
    # top_score = 本次計算中所有組合裡出現的最高分數
    all_scores_used = set()
    for sa, ca, sb, cb in results:
        if ca > 0: all_scores_used.add(sa)
        if cb > 0: all_scores_used.add(sb)
    top_score = max(all_scores_used) if all_scores_used else 0

    def _sort_key(c: tuple) -> tuple:
        sa, ca, sb, cb = c
        count_top = (ca if sa == top_score else 0) + (cb if sb == top_score else 0)
        total = sa * ca + sb * cb
        return (count_top, total)

    results.sort(key=_sort_key)
    return results


def compute_result(id_: str, score: int, count: int, max_slots: int = 24, max_score: int = 60) -> dict:
    """
    整合所有計算，回傳結構化結果 dict：
    {
        "id": str,
        "score": int,
        "title": str,
        "max_slots": int,
        "max_score": int,
        "remaining_slots": int,
        "higher_titles": list[tuple[int, str, int]],
        "recommendations": dict[str, list | None],
    }
    """
    title = get_title(score)
    higher_titles = get_higher_titles(score)
    remaining_slots = calc_remaining_slots(count, max_slots)

    if remaining_slots > 0:
        recommendations = {
            name: recommend_combinations(score, threshold, remaining_slots, bonus=0, max_score=max_score)
            for threshold, name, _ in higher_titles
        }
    else:
        recommendations = {}

    return {
        "id": id_,
        "score": score,
        "title": title,
        "max_slots": max_slots,
        "max_score": max_score,
        "remaining_slots": remaining_slots,
        "higher_titles": higher_titles,
        "recommendations": recommendations,
    }
