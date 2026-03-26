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


def calc_remaining_slots(count: int) -> int:
    """回傳剩餘名額 = 24 - count。"""
    return 24 - count


def recommend_combinations(
    current_score: int,
    target_score: int,
    remaining_slots: int,
) -> list[tuple[int, int, int, int, bool]] | None:
    """
    針對單一目標稱號，計算混合任務推薦組合。
    回傳 list of (score_a, count_a, score_b, count_b, is_doubled)，
    依總次數升序排列，或 None 表示剩餘名額不足以達成。
    """
    need = target_score - current_score
    if need <= 0:
        return []

    NORMAL = [30, 28, 25]   # 不加倍，由高到低
    DOUBLED = [60, 56, 50]  # 加倍，由高到低

    seen: set[tuple[int, int, int, int, bool]] = set()
    results: list[tuple[int, int, int, int, bool]] = []

    def _enumerate(scores: list[int], is_doubled: bool) -> None:
        # 枚舉所有 (score_a, count_a, score_b, count_b) 組合
        # score_a >= score_b，count_a 從 0 開始
        for i, sa in enumerate(scores):
            for sb in scores[i:]:  # sb <= sa
                max_a = min(remaining_slots, ceil(need / sa))
                for ca in range(0, max_a + 1):
                    remain = need - ca * sa
                    if remain <= 0:
                        # 只需要 sa 就夠了
                        combo = (0, 0, sa, ca, is_doubled)
                        if combo not in seen:
                            seen.add(combo)
                            results.append(combo)
                        break
                    cb = ceil(remain / sb)
                    if ca + cb <= remaining_slots:
                        combo = (sb, cb, sa, ca, is_doubled)
                        if combo not in seen:
                            seen.add(combo)
                            results.append(combo)

    _enumerate(NORMAL, False)
    _enumerate(DOUBLED, True)

    if not results:
        return None

    # 依總次數升序，次數相同則依總分升序（越接近 need 越好）
    results.sort(key=lambda c: (c[1] + c[3], c[0] * c[1] + c[2] * c[3]))
    return results


def compute_result(id_: str, score: int, count: int) -> dict:
    """
    整合所有計算，回傳結構化結果 dict：
    {
        "id": str,
        "score": int,
        "title": str,
        "remaining_slots": int,
        "higher_titles": list[tuple[int, str, int]],
        "recommendations": dict[str, list | None],
    }
    """
    title = get_title(score)
    higher_titles = get_higher_titles(score)
    remaining_slots = calc_remaining_slots(count)

    if remaining_slots > 0:
        recommendations = {
            name: recommend_combinations(score, threshold, remaining_slots)
            for threshold, name, _ in higher_titles
        }
    else:
        recommendations = {}

    return {
        "id": id_,
        "score": score,
        "title": title,
        "remaining_slots": remaining_slots,
        "higher_titles": higher_titles,
        "recommendations": recommendations,
    }
