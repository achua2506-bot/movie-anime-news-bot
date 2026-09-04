import os
import json
import re
import html
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from bs4 import BeautifulSoup


# ==============================
# SETTINGS
# ==============================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["MOVIE_CHANNEL"]

MEMORY_FILE = "movie_posted.json"

MAX_POSTS_PER_RUN = 3
MAX_ARTICLE_AGE_HOURS = 24

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==============================
# NEWS FEEDS
# ==============================

FEEDS = [
    {
        "name": "Tamil OTT",
        "language": "Tamil",
        "url": "https://tamil.oneindia.com/rss/feeds/tamil-ott-fb.xml",
        "high_confidence": True,
    },
    {
        "name": "Tamil Cinema",
        "language": "Tamil",
        "url": "https://tamil.oneindia.com/rss/feeds/tamil-cinema-fb.xml",
        "high_confidence": False,
    },
    {
        "name": "Malayalam Cinema",
        "language": "Malayalam",
        "url": "https://malayalam.oneindia.com/rss/feeds/malayalam-cinema-fb.xml",
        "high_confidence": False,
    },
    {
        "name": "Malayalam Movie News",
        "language": "Malayalam",
        "url": "https://malayalam.oneindia.com/rss/feeds/malayalam-movie-news-fb.xml",
        "high_confidence": False,
    },
]


# ==============================
# KEYWORDS
# ==============================

OTT_KEYWORDS = [
    "ott",
    "streaming",
    "stream",
    "now streaming",
    "digital release",
    "digital premiere",
    "digital debut",
    "digital rights",
    "streaming rights",
    "ott rights",
    "ott release",
    "ott premiere",
    "watch online",
    "available on",
    "premieres on",
    "releasing on",
    "released on",
    "coming to",
    "platform",

    "netflix",
    "prime video",
    "amazon prime",
    "jiohotstar",
    "hotstar",
    "sun nxt",
    "sonyliv",
    "zee5",
    "aha",
    "aha tamil",
    "aha malayalam",
    "manorama max",
    "sunnxt",

    "ஓடிடி",
    "ஓடிடியில்",
    "ஓடிடி ரிலீஸ்",
    "ஓடிடி வெளியீடு",
    "ஓடிடியில் வெளியான",
    "ஓடிடியில் வெளியாகும்",
    "ஸ்ட்ரீமிங்",
    "ஸ்ட்ரீமிங் தளம்",
    "டிஜிட்டல் வெளியீடு",
    "டிஜிட்டல் ரிலீஸ்",
    "நெட்ஃப்ளிக்ஸ்",
    "அமேசான் பிரைம்",
    "ஜியோ ஹாட்ஸ்டார்",
    "சன் நெக்ஸ்ட்",

    "ഒടിടി",
    "ഒടിടിയിൽ",
    "ഒടിടി റിലീസ്",
    "ഒടിടി റിലീസിന്",
    "ഒടിടിയില്‍",
    "ഒടിടിയിൽ എത്തും",
    "സ്ട്രീമിംഗ്",
    "സ്ട്രീമിംഗ് പ്ലാറ്റ്ഫോം",
    "ഡിജിറ്റൽ റിലീസ്",
    "ഡിജിറ്റല്‍ റിലീസ്",
    "നെറ്റ്ഫ്ലിക്സ്",
    "ആമസോൺ പ്രൈം",
    "ജിയോ ഹോട്ട്സ്റ്റാർ",
    "സൺ നെക്സ്റ്റ്",
    "മനോരമ മാക്സ്",
]


RELEASE_KEYWORDS = [
    "release date",
    "release",
    "releasing",
    "released",
    "premiere",
    "premieres",
    "available",
    "now streaming",
    "streaming from",
    "streaming on",
    "watch from",
    "coming on",

    "വരും",
    "റിലീസ്",
    "റിലീസിന്",
    "എത്തും",
    "എത്തി",

    "வெளியீடு",
    "வெளியாகும்",
    "வெளியான",
    "வந்தாச்சு",
]


RIGHTS_KEYWORDS = [
    "digital rights",
    "streaming rights",
    "ott rights",
    "bought the rights",
    "acquired",
    "acquires",
    "rights sold",
    "streaming deal",
    "digital rights sold",

    "ഡിജിറ്റൽ റൈറ്റ്സ്",
    "ഒടിടി റൈറ്റ്സ്",
    "സ്ട്രീമിംഗ് റൈറ്റ്സ്",

    "டிஜிட்டல் உரிமை",
    "ஓடிடி உரிமை",
    "ஸ்ட்ரீமிங் உரிமை",
]


BAD_KEYWORDS = [
    "birthday",
    "birthday wishes",
    "interview",
    "exclusive interview",
    "photoshoot",
    "beauty",
    "glamour",
    "fashion",
    "relationship",
    "love life",
    "marriage",
    "divorce",
    "controversy",
    "viral",
    "troll",
    "trolled",
    "social media",
    "instagram",
    "twitter",
    "x post",
    "fans react",
    "fan reaction",
    "statement",
    "rumour",
    "rumor",
    "gossip",

    "ജന്മദിനം",
    "അഭിമുഖം",
    "പ്രണയം",
    "വിവാഹം",
    "വിവാഹമോചനം",
    "വൈറൽ",
    "ട്രോൾ",
    "താരത്തിന്റെ",
    "നടി പറഞ്ഞ",
    "നടൻ പറഞ്ഞ",

    "பிறந்தநாள்",
    "பிறந்த நாள்",
    "பேட்டி",
    "காதல்",
    "திருமணம்",
    "விவாகரத்து",
    "வைரல்",
    "ட்ரோல்",
    "ரசிகர்கள்",
    "நடிகர் கூறிய",
    "நடிகை கூறிய",
]


PLATFORM_KEYWORDS = [
    "netflix",
    "prime video",
    "amazon prime",
    "jiohotstar",
    "hotstar",
    "sun nxt",
    "sunnxt",
    "sonyliv",
    "zee5",
    "aha",
    "manorama max",
    "disney+",
]


# ==============================
# MEMORY
# ==============================

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

        return {}

    except Exception:
        return {}


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            memory,
            f,
            ensure_ascii=False,
            indent=2
        )


# ==============================
# TEXT HELPERS
# ==============================

def clean_text(text):
    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser"
    ).get_text(" ", strip=True)

    text = html.unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize(text):
    text = clean_text(text).lower()

    text = re.sub(
        r"[^\w\s\u0B80-\u0BFF\u0D00-\u0D7F]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def contains_any(text, keywords):
    text = normalize(text)

    for keyword in keywords:
        if normalize(keyword) in text:
            return True

    return False


# ==============================
# DATE
# ==============================

def get_entry_datetime(entry):

    parsed = None

    if getattr(
        entry,
        "published_parsed",
        None
    ):
        parsed = entry.published_parsed

    elif getattr(
        entry,
        "updated_parsed",
        None
    ):
        parsed = entry.updated_parsed

    if parsed:

        try:
            return datetime(
                *parsed[:6],
                tzinfo=timezone.utc
            )

        except Exception:
            pass

    for field in [
        "published",
        "updated",
        "pubDate"
    ]:

        value = entry.get(field)

        if value:

            try:

                parsed_time = feedparser._parse_date(
                    value
                )

                if parsed_time:

                    return datetime(
                        *parsed_time[:6],
                        tzinfo=timezone.utc
                    )

            except Exception:
                pass

    return None


# ==============================
# ARTICLE DATA
# ==============================

def fetch_article_data(url):

    result = {
        "description": "",
        "image": ""
    }

    if not url:
        return result

    try:

        response = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if response.status_code != 200:
            return result

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        meta_description = soup.find(
            "meta",
            attrs={
                "name": "description"
            }
        )

        if not meta_description:

            meta_description = soup.find(
                "meta",
                attrs={
                    "property": "og:description"
                }
            )

        if (
            meta_description
            and meta_description.get("content")
        ):

            result["description"] = clean_text(
                meta_description.get("content")
            )

        og_image = soup.find(
            "meta",
            attrs={
                "property": "og:image"
            }
        )

        if (
            og_image
            and og_image.get("content")
        ):

            result["image"] = og_image.get("content")

    except Exception as e:

        print(
            f"Article fetch failed: {e}"
        )

    return result


# ==============================
# FILTER
# ==============================

def is_ott_article(entry, feed):

    title = clean_text(
        entry.get("title", "")
    )

    summary = clean_text(
        entry.get("summary", "")
        or entry.get("description", "")
    )

    combined = f"{title} {summary}"

    has_ott = contains_any(
        combined,
        OTT_KEYWORDS
    )

    has_platform = contains_any(
        combined,
        PLATFORM_KEYWORDS
    )

    has_rights = contains_any(
        combined,
        RIGHTS_KEYWORDS
    )

    has_release = contains_any(
        combined,
        RELEASE_KEYWORDS
    )

    # Tamil OTT feed is already strongly focused
    # on OTT, so allow legitimate OTT stories
    # even when the title does not contain the word OTT.

    if feed["high_confidence"]:

        if contains_any(
            combined,
            BAD_KEYWORDS
        ):

            if not (
                has_ott
                or has_platform
                or has_rights
                or has_release
            ):
                return False

        return True

    # Other feeds need an OTT-related signal.

    if not (
        has_ott
        or has_platform
        or has_rights
    ):
        return False

    # Reject obvious celebrity/gossip stories
    # unless there is a genuine OTT signal.

    if contains_any(
        combined,
        BAD_KEYWORDS
    ):

        if not (
            has_platform
            or has_rights
            or (
                has_ott
                and has_release
            )
        ):
            return False

    return True


# ==============================
# IMAGE
# ==============================

def get_feed_image(entry):

    try:

        media_content = entry.get(
            "media_content"
        )

        if media_content:

            for item in media_content:

                if item.get("url"):
                    return item["url"]

        media_thumbnail = entry.get(
            "media_thumbnail"
        )

        if media_thumbnail:

            for item in media_thumbnail:

                if item.get("url"):
                    return item["url"]

        for link in entry.get(
            "links",
            []
        ):

            if link.get(
                "type",
                ""
            ).startswith("image/"):

                return link.get(
                    "href",
                    ""
                )

    except Exception:
        pass

    return ""


# ==============================
# SUMMARY
# ==============================

def make_summary(
    entry,
    article_data
):

    summary = clean_text(
        article_data.get("description", "")
        or entry.get("summary", "")
        or entry.get("description", "")
    )

    if not summary:
        return ""

    if len(summary) > 420:

        summary = (
            summary[:417]
            .rsplit(" ", 1)[0]
            + "..."
        )

    return summary


# ==============================
# CATEGORY
# ==============================

def get_category(
    entry,
    feed,
    summary
):

    combined = normalize(
        f"{entry.get('title', '')} {summary}"
    )

    if (
        contains_any(
            combined,
            RIGHTS_KEYWORDS
        )
        or "rights" in combined
        or "உரிமை" in combined
        or "റൈറ്റ്സ്" in combined
    ):

        return "DIGITAL RIGHTS"

    if contains_any(
        combined,
        [
            "now streaming",
            "released",
            "வெளியான",
            "എത്തി"
        ]
    ):

        return "NOW STREAMING"

    return "OTT UPDATE"


# ==============================
# TELEGRAM
# ==============================

def telegram_request(
    method,
    data=None,
    files=None
):

    url = (
        f"{TELEGRAM_API}/{method}"
    )

    response = requests.post(
        url,
        data=data,
        files=files,
        timeout=30
    )

    try:

        result = response.json()

    except Exception:

        result = {
            "ok": False,
            "description": response.text
        }

    if not result.get("ok"):

        print(
            f"Telegram error: {result}"
        )

    return result


# ==============================
# CAPTION
# ==============================

def build_caption(
    title,
    category,
    summary,
    language
):

    safe_title = html.escape(
        title
    )

    safe_summary = html.escape(
        summary
    )

    language_label = (
        "TAMIL"
        if language == "Tamil"
        else "MALAYALAM"
    )

    caption = (
        f"<b>🎬 {safe_title}</b>\n\n"
        f"<b>📺 {category}</b>\n"
        f"🌐 {language_label} • OTT\n\n"
    )

    if safe_summary:

        caption += (
            f"{safe_summary}\n\n"
        )

    caption += (
        "━━━━━━━━━━━━━━\n"
        "<b>OUR MOVIES • OTT NEWS</b>"
    )

    if len(caption) > 1000:

        caption = (
            caption[:997]
            + "..."
        )

    return caption


# ==============================
# SEND POST
# ==============================

def send_post(
    title,
    category,
    summary,
    language,
    image_url,
    article_url
):

    caption = build_caption(
        title,
        category,
        summary,
        language
    )

    reply_markup = json.dumps({
        "inline_keyboard": [[
            {
                "text": "📰 Read article",
                "url": article_url
            }
        ]]
    })

    # Try image post first

    if image_url:

        try:

            result = telegram_request(
                "sendPhoto",
                data={
                    "chat_id": CHANNEL,
                    "photo": image_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                }
            )

            if result.get("ok"):
                return True

        except Exception as e:

            print(
                f"Image post failed: {e}"
            )

    # Fallback to text post

    result = telegram_request(
        "sendMessage",
        data={
            "chat_id": CHANNEL,
            "text": caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
            "disable_web_page_preview": False
        }
    )

    return result.get(
        "ok",
        False
    )


# ==============================
# MAIN
# ==============================

def main():

    print(
        "======================================"
    )

    print(
        "MOVIE OTT NEWS BOT"
    )

    print(
        "======================================"
    )

    memory = load_memory()

    now = datetime.now(
        timezone.utc
    )

    cutoff = (
        now
        - timedelta(
            hours=MAX_ARTICLE_AGE_HOURS
        )
    )

    candidates = []

    # Check every feed

    for feed in FEEDS:

        print(
            f"\nChecking: {feed['name']}"
        )

        try:

            parsed = feedparser.parse(
                feed["url"]
            )

            print(
                f"Entries found: "
                f"{len(parsed.entries)}"
            )

        except Exception as e:

            print(
                f"Feed error "
                f"({feed['name']}): {e}"
            )

            continue

        for entry in parsed.entries:

            title = clean_text(
                entry.get(
                    "title",
                    ""
                )
            )

            url = (
                entry.get(
                    "link",
                    ""
                )
                .strip()
            )

            if not title or not url:
                continue

            item_id = str(
                entry.get("id")
                or entry.get("guid")
                or url
            )

            # Don't post the same article again

            if item_id in memory:
                continue

            published = get_entry_datetime(
                entry
            )

            # Ignore very old articles

            if (
                published
                and published < cutoff
            ):
                continue

            # Check OTT filter

            if not is_ott_article(
                entry,
                feed
            ):

                print(
                    f"Rejected: {title}"
                )

                continue

            # Get article information

            article_data = fetch_article_data(
                url
            )

            summary = make_summary(
                entry,
                article_data
            )

            image_url = (
                get_feed_image(entry)
                or article_data.get(
                    "image",
                    ""
                )
            )

            category = get_category(
                entry,
                feed,
                summary
            )

            # Ranking score

            score = 0

            if feed["high_confidence"]:
                score += 5

            if contains_any(
                f"{title} {summary}",
                RELEASE_KEYWORDS
            ):
                score += 3

            if contains_any(
                f"{title} {summary}",
                RIGHTS_KEYWORDS
            ):
                score += 3

            if contains_any(
                f"{title} {summary}",
                PLATFORM_KEYWORDS
            ):
                score += 2

            if image_url:
                score += 1

            if published:

                age_hours = (
                    now - published
                ).total_seconds() / 3600

                if age_hours < 6:
                    score += 2

            candidates.append({

                "id": item_id,

                "title": title,

                "url": url,

                "language": feed["language"],

                "summary": summary,

                "image": image_url,

                "category": category,

                "published": (
                    published.isoformat()
                    if published
                    else ""
                ),

                "score": score
            })

    # Best articles first

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["published"]
        ),
        reverse=True
    )

    print(
        f"\nValid OTT candidates: "
        f"{len(candidates)}"
    )

    posted_count = 0

    for item in candidates:

        if (
            posted_count
            >= MAX_POSTS_PER_RUN
        ):
            break

        print(
            f"\nPosting: "
            f"{item['title']}"
        )

        success = send_post(

            title=item["title"],

            category=item["category"],

            summary=item["summary"],

            language=item["language"],

            image_url=item["image"],

            article_url=item["url"]
        )

        if success:

            memory[item["id"]] = {

                "title": item["title"],

                "url": item["url"],

                "language": item["language"],

                "category": item["category"],

                "published": item["published"],

                "posted_at": now.isoformat()
            }

            posted_count += 1

            print(
                "Posted successfully."
            )

        else:

            print(
                "Posting failed."
            )

    save_memory(
        memory
    )

        print(
        "\n======================================"
    )

    print(
        f"Posted this run: "
        f"{posted_count}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
