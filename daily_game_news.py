import os
import requests
import feedparser
from datetime import datetime

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]

FEED_URLS = os.environ.get("FEED_URLS", "").split(",")


# -------------------------
# 1. 抓取信息
# -------------------------
def fetch_news():
    items = []

    for url in FEED_URLS:
        feed = feedparser.parse(url)

        for entry in feed.entries[:5]:
            title = entry.get("title", "")
            link = entry.get("link", "")

            items.append({
                "title": title,
                "link": link
            })

    return items


# -------------------------
# 2. AI风格分类（规则版）
# -------------------------
def classify(items):
    out = {
        "出海手游": [],
        "行业动态": [],
        "其他": []
    }

    keywords_outbound = ["mobile", "game", "app", "revenue", "download", "sensor", "pocket", "market"]

    for i in items:
        text = i["title"].lower()

        if any(k in text for k in keywords_outbound):
            out["出海手游"].append(i)
        else:
            out["行业动态"].append(i)

    return out


# -------------------------
# 3. 生成日报
# -------------------------
def build_report(data):
    today = datetime.now().strftime("%Y-%m-%d")

    msg = f"🎮 游戏日报2.0 | 出海手游观察\n{today}\n\n"

    for section, items in data.items():
        msg += f"📊 {section}\n"

        if not items:
            msg += "- 暂无数据\n\n"
            continue

        for i in items[:5]:
            msg += f"- {i['title']}\n{i['link']}\n"

        msg += "\n"

    msg += "💡 今日总结：出海手游市场持续结构性调整（自动生成简版）"

    return msg


# -------------------------
# 4. 发飞书
# -------------------------
def send(text):
    payload = {
        "msg_type": "text",
        "content": {"text": text}
    }

    r = requests.post(FEISHU_WEBHOOK, json=payload)

    print(r.status_code)
    print(r.text)


# -------------------------
# 主流程
# -------------------------
def main():
    news = fetch_news()
    grouped = classify(news)
    report = build_report(grouped)
    send(report)


if __name__ == "__main__":
    main()
