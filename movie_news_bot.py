import os, json, re, html, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["MOVIE_CHANNEL"]
STATE_FILE = "movie_posted.json"

IST = ZoneInfo("Asia/Kolkata")

MAX_NEW_POSTS = 3
MAX_RELEASE_POSTS = 3

# ============================================================
# RSS FEEDS
# Malayalam + Tamil cinema/OTT
# ============================================================

RSS_FEEDS = [
    "https://malayalam.oneindia.com/rss/feeds/malayalam-cinema-fb.xml",
    "https://malayalam.oneindia.com/rss/feeds/malayalam-movie-news-fb.xml",
    "https://tamil.oneindia.com/rss/feeds/tamil-cinema-fb.xml",
    "https://tamil.oneindia.com/rss/feeds/tamil-ott-fb.xml",
]

# ============================================================
# OTT PLATFORMS
# ============================================================

PLATFORMS = {
    "amazon prime video": "Prime Video",
    "prime video": "Prime Video",
    "netflix": "Netflix",
    "jiohotstar": "JioHotstar",
    "hotstar": "JioHotstar",
    "disney+ hotstar": "JioHotstar",
    "sonyliv": "SonyLIV",
    "sony liv": "SonyLIV",
    "zee5": "ZEE5",
    "aha": "Aha",
    "sunnxt": "Sun NXT",
    "sun nxt": "Sun NXT",
    "manorama max": "ManoramaMAX",
    "manoramamax": "ManoramaMAX",
    "saina play": "Saina Play",
    "tentkotta": "Tentkotta",
}

OTT_TERMS = [
    "ott",
    "streaming",
    "stream",
    "digital release",
    "digital premiere",
    "digital rights",
    "streaming rights",
    "ott rights",
    "online release",
    "online streaming",
    "now streaming",
    "now available",
    "available to stream",
    "premiere on",

    # Malayalam
    "ഒടിടി",
    "ഓടിടി",
    "സ്ട്രീമിംഗ്",
    "ഡിജിറ്റൽ റിലീസ്",
    "ഡിജിറ്റൽ",
    "ഒടിടി റിലീസ്",

    # Tamil
    "ஓடிடி",
    "ஒடிடி",
    "ஸ்ட்ரீமிங்",
    "டிஜிட்டல் ரிலீஸ்",
    "டிஜிட்டல்",
    "ஓடிடி ரிலீஸ்",
]

BAD_TITLE_TERMS = [
    "birthday",
    "photoshoot",
    "fashion",
    "interview",
    "viral",
    "instagram",
    "box office",
    "collection",
    "first look",
    "teaser",
    "trailer",
    "song",
    "poster",
    "making video",
    "behind the scenes",
]

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


# ============================================================
# TEXT
# ============================================================

def clean(text):
    if not text:
        return ""

    text = html.unescape(text)

    text = re.sub(
        r"<script.*?</script>|<style.*?</style>",
        " ",
        text,
        flags=re.I | re.S
    )

    text = re.sub(r"<[^>]+>", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def norm(text):
    return clean(text).lower()


def similar(a, b):
    return SequenceMatcher(
        None,
        norm(a),
        norm(b)
    ).ratio()


def escape_html(text):
    return html.escape(
        clean(text),
        quote=False
    )


# ============================================================
# MEMORY
# ============================================================

def load_state():
    try:
        with open(
            STATE_FILE,
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            posted = data.get("posted", [])
            announcements = data.get("announcements", {})

            if not isinstance(posted, list):
                posted = []

            if not isinstance(announcements, dict):
                announcements = {}

            return {
                "posted": posted,
                "announcements": announcements
            }

    except Exception:
        pass

    return {
        "posted": [],
        "announcements": {}
    }


def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# RSS
# ============================================================

def fetch_feed(url):
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "Mozilla/5.0 MovieOTTNewsBot/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:
            return response.read()

    except Exception as e:
        print("Feed failed:", url, e)
        return None


def local_name(tag):
    return tag.rsplit(
        "}",
        1
    )[-1].lower()


def child_text(item, names):
    for child in list(item):
        if local_name(child.tag) in names:
            return clean(
                " ".join(child.itertext())
            )

    return ""


def get_link(item):
    for child in list(item):

        if local_name(child.tag) != "link":
            continue

        href = child.attrib.get(
            "href",
            ""
        ).strip()

        if href:
            return html.unescape(href)

        text = clean(
            "".join(child.itertext())
        )

        if text:
            return text

    return ""


def get_image_from_rss(item):
    for child in item.iter():

        tag = local_name(child.tag)

        if tag not in {
            "enclosure",
            "content",
            "thumbnail"
        }:
            continue

        url = (
            child.attrib.get("url")
            or child.attrib.get("href")
        )

        if not url:
            continue

        file_type = child.attrib.get(
            "type",
            ""
        )

        if (
            tag != "enclosure"
            or file_type.startswith("image/")
            or not file_type
        ):
            return html.unescape(url)

    return ""


def parse_feed(data):
    results = []

    try:
        root = ET.fromstring(data)

    except Exception as e:
        print("XML error:", e)
        return results

    for item in root.iter():

        if local_name(item.tag) not in {
            "item",
            "entry"
        }:
            continue

        title = child_text(
            item,
            {"title"}
        )

        link = get_link(item)

        description = child_text(
            item,
            {
                "description",
                "summary",
                "content",
                "encoded"
            }
        )

        if not title or not link:
            continue

        results.append({
            "title": title,
            "description": description,
            "url": link,
            "image": get_image_from_rss(item)
        })

    return results


# ============================================================
# ARTICLE IMAGE
# ============================================================

def get_article_image(url):
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "Mozilla/5.0 MovieOTTNewsBot/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            text = response.read(
                300000
            ).decode(
                "utf-8",
                errors="ignore"
            )

        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.I
            )

            if match:
                image = html.unescape(
                    match.group(1)
                )

                if image.startswith("//"):
                    image = "https:" + image

                return image

    except Exception as e:
        print("Image error:", e)

    return ""


# ============================================================
# OTT DETECTION
# ============================================================

def find_platform(text):
    text = norm(text)

    for keyword, platform in sorted(
        PLATFORMS.items(),
        key=lambda x: len(x[0]),
        reverse=True
    ):
        if keyword in text:
            return platform

    return ""


def has_ott(text):
    text = norm(text)

    return any(
        keyword in text
        for keyword in OTT_TERMS
    )


def bad_title(title):
    title = norm(title)

    return (
        sum(
            term in title
            for term in BAD_TITLE_TERMS
        ) >= 2
    )


# ============================================================
# IMPORTANT:
# Only search for a release date near OTT-related words.
#
# This reduces the chance of accidentally taking
# an unrelated date from an article.
# ============================================================

def release_context(text):
    raw = clean(text)
    low = raw.lower()

    pattern = (
        r"ott|streaming|digital release|digital premiere|"
        r"digital rights|streaming rights|ott rights|"
        r"available to stream|now streaming|premiere on|"
        r"netflix|prime video|jiohotstar|hotstar|"
        r"sonyliv|zee5|aha|sunnxt|sun nxt|"
        r"manorama max|manoramamax|saina play|tentkotta|"
        r"ഒടിടി|ഓടിടി|സ്ട്രീമിംഗ്|ഡിജിറ്റൽ|"
        r"ஓடிடி|ஒடிடி|ஸ்ட்ரீமிங்|டிஜிட்டல்"
    )

    anchors = list(
        re.finditer(
            pattern,
            low,
            flags=re.I
        )
    )

    windows = []

    for anchor in anchors:

        start = max(
            0,
            anchor.start() - 220
        )

        end = min(
            len(raw),
            anchor.end() + 300
        )

        windows.append(
            raw[start:end]
        )

    return " ".join(windows)


# ============================================================
# DATE DETECTION
# ============================================================

def parse_release_date(text, today):
    text = clean(text)

    month_pattern = "|".join(
        sorted(
            MONTHS,
            key=len,
            reverse=True
        )
    )

    patterns = [

        # 20 May 2026
        # 20 May
        rf"\b(\d{{1,2}})"
        rf"(?:st|nd|rd|th)?"
        rf"\s+({month_pattern})"
        rf"(?:\s*,?\s*(20\d{{2}}))?\b",

        # May 20 2026
        # May 20
        rf"\b({month_pattern})"
        rf"\s+(\d{{1,2}})"
        rf"(?:st|nd|rd|th)?"
        rf"(?:\s*,?\s*(20\d{{2}}))?\b",

        # 2026-05-20
        r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b",

        # 20-05-2026
        r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b",
    ]

    for index, pattern in enumerate(patterns):

        match = re.search(
            pattern,
            text,
            flags=re.I
        )

        if not match:
            continue

        try:

            if index == 0:

                day, month, year = match.groups()

                year = (
                    int(year)
                    if year
                    else today.year
                )

                result = date(
                    year,
                    MONTHS[month.lower()],
                    int(day)
                )

                if (
                    not match.group(3)
                    and result < today
                ):
                    result = date(
                        today.year + 1,
                        result.month,
                        result.day
                    )

            elif index == 1:

                month, day, year = match.groups()

                year = (
                    int(year)
                    if year
                    else today.year
                )

                result = date(
                    year,
                    MONTHS[month.lower()],
                    int(day)
                )

                if (
                    not match.group(3)
                    and result < today
                ):
                    result = date(
                        today.year + 1,
                        result.month,
                        result.day
                    )

            elif index == 2:

                year, month, day = map(
                    int,
                    match.groups()
                )

                result = date(
                    year,
                    month,
                    day
                )

            else:

                day, month, year = map(
                    int,
                    match.groups()
                )

                result = date(
                    year,
                    month,
                    day
                )

            return result

        except ValueError:
            continue

    return None


# ============================================================
# STORY STATUS
# ============================================================

def story_status(text):
    text = norm(text)

    now_terms = [
        "now streaming",
        "now available",
        "streaming now",
        "available to stream",
        "released on ott",
        "ott release today",
    ]

    if any(
        term in text
        for term in now_terms
    ):
        return "now"

    announcement_terms = [
        "will stream",
        "streaming on",
        "streaming from",
        "releasing on",
        "release date",
        "ott release",
        "digital release",
        "premiere on",
        "available from",
    ]

    if any(
        term in text
        for term in announcement_terms
    ):
        return "announced"

    return ""


# ============================================================
# DUPLICATE PROTECTION
# ============================================================

def already_posted(state, item):
    for old in state["posted"]:

        if not isinstance(
            old,
            dict
        ):
            continue

        if old.get("url") == item["url"]:
            return True

        if (
            old.get("title")
            and similar(
                old["title"],
                item["title"]
            ) >= 0.90
        ):
            return True

    return False


# ============================================================
# TELEGRAM
# ============================================================

def telegram_request(
    method,
    params
):
    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    data = urllib.parse.urlencode(
        params
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        result = json.loads(
            response.read().decode()
        )

    if not result.get("ok"):
        raise RuntimeError(
            result.get(
                "description",
                "Telegram error"
            )
        )

    return result


# ============================================================
# POST
# ============================================================

def send_item(item, caption):
    image = item.get("image", "")

    if not image and item.get("url"):
        image = get_article_image(
            item["url"]
        )

    if image:

        try:

            telegram_request(
                "sendPhoto",
                {
                    "chat_id": CHANNEL,
                    "photo": image,
                    "caption": caption,
                    "parse_mode": "HTML"
                }
            )

            return True

        except Exception as e:

            print(
                "Photo failed:",
                e
            )

    try:

        telegram_request(
            "sendMessage",
            {
                "chat_id": CHANNEL,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
        )

        return True

    except Exception as e:

        print(
            "Telegram message failed:",
            e
        )

        return False


# ============================================================
# CAPTIONS
# ============================================================

def announcement_caption(
    title,
    platform,
    release_date
):
    if platform:

        return (
            "🎬 <b>OTT Release Announced</b>\n\n"
            f"<b>{escape_html(title)}</b> will be "
            f"available on <b>{escape_html(platform)}</b> "
            f"from <b>{release_date.strftime('%d %B %Y')}</b>."
        )

    return (
        "🎬 <b>OTT Release Announced</b>\n\n"
        f"<b>{escape_html(title)}</b> will be "
        f"available on OTT from "
        f"<b>{release_date.strftime('%d %B %Y')}</b>."
)
