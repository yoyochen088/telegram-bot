"""
setup_rich_menu.py — 建立 LINE Rich Menu（常駐底部按鈕）

執行一次即可：
  python setup_rich_menu.py

需要環境變數：
  LINE_CHANNEL_ACCESS_TOKEN
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
if not TOKEN:
    raise SystemExit("❌ 未設定 LINE_CHANNEL_ACCESS_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# 1. 建立 Rich Menu
rich_menu = {
    "size": {"width": 2500, "height": 843},
    "selected": True,
    "name": "主選單",
    "chatBarText": "選單",
    "areas": [
        {
            "bounds": {"x": 0, "y": 0, "width": 1250, "height": 843},
            "action": {"type": "postback", "data": "menu|help", "displayText": "說明"}
        },
        {
            "bounds": {"x": 1250, "y": 0, "width": 1250, "height": 843},
            "action": {"type": "postback", "data": "menu|calc", "displayText": "計算分數"}
        }
    ]
}

resp = requests.post(
    "https://api.line.me/v2/bot/richmenu",
    headers=HEADERS,
    json=rich_menu
)
resp.raise_for_status()
rich_menu_id = resp.json()["richMenuId"]
print(f"✅ Rich Menu 建立成功：{rich_menu_id}")

# 2. 上傳背景圖（用純色文字圖）
# 建立簡單的 PNG 圖片（2500x843，左右各一個按鈕）
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (2500, 843), color=(45, 45, 45))
    draw = ImageDraw.Draw(img)
    # 分隔線
    draw.line([(1250, 0), (1250, 843)], fill=(100, 100, 100), width=4)
    # 文字
    draw.text((625, 380), "📖 說明", fill="white", anchor="mm", font=ImageFont.load_default(size=80))
    draw.text((1875, 380), "🧮 計算分數", fill="white", anchor="mm", font=ImageFont.load_default(size=80))
    img.save("/tmp/richmenu.png")

    with open("/tmp/richmenu.png", "rb") as f:
        img_resp = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "image/png"},
            data=f.read()
        )
    img_resp.raise_for_status()
    print("✅ 背景圖上傳成功")
except ImportError:
    print("⚠️ Pillow 未安裝，跳過背景圖上傳（Rich Menu 會顯示空白背景）")
except Exception as e:
    print(f"⚠️ 背景圖上傳失敗：{e}（Rich Menu 仍可使用）")

# 3. 設為預設 Rich Menu
default_resp = requests.post(
    f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}",
    headers=HEADERS
)
default_resp.raise_for_status()
print("✅ 已設為所有使用者的預設 Rich Menu")
print(f"\n完成！Rich Menu ID: {rich_menu_id}")
