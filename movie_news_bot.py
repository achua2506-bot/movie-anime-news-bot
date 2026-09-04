import os
import re
import json
import html
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL = os.environ.get("MOVIE_CHANNEL", "").strip()

FEEDS = [
    (
        "Malayalam",
        "https://malayalam.oneindia.com/rss/feeds/malayalam-cinema-fb.xml",
    ),
    (
        "Malayalam",
        "https://malayalam.oneindia.com/rss/feeds/malayalam-movie-news-fb.xml",
    ),
    (
        "Tamil",
        "https://tamil.oneindia.com/rss/feeds/tamil-cinema-fb.xml",
    ),
    (
        "Tamil",
        "https://tamil.oneindia.com/rss/feeds/tamil-ott-fb.xml",
    ),
]

STATE_FILE = "movie_posted.json"

MAX_ITEMS_PER_FEED = 20
MAX_CANDIDATES_TO_FETCH = 12
MAX_POSTS_PER_RUN = 3

REQUEST_TIMEOUT = 15
LOOKBACK_DAYS = 14

SIMILARITY_THRESHOLD = 0.88


# ============================================================
# MONTHS
# ============================================================

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


# ============================================================
# OTT PLATFORMS
# ============================================================

PLATFORMS = [
    ("JioHotstar", ["jiohotstar", "jio hotstar", "hotstar"]),
    ("Netflix", ["netflix"]),
    ("Prime Video", ["prime video", "amazon prime", "primevideo"]),
    ("SonyLIV", ["sonyliv", "sony liv"]),
    ("ZEE5", ["zee5", "zee 5"]),
    ("Sun NXT", ["sun nxt", "sunnxt"]),
    ("ManoramaMAX", ["manorama max", "manoramamax"]),
    ("aha", ["aha"]),
    ("ETV Win", ["etv win", "etvwin"]),
    ("Saina Play", ["saina play", "sainaplay"]),
    ("Simply South", ["simply south"]),
    ("Tentkotta", ["tentkotta"]),
    ("Disney+", ["disney+"]),
    ("Apple TV+", ["apple tv+"]),
]


# ============================================================
# FILTERS
# ============================================================

OTT_WORDS = [
    "ott",
    "streaming",
    "stream",
    "digital premiere",
    "digital release",
    "digital debut",
    "online release",
    "watch online",
    "where to watch",
    "available on",
    "premiere on",
    "streaming on",
    "released on ott",
]


BAD_PATTERNS = [
    r"\b(actor|actress|hero|heroine)\b.*\b(interview|birthday|look|photo|pics|talks|says)\b",
    r"\b(interview|birthday|photoshoot|first look|glamour|viral photo)\b",
    r"\b(box office|collection|collections|gross|crore|hit|flop)\b",
    r"\b(trailer|teaser|song|lyric video|first single)\b",
    r"\b(review|rating|ratings|verdict)\b",
    r"\b(cast|star cast|actor cast|voice)\b",
]


LISTICLE_PATTERNS = [
    r"\bott releases? this week\b",
    r"\bmovies? releasing on ott\b",
    r"\bmovies? on ott this week\b",
    r"\bcomplete list\b",
    r"\bfull list\b",
    r"\btop \d+\b",
    r"\b\d+ movies?\b.*\bott\b",
]


ADULT_PATTERNS = [
    r"\bporn\b",
    r"\bxxx\b",
    r"\badult content\b",
    r"\bexplicit sexual\b",
]


POSITIVE_PATTERNS = [
    r"\bott\b.*\b(release|released|release date|premiere|stream|streaming|available|debut)\b",
    r"\b(release|released|release date|premiere|stream|streaming|available|debut)\b.*\bott\b",
    r"\b(ott|digital)\b.*\b(date|confirmed|announcement|announced|locked|official)\b",
    r"\b(streaming|available)\b.*\b(on|from)\b",
]


NOW_PATTERNS = [
    r"\bnow streaming\b",
    r"\bnow available\b",
    r"\bavailable now\b",
    r"\bstarted streaming\b",
    r"\bstarts streaming today\b",
    r"\bstreaming today\b",
    r"\breleased today\b",
    r"\bott release today\b",
    r"\bavailable from today\b",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def norm(value):
    value = html.unescape(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def title_key(value):
    value = norm(value)

    stop_words = {
        "ott",
        "release",
        "date",
        "confirmed",
        "official",
        "streaming",
        "movie",
        "film",
        "on",
        "from",
        "the",
    }

    words = [
        word
        for word in value.split()
        if word not in stop_words
    ]

    return " ".join(words)


def similarity(a, b):
    a = norm(a)
    b = norm(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


# ============================================================
# HTTP
# ============================================================

def request(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; OTTNewsBot/1.0)"
            )
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=REQUEST_TIMEOUT
    ) as response:

        return response.read()


# ============================================================
# HTML PARSER
# ============================================================

class MetaParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.meta = {}
        self.title_parts = []

        self.in_title = False
        self.in_body = False

        self.body_parts = []

    def handle_starttag(self, tag, attrs):

        attrs = dict(attrs)

        tag = tag.lower()

        if tag == "meta":

            key = (
                attrs.get("property")
                or attrs.get("name")
            )

            content = attrs.get("content")

            if key and content:
                self.meta[
                    key.lower()
                ] = content.strip()

        elif tag == "title":

            self.in_title = True

        elif tag == "body":

            self.in_body = True

    def handle_endtag(self, tag):

        tag = tag.lower()

        if tag == "title":

            self.in_title = False

        elif tag == "body":

            self.in_body = False

    def handle_data(self, data):

        if self.in_title:
            self.title_parts.append(data)

        if self.in_body:
            self.body_parts.append(data)


# ============================================================
# ARTICLE PAGE DATA
# ============================================================

def fetch_page_data(url):

    try:

        raw = request(url)

        text = raw.decode(
            "utf-8",
            errors="ignore"
        )

        parser = MetaParser()

        parser.feed(text)

        meta = parser.meta

        title = clean_text(
            " ".join(
                parser.title_parts
            )
        )

        body = clean_text(
            " ".join(
                parser.body_parts
            )
        )

        english_summary = ""

        # OneIndia pages can contain
        # an English summary.
        match = re.search(
            r"English summary\s*(.*?)(?:"
            r"\s+(?:Read Full Story|Tags|Related|Comments)"
            r"|$)",
            body,
            re.I,
        )

        if match:

            english_summary = clean_text(
                match.group(1)
            )

        image = (
            meta.get("og:image")
            or meta.get("twitter:image")
            or meta.get("twitter:image:src")
            or ""
        )

        return {
            "title": title,
            "description": clean_text(
                meta.get("description")
                or meta.get("og:description")
                or ""
            ),
            "english": english_summary,
            "image": image,
            "body": body,
        }

    except Exception as error:

        print(
            "Page fetch error:",
            error
        )

        return {
            "title": "",
            "description": "",
            "english": "",
            "image": "",
            "body": "",
        }


# ============================================================
# RSS HELPERS
# ============================================================

def child_text(parent, names):

    for child in list(parent):

        tag = child.tag.rsplit(
            "}",
            1
        )[-1].lower()

        if tag in names:

            return clean_text(
                child.text or ""
            )

    return ""


def child_attr(
    parent,
    names,
    attr
):

    for child in list(parent):

        tag = child.tag.rsplit(
            "}",
            1
        )[-1].lower()

        if tag in names:

            value = child.attrib.get(
                attr
            )

            if value:
                return value.strip()

    return ""


# ============================================================
# DATE PARSING
# ============================================================

def parse_date(value):

    if not value:
        return None

    try:

        dt = parsedate_to_datetime(
            value
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

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:

        try:

            dt = datetime.strptime(
                value.strip(),
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
            continue

    return None


# ============================================================
# RSS FEED PARSER
# ============================================================

def parse_feed(
    url,
    language
):

    try:

        root = ET.fromstring(
            request(url)
        )

    except Exception as error:

        print(
            "Feed error:",
            url,
            error
        )

        return []

    items = []

    for node in root.iter():

        tag = node.tag.rsplit(
            "}",
            1
        )[-1].lower()

        if tag not in (
            "item",
            "entry",
        ):
            continue

        title = child_text(
            node,
            {"title"}
        )

        link = child_text(
            node,
            {"link"}
        )

        if not link:

            link = child_attr(
                node,
                {"link"},
                "href"
            )

        description = child_text(
            node,
            {
                "description",
                "summary",
                "content",
            }
        )

        pub = child_text(
            node,
            {
                "pubdate",
                "published",
                "updated",
                "date",
            }
        )

        image = ""

        for child in list(node):

            child_tag = child.tag.rsplit(
                "}",
                1
            )[-1].lower()

            if child_tag in (
                "enclosure",
                "content",
                "thumbnail",
            ):

                content_type = (
                    child.attrib.get(
                        "type"
                    )
                    or ""
                ).lower()

                image_url = (
                    child.attrib.get(
                        "url"
                    )
                    or child.attrib.get(
                        "href"
                    )
                    or ""
                )

                if image_url and (
                    "image" in content_type
                    or child_tag != "content"
                ):

                    image = image_url
                    break

        if title and link:

            items.append(
                {
                    "title": title,
                    "url": link,
                    "description": clean_text(
                        description
                    ),
                    "published": parse_date(
                        pub
                    ),
                    "image": image,
                    "language": language,
                }
            )

        if len(items) >= MAX_ITEMS_PER_FEED:
            break

    return items


# ============================================================
# TEXT COMBINATION
# ============================================================

def combined_text(
    item,
    page=None
):

    parts = [
        item.get(
            "title",
            ""
        ),
        item.get(
            "description",
            ""
        ),
    ]

    if page:

        parts.extend(
            [
                page.get(
                    "title",
                    ""
                ),
                page.get(
                    "description",
                    ""
                ),
                page.get(
                    "english",
                    ""
                ),
            ]
        )

    return clean_text(
        " ".join(parts)
    )


# ============================================================
# STORY FILTER
# ============================================================

def is_candidate(
    item,
    page=None
):

    text = combined_text(
        item,
        page
    ).lower()

    # Remove unwanted adult content.
    if any(
        re.search(
            pattern,
            text,
            re.I
        )
        for pattern in ADULT_PATTERNS
    ):
        return False

    # Reject listicles.
    if any(
        re.search(
            pattern,
            text,
            re.I
        )
        for pattern in LISTICLE_PATTERNS
    ):
        return False

    # Reject irrelevant movie news.
    if any(
        re.search(
            pattern,
            text,
            re.I
        )
        for pattern in BAD_PATTERNS
    ):
        return False

    positive = any(
        re.search(
            pattern,
            text,
            re.I
        )
        for pattern in POSITIVE_PATTERNS
    )

    has_ott_word = any(
        word in text
        for word in OTT_WORDS
    )

    return positive or has_ott_word


# ============================================================
# PLATFORM DETECTION
# ============================================================

def find_platform(text):

    low = text.lower()

    for display, variants in PLATFORMS:

        for variant in variants:

            pattern = (
                r"(?<![a-z0-9])"
                + re.escape(variant)
                + r"(?![a-z0-9])"
            )

            if re.search(
                pattern,
                low
            ):

                return display

    return ""


# ============================================================
# ORDINAL CLEANUP
# ============================================================

def strip_ordinal(value):

    return re.sub(
        r"(\d{1,2})(st|nd|rd|th)",
        r"\1",
        value,
        flags=re.I,
    )


# ============================================================
# RELEASE DATE
# ============================================================

def parse_release_date(
    text,
    published
):

    text = strip_ordinal(
        text
    )

    # --------------------------------------------------------
    # Explicit year
    # --------------------------------------------------------

    patterns = [

        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(20\d{2})"
        r"\b",

        r"\b"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+"
        r"(20\d{2})"
        r"\b",

        r"\b"
        r"(\d{1,2})[/-]"
        r"(\d{1,2})[/-]"
        r"(20\d{2})"
        r"\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        try:

            if match.group(
                2
            ).lower() in MONTHS:

                day = int(
                    match.group(1)
                )

                month = MONTHS[
                    match.group(2).lower()
                ]

                year = int(
                    match.group(3)
                )

            elif match.group(
                1
            ).lower() in MONTHS:

                month = MONTHS[
                    match.group(1).lower()
                ]

                day = int(
                    match.group(2)
                )

                year = int(
                    match.group(3)
                )

            else:

                day = int(
                    match.group(1)
                )

                month = int(
                    match.group(2)
                )

                year = int(
                    match.group(3)
                )

            return datetime(
                year,
                month,
                day
            ).date()

        except Exception:
            continue

    # --------------------------------------------------------
    # NO YEAR
    #
    # IMPORTANT:
    # Use the article publication year.
    # NOT the current year.
    # --------------------------------------------------------

    no_year_patterns = [

        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\b",

        r"\b"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})"
        r"\b",
    ]

    if published:

        base_year = published.year

    else:

        base_year = datetime.now(
            timezone.utc
        ).year

    for pattern in no_year_patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        try:

            if match.group(
                2
            ).lower() in MONTHS:

                day = int(
                    match.group(1)
                )

                month = MONTHS[
                    match.group(2).lower()
                ]

            else:

                month = MONTHS[
                    match.group(1).lower()
                ]

                day = int(
                    match.group(2)
                )

            # IMPORTANT:
            # Keep article year.
            return datetime(
                base_year,
                month,
                day
            ).date()

        except Exception:
            continue

    return None


# ============================================================
# STORY STATUS
# ============================================================

def story_status(
    text,
    release_date,
    today
):

    low = text.lower()

    if any(
        re.search(
            pattern,
            low,
            re.I
        )
        for pattern in NOW_PATTERNS
    ):
        return "now"

    if (
        release_date
        and release_date <= today
        and re.search(
            r"\b(ott|streaming|available|released|premiere)\b",
            low,
            re.I,
        )
    ):

        old_announcement_words = [
            "announced",
            "confirmed",
            "expected",
            "set to",
            "will be",
        ]

        if not any(
            word in low
            for word in old_announcement_words
        ):
            return "now"

    return "announced"


# ============================================================
# MOVIE TITLE EXTRACTION
# ============================================================

def extract_movie_title(
    item,
    page
):

    sources = [
        page.get(
            "english",
            ""
        ),
        page.get(
            "description",
            ""
        ),
        page.get(
            "title",
            ""
        ),
        item.get(
            "title",
            ""
        ),
    ]

    combined = " ".join(
        source
        for source in sources
        if source
    )

    patterns = [

        r"(?:the\s+)?"
        r"(?:Tamil|Malayalam)\s+"
        r"(?:film|movie)\s+"
        r"([A-Z][A-Za-z0-9'&:+.\- ]{1,80}?)"
        r"(?:,|\s+is\s+|\s+will\s+|\s+was\s+|\s+has\s+|\s+on\s+|\s+from\s+)",

        r"(?:movie|film)\s+"
        r"([A-Z][A-Za-z0-9'&:+.\- ]{1,80}?)"
        r"(?:\s+(?:OTT|release|is|will|was|has|on|from)\b|,|$)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            combined,
            re.I
        )

        if not match:
            continue

        title = clean_text(
            match.group(1)
        ).strip(
            " .:-"
        )

        if (
            1 < len(
                title.split()
            ) <= 12
            and not re.search(
                r"\b(ott|release|confirmed|streaming|date)\b",
                title,
                re.I,
            )
        ):

            return title

    for source in sources:

        for match in re.finditer(
            r"['\"]"
            r"([A-Za-z][A-Za-z0-9'&:+.\- ]{1,80})"
            r"['\"]",
            source,
        ):

            candidate = clean_text(
                match.group(1)
            ).strip()

            if (
                1 < len(
                    candidate.split()
                ) <= 10
                and not re.search(
                    r"\b(OTT|release|streaming|available|confirmed)\b",
                    candidate,
                    re.I,
                )
            ):

                return candidate

    try:

        parsed = urllib.parse.urlparse(
            item["url"]
        )

        slug = (
            parsed.path
            .rstrip("/")
            .split("/")[-1]
        )

        slug = re.sub(
            r"-\d+$",
            "",
            slug
        )

        slug = re.sub(
            r"-(ott|release|date|confirmed|official|streaming|premiere|from|on)-.*$",
            "",
            slug,
            flags=re.I,
        )

        words = re.split(
            r"[-_]+",
            slug
        )

        words = [
            word
            for word in words
            if word
            and not word.isdigit()
        ]

        if words:

            title = " ".join(
                word.capitalize()
                for word in words[:8]
            )

            if len(title) >= 3:
                return title

    except Exception:
        pass

    return ""


# ============================================================
# STATE
# ============================================================

def load_state():

    default = {
        "announcements": {},
        "posted_urls": [],
        "posted_now": [],
    }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

        for key, value in default.items():

            data.setdefault(
                key,
                value
            )

        return data

    except Exception:

        return default


def save_state(state):

    state["posted_urls"] = (
        state.get(
            "posted_urls",
            []
        )[-500:]
    )

    state["posted_now"] = (
        state.get(
            "posted_now",
            []
        )[-500:]
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


# ============================================================
# MOVIE KEY
# ============================================================

def movie_key(title):

    key = title_key(
        title
    )

    if key:
        return key

    return hashlib.sha1(
        norm(title).encode()
    ).hexdigest()[:16]


def find_existing_announcement(
    state,
    title
):

    key = movie_key(
        title
    )

    if key in state[
        "announcements"
    ]:

        return (
            key,
            state[
                "announcements"
            ][key],
        )

    for existing_key, record in (
        state[
            "announcements"
        ].items()
    ):

        if similarity(
            title,
            record.get(
                "title",
                ""
            )
        ) >= SIMILARITY_THRESHOLD:

            return (
                existing_key,
                record,
            )

    return (
        key,
        None
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_call(
    method,
    payload
):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/"
        f"{method}"
    )

    data = urllib.parse.urlencode(
        payload
    ).encode()

    request_obj = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent":
                "OTTNewsBot/1.0"
        },
    )

    try:

        raw = urllib.request.urlopen(
            request_obj,
            timeout=REQUEST_TIMEOUT
        ).read()

        result = json.loads(
            raw.decode()
        )

        if not result.get(
            "ok"
        ):

            print(
                "Telegram error:",
                result
            )

        return result.get(
            "ok",
            False
        )

    except Exception as error:

        print(
            "Telegram request error:",
            error
        )

        return False


def send_post(
    caption,
    image=""
):

    if image:

        success = telegram_call(
            "sendPhoto",
            {
                "chat_id": CHANNEL,
                "photo": image,
                "caption": caption,
                "parse_mode": "HTML",
            },
        )

        if success:
            return True

    return telegram_call(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


# ============================================================
# CAPTIONS
# ============================================================

def format_date(date_value):

    return (
        f"{date_value.day} "
        f"{date_value.strftime('%B %Y')}"
    )


def announcement_caption(
    title,
    platform,
    release_date,
    language
):

    language_label = ""

    if language in (
        "Malayalam",
        "Tamil",
    ):

        language_label = (
            f" ({language})"
        )

    return (
        "🎬 <b>OTT Release Announced</b>\n\n"
        f"<b>{html.escape(title)}</b>"
        f"{language_label} will be available on "
        f"<b>{html.escape(platform)}</b> "
        f"from <b>{format_date(release_date)}</b>."
    )


def now_caption(
    title,
    platform,
    language
):

    language_label = ""

    if language in (
        "Malayalam",
        "Tamil",
    ):

        language_label = (
            f" ({language})"
        )

    return (
        "🎬 <b>Now Streaming</b>\n\n"
        f"<b>{html.escape(title)}</b>"
        f"{language_label} is now available on "
        f"<b>{html.escape(platform)}</b>."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise SystemExit(
            "Missing BOT_TOKEN secret"
        )

    if not CHANNEL:

        raise SystemExit(
            "Missing MOVIE_CHANNEL secret"
        )

    state = load_state()

    # Make sure the state file exists.
    save_state(state)

    now = datetime.now(
        timezone.utc
    )

    today = now.date()

    cutoff = (
        now
        - timedelta(
            days=LOOKBACK_DAYS
        )
    )

    # ========================================================
    # READ ALL FEEDS
    # ========================================================

    all_items = []

    for language, feed in FEEDS:

        items = parse_feed(
            feed,
            language
        )

        for item in items:

            published = item.get(
                "published"
            )

            if (
                published
                and published < cutoff
            ):
                continue

            all_items.append(
                item
            )

    all_items.sort(
        key=lambda item: (
            item.get(
                "published"
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),
            item.get(
                "url",
                ""
            ),
        ),
        reverse=True,
    )

    # ========================================================
    # FIND POSSIBLE OTT STORIES
    # ========================================================

    candidates = []

    seen_urls = set()

    for item in all_items:

        url = item["url"]

        if url in seen_urls:
            continue

        if url in state[
            "posted_urls"
        ]:
            continue

        seen_urls.add(
            url
        )

        text = combined_text(
            item
        ).lower()

        has_positive = any(
            re.search(
                pattern,
                text,
                re.I
            )
            for pattern in POSITIVE_PATTERNS
        )

        has_ott = any(
            word in text
            for word in OTT_WORDS
        )

        if not (
            has_positive
            or has_ott
        ):
            continue

        candidates.append(
            item
        )

        if len(candidates) >= (
            MAX_CANDIDATES_TO_FETCH
        ):
            break

    posts = 0

    # ========================================================
    # PROCESS STORIES
    # ========================================================

    for item in candidates:

        page = fetch_page_data(
            item["url"]
        )

        text = combined_text(
            item,
            page
        )

        if not is_candidate(
            item,
            page
        ):

            state[
                "posted_urls"
            ].append(
                item["url"]
            )

            continue

        platform = find_platform(
            text
        )

        release_date = parse_release_date(
            text,
            item.get(
                "published"
            )
        )

        title = extract_movie_title(
            item,
            page
        )

        # Don't guess.
        if not platform or not title:

            print(
                "Skipping uncertain story:",
                item["title"]
            )

            continue

        key, existing = (
            find_existing_announcement(
                state,
                title
            )
        )

        status = story_status(
            text,
            release_date,
            today
        )

        image = (
            item.get(
                "image"
            )
            or page.get(
                "image",
                ""
            )
        )

        # ====================================================
        # NOW STREAMING
        # ====================================================

        if (
            status == "now"
            or (
                existing
                and existing.get(
                    "release_date"
                ) == str(today)
            )
        ):

            release_key = (
                f"{key}|"
                f"{platform}|"
                f"{today}"
            )

            if release_key not in (
                state[
                    "posted_now"
                ]
            ):

                if posts >= (
                    MAX_POSTS_PER_RUN
                ):
                    break

                success = send_post(
                    now_caption(
                        title,
                        platform,
                        item[
                            "language"
                        ]
                    ),
                    image,
                )

                if success:

                    state[
                        "posted_now"
                    ].append(
                        release_key
                    )

                    posts += 1

                    print(
                        "Posted now:",
                        title
                    )

            state[
                "posted_urls"
            ].append(
                item["url"]
            )

            continue

        # ====================================================
        # ANNOUNCEMENT
        # ====================================================

        if not release_date:

            print(
                "No release date:",
                title
            )

            continue

        # Don't post old announcements.
        if release_date <= today:

            state[
                "posted_urls"
            ].append(
                item["url"]
            )

            continue

        # ====================================================
        # SAME MOVIE ALREADY KNOWN
        # ====================================================

        if existing:

            old_date = existing.get(
                "release_date"
            )

            old_platform = existing.get(
                "platform"
            )

            # Same movie from another feed.
            if (
                old_date != str(
                    release_date
                )
                or old_platform != platform
            ):

                existing.update(
                    {
                        "title": title,
                        "platform": platform,
                        "release_date": str(
                            release_date
                        ),
                        "language": item[
                            "language"
                        ],
                        "updated_at": now.isoformat(),
                    }
                )

                print(
                    "Updated existing movie:",
                    title,
                    release_date
                )

            state[
                "posted_urls"
            ].append(
                item["url"]
            )

            continue

        # ====================================================
        # NEW ANNOUNCEMENT
        # ====================================================

        if posts >= (
            MAX_POSTS_PER_RUN
        ):
            break

        success = send_post(
            announcement_caption(
                title,
                platform,
                release_date,
                item["language"]
            ),
            image,
        )

        if success:

            state[
                "announcements"
            ][key] = {

                "title": title,

                "platform": platform,

                "release_date": str(
                    release_date
                ),

                "language": item[
                    "language"
                ],

                "source_url": item[
                    "url"
                ],

                "created_at": now.isoformat(),
            }

            state[
                "posted_urls"
            ].append(
                item["url"]
            )

            posts += 1

            print(
                "Posted announcement:",
                title,
                release_date
            )

    # ========================================================
    # RELEASE-DAY REMINDERS
    # ========================================================

    if posts < MAX_POSTS_PER_RUN:

        for key, record in list(
            state[
                "announcements"
            ].items()
        ):

            if posts >= (
                MAX_POSTS_PER_RUN
            ):
                break

            try:

                release_date = datetime.strptime(
                    record[
                        "release_date"
                    ],
                    "%Y-%m-%d"
                ).date()

            except Exception:

                continue

            release_key = (
                f"{key}|"
                f"{record.get('platform', '')}|"
                f"{release_date}"
            )

            if (
                release_date == today
                and release_key
                not in state[
                    "posted_now"
                ]
            ):

                success = send_post(
                    now_caption(
                        record[
                            "title"
                        ],
                        record[
                            "platform"
                        ],
                        record.get(
                            "language",
                            ""
                        ),
                    )
                )

                if success:

                    state[
                        "posted_now"
                    ].append(
                        release_key
                    )

                    record[
                        "released_posted"
                    ] = True

                    posts += 1

                    print(
                        "Posted scheduled now:",
                        record[
                            "title"
                        ]
                    )

    # ========================================================
    # SAVE
    # ========================================================

    save_state(
        state
    )

    print(
        "Finished. Posts this run:",
        posts
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
