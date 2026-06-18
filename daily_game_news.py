import os
import time
import requests
import feedparser

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
FEED_URLS = os.environ.get("FEED_URLS", "").split(",")
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "10"))


def fetch_news():
    items = []

    for url in FEED_URLS:
        feed = feedparser.parse(url)

        for entry in feed.entries[:5]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "source": url
            })

    return items[:MAX_ITEMS]


def build_message(items):
    if not items:
        return "🎮 今日没有抓到游戏新闻"

    text = "🎮 游戏日报\n\n"

    for i, item in enumerate(items, 1):
        text += f"{i}. {item['title']}\n{item['link']}\n\n"

    return text


def send_to_feishu(text):
    payload = {
        "msg_type": "text",
        "content": {"text": text}
    }

    res = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)

    print("Feishu status:", res.status_code)
    print("Feishu response:", res.text)


def main():
    print("START BOT")

    news = fetch_news()
    print("NEWS COUNT:", len(news))

    msg = build_message(news)

    print("SENDING TO FEISHU")
    send_to_feishu(msg)

    print("DONE")


if __name__ == "__main__":
    main()
