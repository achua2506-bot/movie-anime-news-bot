import os
import re
import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from html import unescape
from difflib import SequenceMatcher


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

FEEDS = [
    "https://www.animenewsnetwork.com/rss.xml",
    "https://www.otakunews.com/Rss",
    "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
]

DATA_FILE = Path("posted.json")

MAX_POSTS_PER_RUN = 3


# ============================================================
# ANIME SIGNALS
# ============================================================

ANIME_PATTERNS = [
    r"\banime\b",
    r"\bmanga\b",
    r"\banime series\b",
    r"\banime film\b",
    r"\banime movie\b",
    r"\banime adaptation\b",
    r"\banimated series\b",
    r"\banimated film\b",
    r"\banimation studio\b",
    r"\bcrunchyroll\b",
]


# ============================================================
# MAJOR NEWS SIGNALS
# ============================================================

MAJOR_NEWS = [
    r"\bseason\s+\d+\b",
    r"\bnew season\b",
    r"\bfinal season\b",
    r"\bsequel\b",
    r"\bsequel announced\b",
    r"\bsequel confirmed\b",

    r"\brelease date\b",
    r"\bpremiere date\b",
    r"\bair date\b",
    r"\bbroadcast date\b",

    r"\bofficial trailer\b",
    r"\bofficial teaser\b",
    r"\bnew trailer\b",
    r"\bnew teaser\b",

    r"\bofficially announced\b",
    r"\bofficial announcement\b",
    r"\bofficially confirmed\b",

    r"\banime adaptation\b",
    r"\badaptation announced\b",

    r"\bproduction begins\b",
    r"\bproduction started\b",
    r"\bproduction confirmed\b",

    r"\brenewed\b",
    r"\brenewal\b",

    r"\bstreaming release\b",
    r"\bstreaming date\b",

    r"\bdelayed\b",
    r"\bpostponed\b",
    r"\brescheduled\b",
    r"\bcancelled\b",
    r"\bcanceled\b",
]


# ============================================================
# IMPORTANT EPISODE CHANGES
# ============================================================

EPISODE_NEWS = [
    r"\bepisode\s+\d+\b.*\b(release date|delayed|postponed|rescheduled|cancelled|canceled|air date)\b",
    r"\bepisodes?\b.*\b(delayed|postponed|rescheduled|cancelled|canceled)\b",
]


# ============================================================
# BAD / LOW-VALUE CONTENT
# ============================================================

BAD_TITLE = [
    r"\breview\b",
    r"\breviews\b",
    r"\binterview\b",
    r"\bpodcast\b",

    r"\branking\b",
    r"\brankings\b",
    r"\btop\s+\d+\b",
    r"\b\d+\s+(best|worst|greatest|favorite|favourite)\b",
    r"\bbest anime\b",
    r"\bworst anime\b",

    r"\bopinion\b",
    r"\breaction\b",

    r"\bfan theory\b",
    r"\bfan theories\b",

    r"\brumor\b",
    r"\brumour\b",
    r"\brumors\b",
    r"\brumours\b",

    r"\bcelebrity\b",
    r"\bgossip\b",
    r"\bfashion\b",

    r"\bmerchandise\b",
    r"\bcollectible\b",
    r"\bcollectibles\b",
    r"\bfigurine\b",

    r"\bcosplay\b",
    r"\bquiz\b",

    r"\bvideo game\b",
    r"\bmobile game\b",
    r"\bgame news\b",
]


# ============================================================
# ADULT CONTENT
# ============================================================

ADULT_PATTERNS = [
    r"\bhentai\b",
    r"\becchi\b",
    r"\bporn\b",
    r"\bxxx\b",
    r"\berotic\b",
    r"\bexplicit\b",
    r"\badult anime\b",
]


# ============================================================
# SOURCE TRUST
# ============================================================

SOURCE_WEIGHTS = {
    "animenewsnetwork.com": 3,
    "otakunews.com": 2,
    "crunchyroll.com": 3,
}


# ============================================================
# TEXT HELPERS
# ============================================================

def clean(text):
    if not text:
        return ""

    text = unescape(text)

    text = re.sub(
        r"<script.*?</script>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<style.*?</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def matches(text, patterns):
    text = text.lower()

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in patterns
    )


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    url = re.sub(
        r"([?&])(utm_[^=&]+|fbclid|gclid)=[^&]*",
        r"\1",
        url,
        flags=re.IGNORECASE
    )

    url = re.sub(
        r"[?&]+$",
        "",
        url
    )

    return url


def normalize_title(title):
    title = clean(title).lower()

    title = re.sub(
        r"[^a-z0-9\s]",
        " ",
        title
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


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


def source_score(url):
    url = url.lower()

    for domain, score in SOURCE_WEIGHTS.items():

        if domain in url:
            return score

    return 0


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def extract_image(element):

    # RSS enclosure
    enclosure = element.find("enclosure")

    if enclosure is not None:

        image_url = enclosure.attrib.get(
            "url",
            ""
        )

        content_type = enclosure.attrib.get(
            "type",
            ""
        ).lower()

        if (
            image_url
            and "image" in content_type
        ):
            return image_url


    # Media RSS
    for child in list(element):

        tag = child.tag.lower()

        if (
            "thumbnail" in tag
            or "content" in tag
        ):

            url = child.attrib.get(
                "url",
                ""
            )

            if url:
                return url


    # Image inside description
    for field in [
        "description",
        "{http://purl.org/rss/1.0/modules/content/}encoded"
    ]:

        value = element.findtext(
            field,
            ""
        )

        if value:

            match = re.search(
                r'<img[^>]+src=["\']([^"\']+)',
                value,
                re.IGNORECASE
            )

            if match:
                return match.group(1)


    return ""


# ============================================================
# FEED READER
# ============================================================

def get_feed(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 AnimeNewsBot"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.read()


def parse_feed(xml_data):

    root = ET.fromstring(
        xml_data
    )

    articles = []


    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    for item in root.findall(
        ".//item"
    ):

        title = clean(
            item.findtext(
                "title",
                ""
            )
        )

        link = clean(
            item.findtext(
                "link",
                ""
            )
        )

        description = clean(
            item.findtext(
                "description",
                ""
            )
        )

        encoded = clean(
            item.findtext(
                "{http://purl.org/rss/1.0/modules/content/}encoded",
                ""
            )
        )

        description = (
            f"{description} {encoded}"
        ).strip()

        image = extract_image(
            item
        )


        if title and link:

            articles.append({
                "title": title,
                "link": link,
                "description": description,
                "image": image,
            })


    # --------------------------------------------------------
    # ATOM
    # --------------------------------------------------------

    if not articles:

        ns = {
            "atom":
                "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            ns
        ):

            title = clean(
                entry.findtext(
                    "atom:title",
                    "",
                    ns
                )
            )

            description = clean(
                entry.findtext(
                    "atom:summary",
                    "",
                    ns
                )
            )

            link = ""

            for link_element in entry.findall(
                "atom:link",
                ns
            ):

                href = link_element.attrib.get(
                    "href",
                    ""
                )

                rel = link_element.attrib.get(
                    "rel",
                    ""
                )

                if href and (
                    rel == "alternate"
                    or not link
                ):
                    link = href


            if title and link:

                articles.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "image": "",
                })


    return articles


# ============================================================
# ARTICLE SCORING
# ============================================================

def score_article(article):

    title = article["title"]
    description = article["description"]
    link = article["link"]

    text = (
        f"{title} {description}"
    )


    # --------------------------------------------------------
    # Immediate rejection
    # --------------------------------------------------------

    if matches(
        text,
        ADULT_PATTERNS
    ):
        return -100


    if matches(
        title,
        BAD_TITLE
    ):
        return -50


    score = 0


    # --------------------------------------------------------
    # Anime relevance
    # --------------------------------------------------------

    anime_count = 0

    for pattern in ANIME_PATTERNS:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):
            anime_count += 1


    if anime_count >= 2:
        score += 6

    elif anime_count == 1:
        score += 4


    # --------------------------------------------------------
    # Major news
    # --------------------------------------------------------

    if matches(
        title,
        MAJOR_NEWS
    ):
        score += 8

    elif matches(
        description,
        MAJOR_NEWS
    ):
        score += 3


    # --------------------------------------------------------
    # Episode changes
    # --------------------------------------------------------

    if matches(
        title,
        EPISODE_NEWS
    ):
        score += 8

    elif matches(
        description,
        EPISODE_NEWS
    ):
        score += 3


    # --------------------------------------------------------
    # Official confirmation
    # --------------------------------------------------------

    official = [
        r"\bofficially\b",
        r"\bofficial announcement\b",
        r"\bofficial trailer\b",
        r"\bofficial teaser\b",
        r"\bconfirmed\b",
        r"\bannounced\b",
    ]

    for pattern in official:

        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 2


    # --------------------------------------------------------
    # Source reliability
    # --------------------------------------------------------

    score += source_score(
        link
    )


    # --------------------------------------------------------
    # Rumor penalty
    # --------------------------------------------------------

    if re.search(
        r"\brumou?r\b",
        text,
        re.IGNORECASE
    ):
        score -= 5


    return score


# ============================================================
# FINAL DECISION
# ============================================================

def is_worth_posting(article):

    title = article["title"]
    description = article["description"]

    text = (
        f"{title} {description}"
    )


    # Must be anime-related
    if not matches(
        text,
        ANIME_PATTERNS
    ):
        return False


    score = score_article(
        article
    )


    # High-quality news only
    return score >= 10


# ============================================================
# DUPLICATE CHECK
# ============================================================

def is_duplicate(
    article,
    posted
):

    url = normalize_url(
        article["link"]
    )

    title = article["title"]


    for old in posted:

        if isinstance(
            old,
            dict
        ):

            old_url = normalize_url(
                old.get(
                    "url",
                    ""
                )
            )

            old_title = old.get(
                "title",
                ""
            )

        else:

            old_url = normalize_url(
                str(old)
            )

            old_title = ""


        # Exact URL
        if (
            url
            and url == old_url
        ):
            return True


        # Same story, different URL
        if old_title:

            if title_similarity(
                title,
                old_title
            ) >= 0.82:

                return True


    return False


# ============================================================
# STORAGE
# ============================================================

def load_posted():

    if not DATA_FILE.exists():
        return []

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

            if isinstance(
                data,
                list
            ):
                return data

    except Exception as e:

        print(
            "posted.json error:",
            e
        )


    return []


def save_posted(posted):

    posted = posted[-1000:]

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            posted,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_request(
    method,
    data
):

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/{method}"
    )

    body = json.dumps(
        data
    ).encode("utf-8")


    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST"
    )


    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            return json.loads(
                response.read().decode()
            )


    except urllib.error.HTTPError as e:

        if e.code == 429:

            try:

                error_data = json.loads(
                    e.read().decode()
                )

                wait_time = (
                    error_data
                    .get(
                        "parameters",
                        {}
                    )
                    .get(
                        "retry_after",
                        5
                    )
                )

                print(
                    "Telegram rate limit.",
                    "Waiting:",
                    wait_time
                )

                time.sleep(
                    wait_time
                )

                return telegram_request(
                    method,
                    data
                )

            except Exception:
                pass


        print(
            "Telegram HTTP error:",
            e
        )

        return None


    except Exception as e:

        print(
            "Telegram error:",
            e
        )

        return None


# ============================================================
# CREATE POST
# ============================================================

def create_caption(article):

    title = clean(
        article["title"]
    )

    description = clean(
        article["description"]
    )


    # Remove HTML leftovers
    description = re.sub(
        r"\s+",
        " ",
        description
    ).strip()


    # Keep caption short
    if len(description) > 350:

        description = (
            description[:347]
            + "..."
        )


    if description:

        caption = (
            f"📰 {title}\n\n"
            f"{description}"
        )

    else:

        caption = (
            f"📰 {title}"
        )


    # Telegram photo caption limit
    return caption[:1024]


# ============================================================
# SEND PHOTO
# ============================================================

def send_photo(
    image,
    caption
):

    return telegram_request(
        "sendPhoto",
        {
            "chat_id": CHANNEL,
            "photo": image,
            "caption": caption,
        }
    )


# ============================================================
# SEND TEXT FALLBACK
# ============================================================

def send_text(
    caption
):

    return telegram_request(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": caption,
        }
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Starting Anime News Bot..."
    )


    posted = load_posted()

    candidates = []

    seen_urls = set()


    # ========================================================
    # READ FEEDS
    # ========================================================

    for feed_url in FEEDS:

        print(
            "Checking:",
            feed_url
        )


        try:

            xml_data = get_feed(
                feed_url
            )

            articles = parse_feed(
                xml_data
            )

            print(
                "Found:",
                len(articles)
            )


        except Exception as e:

            print(
                "Feed error:",
                e
            )

            continue


        # ====================================================
        # FILTER
        # ====================================================

        for article in articles:

            article["link"] = normalize_url(
                article["link"]
            )


            if not article["link"]:
                continue


            # Same URL in this run
            if article["link"] in seen_urls:
                continue


            seen_urls.add(
                article["link"]
            )


            # Already posted
            if is_duplicate(
                article,
                posted
            ):
           
