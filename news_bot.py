import os
import re
import json
import html
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from difflib import SequenceMatcher


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = os.environ.get("CHANNEL", "@ouranime001")

POSTED_FILE = "posted.json"

MAX_POSTS_PER_RUN = 3
MAX_ARTICLE_AGE_HOURS = 6

FEEDS = [
    {
        "name": "Anime News Network",
        "url": "https://www.animenewsnetwork.com/rss.xml",
        "weight": 3,
    },
    {
        "name": "Otaku News",
        "url": "https://www.otakunews.com/Rss",
        "weight": 2,
    },
    {
        "name": "Crunchyroll News",
        "url": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
        "weight": 3,
    },
]


# ============================================================
# HTTP
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 (compatible; AnimeNewsBot/1.0; "
    "+https://github.com/)"
)


def http_get(url, timeout=20):
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "application/rss+xml, application/xml, "
                    "text/xml, text/html, */*"
                ),
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:
            return response.read()

    except Exception as e:
        print(f"HTTP error: {e}")
        return None


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_html(text):
    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def shorten(text, limit=360):
    text = clean_html(text)

    if len(text) <= limit:
        return text

    cut = text[:limit]

    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]

    return cut.rstrip(" .,;:") + "…"


def normalize_text(text):
    text = clean_html(text).lower()

    text = re.sub(
        r"https?://\S+",
        "",
        text,
    )

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_title(title):
    text = normalize_text(title)

    prefixes = [
        "crunchyroll news",
        "anime news network",
        "otaku news",
    ]

    for prefix in prefixes:
        if text.startswith(prefix + " "):
            text = text[len(prefix):].strip()

    return text


def title_similarity(a, b):
    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return 0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# DATE HELPERS
# ============================================================

def parse_date(value):
    if not value:
        return None

    value = value.strip()

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(
                value,
                fmt
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

        except Exception:
            pass

    return None


def article_is_fresh(date_value):
    dt = parse_date(date_value)

    if not dt:
        return True

    now = datetime.now(timezone.utc)

    age = now - dt

    if age.total_seconds() < 0:
        return True

    return (
        age.total_seconds()
        <= MAX_ARTICLE_AGE_HOURS * 3600
    )


# ============================================================
# RSS PARSING
# ============================================================

def local_name(tag):
    if "}" in tag:
        return tag.split(
            "}",
            1
        )[1].lower()

    return tag.lower()


def find_child(element, names):
    names = {
        name.lower()
        for name in names
    }

    for child in list(element):
        if local_name(child.tag) in names:
            return child

    return None


def child_text(element, names):
    child = find_child(
        element,
        names
    )

    if child is None:
        return ""

    return child.text or ""


def get_link(item):

    link = child_text(
        item,
        ["link"]
    ).strip()

    if link:
        return html.unescape(link)

    for child in list(item):

        if local_name(child.tag) == "link":

            href = child.attrib.get(
                "href"
            )

            if href:
                return html.unescape(
                    href
                )

    return ""


def get_image_from_item(item):

    # RSS enclosure
    for child in list(item):

        name = local_name(
            child.tag
        )

        if name in (
            "enclosure",
            "content"
        ):

            url = (
                child.attrib.get("url")
                or child.attrib.get("href")
                or ""
            )

            if url:

                media_type = (
                    child.attrib.get(
                        "type",
                        ""
                    ).lower()
                )

                if (
                    "image" in media_type
                    or name == "content"
                    or not media_type
                ):
                    return html.unescape(
                        url
                    )

    # media:thumbnail / media:content
    for child in list(item):

        name = local_name(
            child.tag
        )

        if name in (
            "thumbnail",
            "content"
        ):

            url = (
                child.attrib.get("url")
                or child.attrib.get("href")
                or ""
            )

            if url:
                return html.unescape(
                    url
                )

    return ""


def parse_feed(
    xml_data,
    source_name,
    source_weight
):

    if not xml_data:
        return []

    try:
        root = ET.fromstring(
            xml_data
        )

    except Exception as e:
        print(
            f"RSS parse error: {e}"
        )
        return []

    items = []

    for item in root.iter():

        if local_name(item.tag) not in (
            "item",
            "entry"
        ):
            continue

        title = child_text(
            item,
            ["title"]
        ).strip()

        link = get_link(item)

        description = child_text(
            item,
            [
                "description",
                "summary",
                "content"
            ]
        ).strip()

        pub_date = child_text(
            item,
            [
                "pubDate",
                "published",
                "updated",
                "date"
            ]
        ).strip()

        image = get_image_from_item(
            item
        )

        if not title or not link:
            continue

        items.append(
            {
                "title": clean_html(title),
                "summary": clean_html(
                    description
                ),
                "url": link,
                "date": pub_date,
                "image": image,
                "source": source_name,
                "weight": source_weight,
            }
        )

    return items


# ============================================================
# ARTICLE IMAGE EXTRACTION
# ============================================================

def extract_image_from_html(page):

    if not page:
        return ""

    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page,
            flags=re.IGNORECASE,
        )

        if match:

            image_url = html.unescape(
                match.group(1).strip()
            )

            if image_url.startswith("//"):
                image_url = (
                    "https:" + image_url
                )

            if image_url.startswith(
                "http"
            ):
                return image_url

    images = re.findall(
        r'<img[^>]+src=["\']([^"\']+)["\']',
        page,
        flags=re.IGNORECASE,
    )

    for image_url in images:

        image_url = html.unescape(
            image_url.strip()
        )

        if image_url.startswith("//"):
            image_url = (
                "https:" + image_url
            )

        if not image_url.startswith(
            "http"
        ):
            continue

        lowered = image_url.lower()

        if any(
            x in lowered
            for x in [
                "logo",
                "icon",
                "avatar",
                "favicon",
                "sprite",
            ]
        ):
            continue

        return image_url

    return ""


def get_article_image(article):

    if article.get("image"):
        return article["image"]

    page = http_get(
        article["url"]
    )

    if not page:
        return ""

    try:
        page_text = page.decode(
            "utf-8",
            errors="ignore"
        )

    except Exception:
        return ""

    return extract_image_from_html(
        page_text
    )


# ============================================================
# ANIME NEWS FILTER
# ============================================================

IMPORTANT_ANIME_PATTERNS = [

    # Seasons / cours
    r"\bseason\s+\d+\b",
    r"\bnew\s+season\b",
    r"\bsecond\s+cour\b",
    r"\bthird\s+cour\b",
    r"\bcour\s+\d+\b",

    # Release / premiere
    r"\bpremiere\b",
    r"\bpremiere\s+date\b",
    r"\brelease\s+date\b",
    r"\breleases?\s+on\b",
    r"\bdebut\b",
    r"\bdebut\s+date\b",
    r"\bstarts?\s+on\b",

    # Announcements
    r"\banime\s+announced\b",
    r"\banime\s+adaptation\b",
    r"\banime\s+confirmed\b",
    r"\banime\s+revealed\b",
    r"\bnew\s+anime\b",
    r"\bproduction\s+confirmed\b",
    r"\bproduction\s+announced\b",

    # Important trailers / visuals
    r"\bnew\s+trailer\b",
    r"\btrailer\s+reveals?\b",
    r"\btrailer\s+unveils?\b",
    r"\bkey\s+visual\b",
    r"\bmain\s+visual\b",

    # Streaming
    r"\bstream(?:ing)?\s+on\b",
    r"\bstreaming\s+date\b",
    r"\bnow\s+streaming\b",

    # Delays / changes
    r"\bdelayed\b",
    r"\bdelay\b",
    r"\bpostponed\b",
    r"\brescheduled\b",
    r"\bnew\s+release\s+date\b",

    # Major adaptations
    r"\bmovie\s+adaptation\b",
    r"\bfilm\s+adaptation\b",
    r"\blive[- ]action\s+adaptation\b",
    r"\bgreenlit\b",
]


BAD_ANIME_PATTERNS = [

    # Cast-only stories
    r"\bvoice\s+cast\b",
    r"\bcast\s+revealed\b",
    r"\bcast\s+announced\b",
    r"\badditional\s+cast\b",
    r"\bvoice\s+actor\b",
    r"\bvoice\s+actress\b",
    r"\bjoins?\s+the\s+cast\b",

    # Interviews / features
    r"\binterview\b",
    r"\bq&a\b",
    r"\bbehind\s+the\s+scenes\b",
    r"\bfeature\b",
    r"\bspotlight\b",

    # Recaps / guides
    r"\brecap\b",
    r"\breview\b",
    r"\bexplained\b",
    r"\bguide\b",
    r"\bquiz\b",
    r"\btop\s+\d+\b",
    r"\bbest\s+\d+\b",

    # Merchandise
    r"\bmerch\b",
    r"\bmerchandise\b",
    r"\bfigures?\b",
    r"\bcollectibles?\b",

    # Games
    r"\bmobile\s+game\b",
    r"\bvideo\s+game\b",
    r"\bgame\s+update\b",
    r"\bdlc\b",

    # Music-only
    r"\bnew\s+single\b",
    r"\bmusic\s+video\b",
]


def is_good_anime_news(
    title,
    summary=""
):

    text = (
        f"{title} {summary}"
    ).lower()

    # Reject obvious low-value articles.
    for pattern in BAD_ANIME_PATTERNS:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):

            important = any(
                re.search(
                    pattern2,
                    text,
                    re.IGNORECASE
                )
                for pattern2
                in IMPORTANT_ANIME_PATTERNS
            )

            if not important:
                return False

    release_signal = any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bpremiere\b",
            r"\brelease\s+date\b",
            r"\bdebut\b",
            r"\breleases?\s+on\b",
            r"\bstarts?\s+on\b",
            r"\bstream(?:ing)?\s+on\b",
        ]
    )

    announcement_signal = any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bannounced\b",
            r"\bconfirmed\b",
            r"\brevealed\b",
            r"\bunveils?\b",
            r"\bset\s+to\b",
        ]
    )

    if (
        release_signal
        and announcement_signal
    ):
        return True

    season_signal = any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bseason\s+\d+\b",
            r"\bnew\s+season\b",
            r"\bsecond\s+cour\b",
            r"\bthird\s+cour\b",
            r"\bcour\s+\d+\b",
        ]
    )

    if (
        season_signal
        and (
            release_signal
            or announcement_signal
        )
    ):
        return True

    score = sum(
        1
        for pattern
        in IMPORTANT_ANIME_PATTERNS
        if re.search(
            pattern,
            text,
            re.IGNORECASE
        )
    )

    if score >= 2:
        return True

    strong_score = sum(
        1
        for pattern in [
            r"\bofficial\b",
            r"\bannounced\b",
            r"\bconfirmed\b",
            r"\brevealed\b",
            r"\bunveils?\b",
            r"\bset\s+to\b",
        ]
        if re.search(
            pattern,
            text,
            re.IGNORECASE
        )
    )

    if (
        score >= 1
        and strong_score >= 2
    ):
        return True

    return False


# ============================================================
# DUPLICATE MEMORY
# ============================================================

def load_posted():

    if not os.path.exists(
        POSTED_FILE
    ):
        return []

    try:

        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            list
        ):
            return data

        if isinstance(
            data,
            dict
        ):
            return data.get(
                "posts",
                []
            )

    except Exception:
        pass

    return []


def save_posted(posts):

    posts = posts[-1000:]

    with open(
        POSTED_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            posts,
            file,
            ensure_ascii=False,
            indent=2,
        )


def article_id(article):

    url = article.get(
        "url",
        ""
    ).strip()

    if url:

        return hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

    return hashlib.sha256(
        article.get(
            "title",
            ""
        ).encode("utf-8")
    ).hexdigest()


def is_duplicate(
    article,
    posted
):

    aid = article_id(
        article
    )

    for old in posted:

        if isinstance(
            old,
            dict
        ):

            if old.get(
                "id"
            ) == aid:
                return True

            old_title = old.get(
                "title",
                ""
            )

            if (
                old_title
                and title_similarity(
                    article["title"],
                    old_title
                ) >= 0.88
            ):
                return True

        elif isinstance(
            old,
            str
        ):

            if old == aid:
                return True

    return False


# ============================================================
# SCORING
# ============================================================

def article_score(article):

    title = article.get(
        "title",
        ""
    )

    summary = article.get(
        "summary",
        ""
    )

    text = (
        f"{title} {summary}"
    ).lower()

    score = (
        article.get(
            "weight",
            1
        ) * 2
    )

    important_patterns = [
        r"\bseason\s+\d+\b",
        r"\bpremiere\s+date\b",
        r"\brelease\s+date\b",
        r"\banime\s+announced\b",
        r"\banime\s+adaptation\b",
        r"\bdelayed\b",
        r"\bpostponed\b",
        r"\brescheduled\b",
    ]

    for pattern in important_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):
            score += 5

    strong_patterns = [
        r"\bofficial\b",
        r"\bannounced\b",
        r"\bconfirmed\b",
        r"\brevealed\b",
        r"\bunveils?\b",
    ]

    for pattern in strong_patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):
            score += 2

    dt = parse_date(
        article.get(
            "date",
            ""
        )
    )

    if dt:

        age_hours = (
            datetime.now(
                timezone.utc
            ) - dt
        ).total_seconds() / 3600

        if age_hours <= 2:
            score += 5

        elif age_hours <= 4:
            score += 3

        elif age_hours <= 6:
            score += 1

    return score


# ============================================================
# TITLE CLEANING
# ============================================================

def clean_title(title):

    title = clean_html(
        title
    )

    title = re.sub(
        r"\s*[-|–—]\s*"
        r"(Crunchyroll|Anime News Network|Otaku News)"
        r"\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    return title.strip()


# ============================================================
# NEWS CATEGORY
# ============================================================

def get_category(article):

    text = (
        f"{article.get('title', '')} "
        f"{article.get('summary', '')}"
    ).lower()

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bseason\s+\d+\b",
            r"\bnew\s+season\b",
            r"\bsecond\s+cour\b",
            r"\bthird\s+cour\b",
        ]
    ):
        return "NEW SEASON"

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bpremiere\b",
            r"\brelease\s+date\b",
            r"\breleases?\s+on\b",
            r"\bdebut\b",
            r"\bstarts?\s+on\b",
        ]
    ):
        return "RELEASE UPDATE"

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bnew\s+trailer\b",
            r"\btrailer\s+reveals?\b",
            r"\btrailer\s+unveils?\b",
            r"\bkey\s+visual\b",
            r"\bmain\s+visual\b",
        ]
    ):
        return "TRAILER / VISUAL"

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bdelayed\b",
            r"\bpostponed\b",
            r"\brescheduled\b",
            r"\bnew\s+release\s+date\b",
        ]
    ):
        return "RELEASE CHANGE"

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\banime\s+adaptation\b",
            r"\banime\s+announced\b",
            r"\bproduction\s+announced\b",
            r"\bproduction\s+confirmed\b",
        ]
    ):
        return "NEW ANIME"

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [
            r"\bstream(?:ing)?\s+on\b",
            r"\bnow\s+streaming\b",
            r"\bstreaming\s+date\b",
        ]
    ):
        return "STREAMING UPDATE"

    return "ANIME UPDATE"


# ============================================================
# DATE EXTRACTION
# ============================================================

def extract_important_date(article):

    text = clean_html(
        f"{article.get('title', '')} "
        f"{article.get('summary', '')}"
    )

    patterns = [
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(0)

    return ""


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_request(
    method,
    payload
):

    if not BOT_TOKEN:
        return None

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/{method}"
    )

    data = urllib.parse.urlencode(
        payload
    ).encode("utf-8")

    try:

        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": USER_AGENT,
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            raw = response.read().decode(
                "utf-8",
                errors="ignore"
            )

            result = json.loads(
                raw
            )

            if not result.get(
                "ok",
                False
            ):
                print(
                    f"Telegram error: "
                    f"{result}"
                )

            return result

    except Exception as e:

        print(
            f"Telegram request error: {e}"
        )

        return None


# ============================================================
# POST DESIGN
# ============================================================

def make_post(article):

    title = clean_title(
        article["title"]
    )

    summary = shorten(
        article.get(
            "summary",
            ""
        ),
        360
    )

    if not summary:

        summary = (
            "A new official update "
            "has been announced "
            "for this anime."
        )

    category = get_category(
        article
    )

    important_date = (
        extract_important_date(
            article
        )
    )

    safe_title = html.escape(
        title
    )

    safe_summary = html.escape(
        summary
    )

    safe_category = html.escape(
        category
    )

    caption = (
        "<b>🎬 OUR ANIME</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>✨ {safe_category}</b>\n\n"
        f"<b>{safe_title}</b>\n\n"
    )

    if important_date:

        safe_date = html.escape(
            important_date
        )

        caption += (
            f"📅 <b>{safe_date}</b>\n\n"
        )

    caption += (
        f"{safe_summary}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>🔥 OUR ANIME • NEWS</b>"
    )

    if len(caption) > 1000:

        caption = (
            caption[:997]
            + "..."
        )

    return caption


# ============================================================
# SEND POST
# ============================================================

def send_message(text):

    return telegram_request(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


def send_photo(
    image_url,
    caption
):

    return telegram_request(
        "sendPhoto",
        {
            "chat_id": CHANNEL,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "HTML",
        },
    )


def publish_article(article):

    caption = make_post(
        article
    )

    image_url = get_article_image(
        article
    )

    if image_url:

        print(
            "Trying image post..."
        )

        result = send_photo(
            image_url,
            caption
        )

        if (
            result
            and result.get("ok")
        ):
            print(
                "Image post successful."
            )
            return True

        print(
            "Image post failed. "
            "Falling back to text."
        )

    result = send_message(
        caption
    )

    if (
        result
        and result.get("ok")
    ):
        print(
            "Text post successful."
        )
        return True

    print(
        "Text post failed."
    )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        print(
            "ERROR: BOT_TOKEN is missing."
        )

        return

    print(
        "======================================"
    )

    print(
        "        OUR ANIME NEWS BOT"
    )

    print(
        "======================================"
    )

    all_articles = []

    for feed in FEEDS:

        print(
            f"\nChecking {feed['name']}..."
        )

        data = http_get(
            feed["url"]
        )

        if not data:

            print(
                f"Could not fetch "
                f"{feed['name']}"
            )

            continue

        articles = parse_feed(
            data,
            feed["name"],
            feed["weight"],
        )

        print(
            f"Found {len(articles)} "
            f"articles from "
            f"{feed['name']}"
        )

        all_articles.extend(
            articles
        )

    if not all_articles:

        print(
            "\nNo articles found."
        )

        return

    unique = {}

    for article in all_articles:

        key = article.get(
            "url",
            ""
        ).strip()

        if not key:
            continue

        if key not in unique:

            unique[key] = article

        elif (
            article.get(
                "weight",
                0
            )
            > unique[key].get(
                "weight",
                0
            )
        ):

            unique[key] = article

    all_articles = list(
        unique.values()
    )

    print(
        f"\n{len(all_articles)} "
        f"unique articles."
    )

    posted = load_posted()

    candidates = []

    for article in all_articles:

        title = article.get(
            "title",
            ""
        )

        if not title:
            continue

        if not article_is_fresh(
            article.get(
                "date",
                ""
            )
        ):

            print(
                f"Old article: {title}"
            )

            continue

        if is_duplicate(
            article,
            posted
        ):

            print(
                f"Duplicate: {title}"
            )

            continue

        if not is_good_anime_news(
            article.get(
                "title",
                ""
            ),
            article.get(
                "summary",
                ""
            ),
        ):

            print(
                f"Rejected: {title}"
            )

            continue

        score = article_score(
            article
        )

        article["score"] = score

        candidates.append(
            article
        )

        print(
            f"Candidate [{score}]: "
            f"{title}"
        )

    candidates.sort(
        key=lambda article: (
            article.get(
                "score",
                0
            ),
            parse_date(
                article.get(
                    "date",
                    ""
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),
        ),
        reverse=True,
    )

    print(
        f"\nQualified articles: "
        f"{len(candidates)}"
    )

    if not candidates:

        print(
            "No new qualifying "
            "anime news this run."
        )

        return

    posted_count = 0

    for article in candidates:

        if (
            posted_count
            >= MAX_POSTS_PER_RUN
        ):
            break

        print(
            "\n--------------------------------------"
        )

        print(
            f"Posting: "
            f"{article['title']}"
        )

        success = publish_article(
            article
        )

        if success:

            posted.append(
                {
                    "id": article_id(
                        article
                    ),
                    "title": clean_title(
                        article["title"]
                    ),
                    "url": article.get(
                        "url",
                        ""
                    ),
                    "posted_at": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                }
            )

            posted_count += 1

            print(
                "Posted successfully."
            )

        else:

            print(
                "Posting failed."
            )

    save_posted(
        posted
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
