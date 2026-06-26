import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================
# 环境变量
# =========================

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"].strip()
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "").strip()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()

MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "12"))


def env_list(name):
    raw = os.environ.get(name, "")
    raw = raw.replace("\n", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


FEED_URLS = env_list("FEED_URLS")
MANUAL_URLS = env_list("MANUAL_URLS")
USER_KEYWORDS = env_list("KEYWORDS")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


# =========================
# 关键词体系：出海手游 + Sensor Tower风格
# =========================

BASE_KEYWORDS = [
    # 中文
    "出海", "手游", "海外", "全球", "发行", "买量", "素材", "投放",
    "下载", "收入", "营收", "流水", "榜单", "畅销榜", "下载榜",
    "Sensor Tower", "sensortower", "点点数据", "AppMagic", "data.ai",
    "App Store", "Google Play", "iOS", "Android",
    "美国", "日本", "韩国", "东南亚", "港澳台", "欧美", "中东", "拉美",
    "SLG", "RPG", "卡牌", "休闲", "超休闲", "混合休闲", "放置", "二游",
    "腾讯", "网易", "米哈游", "莉莉丝", "沐瞳", "三七", "Habby", "FunPlus",
    "Scopely", "Supercell", "King", "Zynga",

    # 英文
    "mobile game", "mobile games", "gaming", "revenue", "downloads",
    "download", "grossing", "top grossing", "top games", "publisher",
    "user acquisition", "UA", "CPI", "ROAS", "ad spend", "creative",
    "TikTok", "Meta", "Google Ads", "Apple Search Ads",
    "US", "Japan", "Korea", "SEA", "MENA", "LATAM",
]

FOCUS_KEYWORDS = list(dict.fromkeys(BASE_KEYWORDS + USER_KEYWORDS))


SECTION_RULES = {
    "📈 Sensor Tower式数据线索": [
        "sensor tower", "sensortower", "revenue", "downloads", "download",
        "grossing", "top grossing", "top games", "榜单", "下载", "收入",
        "流水", "畅销榜", "下载榜", "估算", "市场趋势", "App Store", "Google Play",
        "data.ai", "AppMagic", "点点数据"
    ],
    "🌏 出海手游重点": [
        "出海", "海外", "全球", "mobile game", "mobile games", "手游",
        "publisher", "发行", "launch", "soft launch", "pre-registration",
        "iOS", "Android", "Google Play", "App Store"
    ],
    "📣 买量与广告观察": [
        "买量", "投放", "素材", "广告", "ad spend", "user acquisition",
        "UA", "CPI", "ROAS", "creative", "TikTok", "Meta", "Google Ads",
        "Apple Search Ads", "impressions"
    ],
    "🧩 产品与品类变化": [
        "SLG", "RPG", "卡牌", "休闲", "超休闲", "混合休闲", "放置",
        "二游", "gacha", "casual", "hybrid casual", "strategy", "simulation"
    ],
}


# =========================
# 工具函数
# =========================

def clean_text(text, limit=700):
    if not text:
        return ""
    text = BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def source_name(url):
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return host or "unknown"
    except Exception:
        return "unknown"


def score_item(item):
    text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')}".lower()
    score = 0

    for kw in FOCUS_KEYWORDS:
        kw_l = kw.lower()
        if kw_l and kw_l in text:
            score += 2

    # 加权：越接近出海手游和数据分析，分越高
    boost_terms = [
        "sensor tower", "sensortower", "revenue", "downloads", "top grossing",
        "出海", "手游", "买量", "收入", "下载", "榜单", "google play", "app store"
    ]

    for term in boost_terms:
        if term in text:
            score += 5

    return score


def classify_item(item):
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    best_section = "📰 其他值得关注"
    best_score = 0

    for section, terms in SECTION_RULES.items():
        s = 0
        for term in terms:
            if term.lower() in text:
                s += 1
        if s > best_score:
            best_score = s
            best_section = section

    return best_section


# =========================
# RSS 抓取
# =========================

def fetch_rss_items():
    items = []

    for feed_url in FEED_URLS:
        try:
            print(f"Fetching RSS: {feed_url}")

            response = requests.get(feed_url, headers=HEADERS, timeout=20)
            response.raise_for_status()

            feed = feedparser.parse(response.content)
            feed_title = feed.feed.get("title", source_name(feed_url))

            for entry in feed.entries[:20]:
                title = clean_text(entry.get("title", ""), 200)
                link = entry.get("link", "").strip()
                summary = clean_text(
                    entry.get("summary", "") or entry.get("description", ""),
                    600
                )

                if not title or not link:
                    continue

                items.append({
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "source": feed_title,
                    "kind": "rss",
                })

        except Exception as e:
            print(f"RSS fetch failed: {feed_url} | {e}")

    return items


# =========================
# 手动文章抓取：适合微信公众号 / Sensor Tower报告页
# =========================

def get_meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            return tag.get("content").strip()

        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag.get("content").strip()

    return ""


def fetch_manual_article(url):
    try:
        print(f"Fetching manual URL: {url}")

        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        title = (
            get_meta(soup, "og:title", "twitter:title")
            or (soup.title.get_text(" ", strip=True) if soup.title else "")
            or url
        )

        description = get_meta(
            soup,
            "description",
            "og:description",
            "twitter:description"
        )

        # 微信公众号正文常见容器
        content_node = soup.select_one("#js_content")
        if content_node:
            paragraphs = content_node.get_text(" ", strip=True)
        else:
            paragraphs = " ".join(
                p.get_text(" ", strip=True)
                for p in soup.find_all("p")[:8]
            )

        summary = clean_text(description or paragraphs, 1000)

        return {
            "title": clean_text(title, 200),
            "url": url,
            "summary": summary,
            "source": source_name(url),
            "kind": "manual",
        }

    except Exception as e:
        print(f"Manual URL fetch failed: {url} | {e}")
        return None


def fetch_manual_items():
    items = []

    for url in MANUAL_URLS:
        item = fetch_manual_article(url)
        if item:
            items.append(item)

    return items


# =========================
# 去重、过滤、排序
# =========================

def prepare_items(items):
    seen = set()
    prepared = []

    for item in items:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue

        seen.add(key)

        item["score"] = score_item(item)
        item["section"] = classify_item(item)
        prepared.append(item)

    # 优先保留与出海手游 / Sensor Tower / 数据分析相关的内容
    focused = [x for x in prepared if x["score"] > 0]

    if not focused:
        focused = prepared

    focused.sort(key=lambda x: x.get("score", 0), reverse=True)

    return focused[:MAX_ITEMS]


# =========================
# AI 分析：Sensor Tower风格日报
# =========================

def build_ai_prompt(items):
    source_lines = []

    for i, item in enumerate(items, 1):
        source_lines.append(
            f"{i}. 来源：{item['source']}\n"
            f"标题：{item['title']}\n"
            f"摘要：{item.get('summary', '')}\n"
            f"链接：{item['url']}\n"
        )

    sources_text = "\n".join(source_lines)

    return f"""
你是一名游戏行业分析师，专注“出海手游、全球移动游戏市场、Sensor Tower式数据分析、买量和收入趋势”。

请基于下面的资料，生成一份适合飞书推送的中文日报。

要求：
1. 标题使用“📊 游戏日报 3.0｜出海手游情报”。
2. 内容重点放在：
   - 出海手游
   - Sensor Tower式下载/收入/榜单线索
   - App Store / Google Play
   - 美国、日本、韩国、东南亚、欧美市场
   - 买量、广告素材、CPI、ROAS、TikTok、Meta、Google Ads
   - 手游品类：SLG、RPG、卡牌、休闲、二游、混合休闲
3. 不要编造具体下载量、收入、排名或百分比。
4. 如果资料没有具体数字，就写“公开资料未披露具体数值”。
5. 输出结构：
   - 🎯 今日一句话结论
   - 📈 数据/榜单信号
   - 🌏 出海手游重点
   - 📣 买量与广告观察
   - 🧠 今日判断
   - 🔗 来源
6. 风格要像行业分析日报，不要像普通新闻列表。
7. 总长度控制在 3000 字以内。

资料：
{sources_text}
"""


def build_ai_report(items):
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set, using rule-based report.")
        return None

    if OpenAI is None:
        print("OpenAI SDK not available, using rule-based report.")
        return None

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = build_ai_prompt(items)

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
        )

        text = getattr(response, "output_text", "").strip()

        if text:
            return text

        print("OpenAI returned empty output, using rule-based report.")
        return None

    except Exception as e:
        print(f"OpenAI report failed, using rule-based report: {e}")
        return None


# =========================
# 规则版日报：没有 OpenAI Key 时也能跑
# =========================

def build_rule_report(items):
    today = datetime.now().strftime("%Y-%m-%d")

    if not items:
        return (
            f"📊 游戏日报 3.0｜出海手游情报\n"
            f"{today}\n\n"
            f"今天没有抓到符合条件的出海手游 / Sensor Tower相关资讯。\n"
            f"建议检查 FEED_URLS / MANUAL_URLS / KEYWORDS。"
        )

    sections = {
        "📈 Sensor Tower式数据线索": [],
        "🌏 出海手游重点": [],
        "📣 买量与广告观察": [],
        "🧩 产品与品类变化": [],
        "📰 其他值得关注": [],
    }

    for item in items:
        sections.setdefault(item["section"], []).append(item)

    msg = f"📊 游戏日报 3.0｜出海手游情报\n{today}\n\n"

    top = items[0]
    msg += "🎯 今日一句话结论\n"
    msg += f"今日最值得关注的是：{top['title']}\n\n"

    for section, section_items in sections.items():
        if not section_items:
            continue

        msg += f"{section}\n"

        for item in section_items[:4]:
            msg += f"- {item['title']}\n"
            if item.get("summary"):
                msg += f"  摘要：{item['summary'][:160]}\n"
            msg += f"  来源：{item['source']}\n"
            msg += f"  链接：{item['url']}\n"

        msg += "\n"

    msg += "🧠 今日判断\n"
    msg += "- 当前版本为规则分析版：会优先筛选出海手游、收入下载、榜单、买量和全球市场相关内容。\n"
    msg += "- 接入 OPENAI_API_KEY 后，会升级为 AI 行业分析日报。\n"
    msg += "- 若接入 Sensor Tower Connect API，可进一步加入真实下载、收入、榜单和国家市场数据。\n"

    return msg


# =========================
# 飞书签名 + 推送
# =========================

def make_feishu_sign(timestamp, secret):
    string_to_sign = f"{timestamp}\n{secret}"

    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        b"",
        digestmod=hashlib.sha256,
    ).digest()

    return base64.b64encode(hmac_code).decode("utf-8")


def trim_for_feishu(text, limit=3500):
    if len(text) <= limit:
        return text

    return text[:limit] + "\n\n……内容过长，已自动截断。"


def send_to_feishu(text):
    payload = {
        "msg_type": "text",
        "content": {
            "text": trim_for_feishu(text)
        }
    }

    if FEISHU_SECRET:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = make_feishu_sign(timestamp, FEISHU_SECRET)

    response = requests.post(FEISHU_WEBHOOK, json=payload, timeout=20)

    print("Feishu status:", response.status_code)
    print("Feishu response:", response.text)

    response.raise_for_status()

    try:
        data = response.json()
        code = data.get("code")

        if code not in (0, None):
            raise RuntimeError(f"Feishu rejected message: {data}")

    except ValueError:
        pass


# =========================
# 主流程
# =========================

def main():
    print("START GAME DAILY 3.0")

    rss_items = fetch_rss_items()
    manual_items = fetch_manual_items()

    print("RSS ITEMS:", len(rss_items))
    print("MANUAL ITEMS:", len(manual_items))

    items = prepare_items(rss_items + manual_items)

    print("FOCUS ITEMS:", len(items))

    ai_report = build_ai_report(items)

    if ai_report:
        report = ai_report
        print("REPORT MODE: AI")
    else:
        report = build_rule_report(items)
        print("REPORT MODE: RULE")

    send_to_feishu(report)

    print("DONE")


if __name__ == "__main__":
    main()
