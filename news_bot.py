import os
import re
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

FEEDS = [
    "https://www.animenewsnetwork.com/rss.xml",
    "https://www.otakunews.com/Rss",
    "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
]

# Words that strongly suggest useful anime news
GOOD_WORDS = [
    "announces", "announcement", "announced",
    "officially", "confirmed", "confirm",
    "new season", "season 2", "season 3", "season 4",
    "renewed", "renewal",
    "premiere", "release date", "release",
    "air date", "broadcast",
    "trailer", "teaser", "pv",
    "production", "production confirmed",
    "adaptation announced",
    "anime adaptation",
    "streaming",
    "debut",
    "episode"
]

# Words/articles we don't want
BAD_WORDS = [
    "review",
    "reviews",
    "interview",
    "podcast",
    "fashion",
    "ranking",
    "rankings",
    "list",
    "top 10",
    "best anime",
    "box office",
    "celebrity",
    "gossip",
    "opinion",
    "reaction",
    "fan theory",
    "theory",
    "rumor",
    "rumour",
    "rumors",
    "rumours",
    "merchandise",
    "figure",
    "collectible",
    "game",
    "video game"
]

DATA_FILE = Path("posted.json")
MAX_POSTS_PER_RUN = 3


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
    except Exception as e:
        print(f"XML error: {e}")
        return []

    results = []

    # RSS
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

    # Atom
    if not results:
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            summary = entry.findtext("atom:summary", "", ns).strip()

            link = ""

            link_element = entry.find(
                "atom:link[@rel='alternate']", ns
            )

            if link_element is None:
                link_element = entry.find("atom:link", ns)

            if link_element is not None:
                link = link_element.attrib.get("href", "").strip()

            if title and link:
                results.append({
                    "title": title,
                    "link": link,
                    "description": summary
                })

    return results


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def relevant(item):
    title = clean(item["title"]).lower()
    description = clean(item["description"]).lower()

    # We judge the title more heavily than the description.
    text = title + " " + description

    # Reject obvious unwanted article types.
    if any(word in title for word in BAD_WORDS):
        return False

    # Must contain an anime-related signal.
    anime_signals = [
        "anime",
        "manga",
        "episode",
        "season",
        "studio",
        "crunchyroll",
        "animation",
        "japanese anime"
    ]

    if not any(word in text for word in anime_signals):
        return False

    # Must also contain a useful-news signal.
    if not any(word in text for word in GOOD_WORDS):
        return False

    return True


def load_posted():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text())
            return set(data)
        except Exception:
            pass

    return set()


def save_posted(posted):
    # Keep the file from growing forever.
    recent = list(posted)[-1000:]
    DATA_FILE.write_text(json.dumps(recent, indent=2))


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

    try:
        urllib.request.urlopen(req, timeout=20)
        time.sleep(3)

    except urllib.error.HTTPError as e:

        if e.code == 429:
            retry_after = 10

            try:
                data = json.loads(e.read().decode())
                retry_after = data.get(
                    "parameters", {}
                ).get("retry_after", 10)

            except Exception:
                pass

            print(
                f"Telegram rate limit. "
                f"Waiting {retry_after} seconds..."
            )

            time.sleep(retry_after)

            urllib.request.urlopen(req, timeout=20)
            time.sleep(3)

        else:
            raise


def main():
    posted = load_posted()
    candidates = []

    for feed in FEEDS:
        items = parse_feed(get_feed(feed))

        for item in items:
            if relevant(item):
                candidates.append(item)

    # Remove duplicates inside the same run.
    unique = {}
    for item in candidates:
        unique[item["link"]] = item

    candidates = list(unique.values())

    posted_this_run = 0

    for item in candidates:

        if posted_this_run >= MAX_POSTS_PER_RUN:
            break

        if item["link"] in posted:
            continue

        message = (
            "🍿 ANIME NEWS\n\n"
            f"{item['title']}\n\n"
            f"🔗 Source: {item['link']}"
        )

        try:
            send_telegram(message)

            posted.add(item["link"])
            posted_this_run += 1

            print(f"Posted: {item['title']}")

        except Exception as e:
            print(f"Telegram error: {e}")

    save_posted(posted)

    print(
        f"Finished. Posted {posted_this_run} "
        f"new article(s)."
    )


if __name__ == "__main__":
    main()
