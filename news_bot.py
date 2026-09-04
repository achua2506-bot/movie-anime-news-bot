import os
import re
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

FEEDS = [
    "https://www.animenewsnetwork.com/rss.xml",
    "https://www.otakunews.com/Rss",
    "https://variety.com/feed/",
    "https://www.hollywoodreporter.com/feed/",
    "https://deadline.com/feed/",
]

KEYWORDS = [
    "anime", "manga", "episode", "season", "trailer",
    "movie", "film", "release", "premiere", "streaming",
    "cast", "casting", "renewed", "renewal", "cancelled",
    "canceled", "announcement", "teaser"
]

IGNORE = [
    "review", "interview", "podcast", "box office",
    "fashion", "award", "tv ratings", "celebrity"
]

DATA_FILE = Path("posted.json")


def get_feed(url):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MovieAnimeNewsBot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception as e:
        print(f"Feed error: {url} -> {e}")
        return b""


def parse_feed(data):
    if not data:
        return []

    try:
        root = ET.fromstring(data)
    except Exception:
        return []

    results = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        description = item.findtext("description", "").strip()

        if title and link:
            results.append({
                "title": title,
                "link": link,
                "description": description
            })

    return results


def clean(text):
    return re.sub("<[^>]+>", "", text or "").strip()


def relevant(item):
    text = (
        item["title"] + " " +
        clean(item["description"])
    ).lower()

    if any(word in text for word in IGNORE):
        return False

    return any(word in text for word in KEYWORDS)


def load_posted():
    if DATA_FILE.exists():
        try:
            return set(json.loads(DATA_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_posted(posted):
    DATA_FILE.write_text(json.dumps(list(posted)[-500:]))


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text,
        "disable_web_page_preview": False
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    urllib.request.urlopen(req, timeout=20)


def main():
    posted = load_posted()
    candidates = []

    for feed in FEEDS:
        for item in parse_feed(get_feed(feed)):
            if relevant(item):
                candidates.append(item)

    for item in candidates:
        if item["link"] in posted:
            continue

        message = (
            "🔥 MOVIE / ANIME UPDATE\n\n"
            f"{item['title']}\n\n"
            f"🔗 {item['link']}"
        )

        # First version: send only selected news.
        send_telegram(message)

        posted.add(item["link"])

    save_posted(posted)


if __name__ == "__main__":
    main()
