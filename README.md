# 🌸 公會競賽分數計算 Bot

支援 **Telegram** 與 **LINE** 雙平台的公會競賽分數計算機器人。輸入任務分數後，Bot 會自動累計本期總分、判斷目前稱號，並推薦最省接法以達成目標稱號。

---

## 功能特色

- 單筆累加模式：逐筆輸入分數，Bot 自動累計
- 完整格式模式：直接指定 ID、累計總分與次數
- 任務數選擇：每次計算前先選擇本週預計任務數（18 或 24 個）
- 稱號判斷：依任務數上限顯示目前稱號、剩餘可接任務數與距各稱號的差距
- 推薦組合：計算用完剩餘任務名額的最低成本接法
- 進階加成支援：可選擇 56+1、56+2、60+1、60+2 加成
- 雙平台：同時支援 Telegram（Inline Keyboard）與 LINE（Quick Reply）

---

## 專案結構

```
.
├── bot.py           # Telegram Bot 主程式（指令處理、Webhook 伺服器）
├── line_bot.py      # LINE Bot 處理邏輯（訊息與 Postback 事件）
├── calculator.py    # 核心計算邏輯（稱號判斷、推薦組合，純函式）
├── formatter.py     # 回覆格式化（將計算結果轉為繁體中文字串，純函式）
├── requirements.txt # Python 套件依賴
├── .env             # 環境變數（不納入版本控制）
└── tests/
    ├── conftest.py
    └── test_formatter.py
```

---

## 遊戲規則

### 競賽週期
- 每週二到週日為一個競賽週期
- 每個 ID 每期最多承接 **24 個任務**

### 任務分數
| 類型 | 分數 |
|------|------|
| 一般任務 | 14、21、23、25、28、30 分 |
| 加倍任務 | 28、42、46、50、56、60 分 |
| 加倍＋技能 | 57（56+1）、58（56+2）、61（60+1）、62（60+2）分 |

### 稱號級距
| 稱號 | 分數範圍 |
|------|----------|
| 無稱號 | 0–499 分 |
| 青銅花匠 | 500–699 分 |
| 白銀花匠 | 700–999 分 |
| 黃金花匠 | 1000–1299 分 |
| 大師花匠 | 1300–1399 分 |
| 王者花匠 | 1400 分以上 |

---

## 使用方式

### 輸入格式

**單筆模式**：直接輸入分數（正整數），Bot 自動累加本期總分
```
60
```

**完整模式**：`{ID} {累計總分} {次數}`
```
蜜桃香檳 528 4
```

### 指令

| 指令 | 說明 |
|------|------|
| `/start` 或 `/help` | 顯示使用說明 |
| `/reset` | 清除本期累計紀錄，重新開始 |

LINE 平台額外支援：`重置`、`說明`、`help` 文字觸發對應功能。

### 互動流程

1. 輸入分數後，Bot 詢問「本週預計要解的任務數」（18 或 24）
2. 選擇任務數後，Bot 顯示目前累計總分、稱號、本週任務上限與剩餘可接任務數
3. 點選目標稱號按鈕（Telegram：Inline Keyboard；LINE：Quick Reply）
4. 選擇是否有進階加成（可複選）
5. Bot 顯示推薦的最低成本任務組合

---

## 環境設定

### 必要環境變數

複製 `.env` 並填入對應金鑰：

```env
# Telegram
BOT_TOKEN=<your_telegram_bot_token>

# LINE
LINE_CHANNEL_ACCESS_TOKEN=<your_line_channel_access_token>
LINE_CHANNEL_SECRET=<your_line_channel_secret>

# Webhook（部署時使用，本地 polling 模式不需要）
WEBHOOK_URL=https://your-service.onrender.com
PORT=8443
```

### 安裝依賴

```bash
pip install -r requirements.txt
```

---

## 執行方式

### 本地開發（Polling 模式）

不設定 `WEBHOOK_URL`，直接執行：

```bash
python bot.py
```

### 部署（Webhook 模式）

設定 `WEBHOOK_URL` 後執行，Bot 會自動啟動 aiohttp HTTP 伺服器並註冊 Webhook：

- Telegram Webhook：`POST /webhook`
- LINE Webhook：`POST /line-webhook`
- Health Check：`GET /`

> 部署於 Render 免費版時，Bot 每 10 分鐘會自動 ping 自身以防止服務休眠。

---

## 模組說明

### `calculator.py`

核心計算邏輯，所有函式為純函式（無副作用）。

| 函式 | 說明 |
|------|------|
| `get_title(score)` | 依分數回傳目前稱號 |
| `get_higher_titles(score)` | 回傳所有更高稱號的門檻與差距 |
| `calc_remaining_slots(count, max_slots)` | 計算剩餘任務名額（max_slots - count，預設 24） |
| `recommend_combinations(current, target, slots, bonus)` | 計算最低成本任務推薦組合 |
| `compute_result(id_, score, count, max_slots)` | 整合所有計算，回傳結構化結果 dict |

`compute_result` 回傳格式：
```python
{
    "id": str,
    "score": int,
    "title": str,
    "max_slots": int,           # 本週任務上限（18 或 24）
    "remaining_slots": int,
    "higher_titles": list[tuple[int, str, int]],  # (門檻, 稱號, 差距)
    "recommendations": dict[str, list | None],
}
```

### `formatter.py`

回覆格式化，將計算結果轉為繁體中文字串，所有函式為純函式。

| 函式 | 說明 |
|------|------|
| `format_summary(result)` | 基本摘要（總分、稱號、任務上限、剩餘可接任務數、差距） |
| `format_recommendation(result, target, combos, bonus)` | 指定目標稱號的推薦組合 |
| `format_help(max_slots)` | 使用說明字串，傳入 max_slots 時額外顯示目前任務數設定 |

### `bot.py`

Telegram Bot 主程式。

- `handle_message`：處理文字訊息（單筆模式 / 完整模式），輸入後詢問任務數
- `handle_callback`：處理 Inline Keyboard 回調（任務數選擇、稱號選擇、進階加成切換、確認計算）
- `handle_reset` / `handle_help`：指令處理（help 顯示目前任務數設定）
- `main`：依環境變數決定 Polling 或 Webhook 模式啟動

Callback data 格式：
```
s_{score}_{count}_{max_slots}                        # 任務數選擇
t_{score}_{count}_{max_slots}_{title_idx}            # 稱號選擇
x_{score}_{count}_{max_slots}_{title_idx}_{bonus}    # 進階加成切換
b_{score}_{count}_{max_slots}_{title_idx}_{bonus}    # 確認計算
```

### `line_bot.py`

LINE Bot 處理邏輯，使用 `PostbackAction` 讓按鈕點擊不顯示內部指令文字。

- `handle_line_event`：處理 MessageEvent 與 PostbackEvent
- `_process_postback`：處理 Postback 核心邏輯（任務數選擇、稱號選擇、進階加成切換、確認計算）
- `create_line_handler`：建立 aiohttp LINE Webhook 處理器

Postback data 格式：
```
slots|{score}|{count}|{max_slots}
title|{target}|{score}|{count}|{max_slots}
bonus|{target}|{score}|{count}|{max_slots}|{bonus}
calc|{target}|{score}|{count}|{max_slots}|{bonus}
```

---

## 測試

```bash
pytest tests/
```

---

## 注意事項

- 累計紀錄不會自動清空，需手動執行 `/reset`
- LINE Bot 的使用者狀態儲存於記憶體（`_user_state`），服務重啟後會清空
- Render 免費版服務偶爾可能有短暫延遲
- `.env` 檔案包含敏感金鑰，請勿納入版本控制
