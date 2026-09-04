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
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

FEEDS = [
    "https://www.animenewsnetwork.com/rss.xml",
    "https://www.otakunews.com/Rss",
    "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
]

DATA_FILE = Path("posted.json")

# Maximum number of posts in one GitHub Actions run
MAX_POSTS_PER_RUN = 3


# ============================================================
# ANIME RELEVANCE
# ============================================================

ANIME_PATTERNS = [
    r"\banime\b",
    r"\bmanga\b",
    r"\banime series\b",
    r"\banime film\b",
    r"\banime movie\b",
    r"\banime adaptation\b",
    r"\banimation studio\b",
    r"\banimated series\b",
    r"\banimated film\b",
    r"\bcrunchyroll\b",
]


# ============================================================
# IMPORTANT NEWS SIGNALS
# ============================================================

STRONG_NEWS_PATTERNS = [
    r"\bofficially announced\b",
    r"\bofficial announcement\b",
    r"\bofficially confirmed\b",
    r"\bannounced\b",
    r"\bconfirmed\b",

    r"\brelease date\b",
    r"\brelease date announced\b",
    r"\bpremiere date\b",
    r"\bair date\b",
    r"\bbroadcast date\b",

    r"\bofficial trailer\b",
    r"\bofficial teaser\b",
    r"\bnew trailer\b",
    r"\bnew teaser\b",

    r"\bnew season\b",
    r"\bfinal season\b",
    r"\brenewed\b",
    r"\brenewal\b",

    r"\banime adaptation\b",
    r"\badaptation announced\b",

    r"\bproduction begins\b",
    r"\bproduction started\b",
    r"\bproduction confirmed\b",

    r"\bstreaming release\b",
    r"\bstreaming date\b",
]


# ============================================================
# IMPORTANT EPISODE NEWS
# ============================================================

EPISODE_NEWS_PATTERNS = [
    r"\bepisode\s+\d+\b.*\b(release date|delayed|postponed|rescheduled|cancelled|canceled|schedule|air date)\b",
    r"\bepisodes?\b.*\b(delayed|postponed|rescheduled|cancelled|canceled)\b",
]


# ============================================================
# LOW-VALUE / UNWANTED TITLES
# ============================================================

BAD_TITLE_PATTERNS = [
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
    r"\btheory\b",

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
    r"\bfigures\b",

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
# DESCRIPTION NOISE
# ============================================================

LOW_VALUE_DESCRIPTION_PATTERNS = [
    r"\binterview\b",
    r"\bpodcast\b",
    r"\bfashion\b",
    r"\bcelebrity\b",
    r"\bgossip\b",
    r"\breaction\b",
    r"\bfan theory\b",
    r"\bmerchandise\b",
    r"\bcosplay\b",
    r"\bvideo game\b",
    r"\bmobile game\b",
]


# ============================================================
# SOURCE RELIABILITY
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
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def matches_any(text, patterns):
    text = text.lower()

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    # Remove common tracking parameters
    url = re.sub(
        r"([?&])(utm_[^=&]+|fbclid|gclid)=[^&]*",
        r"\1",
        url,
        flags=re.IGNORECASE,
    )

    url = re.sub(r"[?&]+$", "", url)

    return url


def normalize_title(title):
    title = clean(title).lower()

    title = re.sub(
        r"[^a-z0-9\s]",
        " ",
        title,
    )

    title = re.sub(
        r"\s+",
        " ",
        title,
    )

    return title.strip()


def title_similarity(title1, title2):
    a = normalize_title(title1)
    b = normalize_title(title2)

    if not a or not b:
        return 0

    return SequenceMatcher(None, a, b).ratio()


def source_weight(url):
    url = url.lower()

    for domain, weight in SOURCE_WEIGHTS.items():
        if domain in url:
            return weight

    return 0


# ============================================================
# RSS / ATOM READER
# ============================================================

def get_feed(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AnimeNewsBot/Final"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.read()


def parse_feed(xml_data):
    root = ET.fromstring(xml_data)

    articles = []

    # ----------------------------
    # RSS
    # ----------------------------

    for item in root.findall(".//item"):

        title = clean(
            item.findtext("title", "")
        )

        link = clean(
            item.findtext("link", "")
        )

        description = clean(
            item.findtext("description", "")
        )

        if title and link:

            articles.append({
                "title": title,
                "link": link,
                "description": description,
            })

    # ----------------------------
    # ATOM
    # ----------------------------

    if not articles:

        namespaces = {
            "atom": "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            namespaces
        ):

            title = clean(
                entry.findtext(
                    "atom:title",
                    "",
                    namespaces
                )
            )

            description = clean(
                entry.findtext(
                    "atom:summary",
                    "",
                    namespaces
                )
            )

            link = ""

            link_element = entry.find(
                "atom:link",
                namespaces
            )

            if link_element is not None:

                link = link_element.attrib.get(
                    "href",
                    ""
                )

            if title and link:

                articles.append({
                    "title": title,
                    "link": link,
                    "description": description,
                })

    return articles


# ============================================================
# ARTICLE SCORING
# ============================================================

def score_article(article):

    title = article["title"]
    description = article["description"]
    link = article["link"]

    full_text = f"{title} {description}"

    # --------------------------------
    # Immediately reject adult content
    # --------------------------------

    if matches_any(
        full_text,
        ADULT_PATTERNS
    ):
        return -100


    # --------------------------------
    # Immediately reject obvious noise
    # --------------------------------

    if matches_any(
        title,
        BAD_TITLE_PATTERNS
    ):
        return -50


    score = 0


    # --------------------------------
    # Anime relevance
    # --------------------------------

    anime_matches = 0

    for pattern in ANIME_PATTERNS:

        if re.search(
            pattern,
            full_text,
            re.IGNORECASE
        ):
            anime_matches += 1


    if anime_matches >= 2:
        score += 6

    elif anime_matches == 1:
        score += 4


    # --------------------------------
    # Strong news signals
    # --------------------------------

    if matches_any(
        title,
        STRONG_NEWS_PATTERNS
    ):
        score += 6

    elif matches_any(
        description,
        STRONG_NEWS_PATTERNS
    ):
        score += 2


    # --------------------------------
    # Important episode changes
    # --------------------------------

    if matches_any(
        title,
        EPISODE_NEWS_PATTERNS
    ):
        score += 6

    elif matches_any(
        description,
        EPISODE_NEWS_PATTERNS
    ):
        score += 2


    # --------------------------------
    # Any season number
    # --------------------------------

    if re.search(
        r"\bseason\s+\d+\b",
        title,
        re.IGNORECASE
    ):
        score += 6

    elif re.search(
        r"\bseason\s+\d+\b",
        description,
        re.IGNORECASE
    ):
        score += 2


    # --------------------------------
    # Official wording
    # --------------------------------

    official_patterns = [
        r"\bofficially\b",
        r"\bofficial announcement\b",
        r"\bofficial trailer\b",
        r"\bofficial teaser\b",
        r"\bconfirmed\b",
        r"\bannounced\b",
    ]

    for pattern in official_patterns:

        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 3


    # --------------------------------
    # Source reliability
    # --------------------------------

    score += source_weight(link)


    # --------------------------------
    # Description noise
    # --------------------------------

    for pattern in LOW_VALUE_DESCRIPTION_PATTERNS:

        if re.search(
            pattern,
            description,
            re.IGNORECASE
        ):
            score -= 1


    # --------------------------------
    # Rumor penalty
    # --------------------------------

    if re.search(
        r"\brumou?r\b",
        description,
        re.IGNORECASE
    ):
        score -= 2


    return score


# ============================================================
# FINAL RELEVANCE CHECK
# ============================================================

def relevant(article):

    title = article["title"]
    description = article["description"]

    full_text = f"{title} {description}"

    # Must actually be related to anime
    if not matches_any(
        full_text,
        ANIME_PATTERNS
    ):
        return False

    # Minimum quality score
    if score_article(article) < 7:
        return False

    return True


# ============================================================
# DUPLICATE CHECK
# ============================================================

def is_duplicate(article, posted):

    article_url = normalize_url(
        article["link"]
    )

    article_title = article["title"]


    for old in posted:

        # New format
        if isinstance(old, dict):

            old_url = normalize_url(
                old.get("url", "")
            )

            old_title = old.get(
                "title",
                ""
            )

        # Compatibility with old posted.json
        else:

            old_url = normalize_url(
                str(old)
            )

            old_title = ""


        # Exact URL
        if (
            article_url
            and article_url == old_url
        ):
            return True


        # Similar headline
        if old_title:

            similarity = title_similarity(
                article_title,
                old_title
            )

            if similarity >= 0.82:
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
        ) as f:

            data = json.load(f)

            if isinstance(data, list):
                return data

    except Exception as e:

        print(
            "Could not read posted.json:",
            e
        )


    return []


def save_posted(posted):

    # Keep the file from growing forever
    posted = posted[-1000:]

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            posted,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    data = json.dumps({
        "chat_id": CHANNEL,
        "text": message,
        "disable_web_page_preview": False,
    }).encode("utf-8")


    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )


    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            return json.loads(
                response.read().decode()
            )


    except urllib.error.HTTPError as e:

        # Telegram rate limit
        if e.code == 429:

            try:

                error_data = json.loads(
                    e.read().decode()
                )

                retry_after = (
                    error_data
                    .get("parameters", {})
                    .get("retry_after", 5)
                )

                time.sleep(
                    retry_after
                )

                return send_telegram(
                    message
                )

            except Exception:
                pass


        print(
            "Telegram error:",
            e
        )

        return None


    except Exception as e:

        print(
            "Telegram connection error:",
            e
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("Starting Anime News Bot...")

    posted = load_posted()

    candidates = []

    seen_urls = set()


    # ========================================================
    # READ ALL FEEDS
    # ========================================================

    for feed_url in FEEDS:

        print(
            "Checking feed:",
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
                "Found",
                len(articles),
                "articles"
            )

        except Exception as e:

            print(
                "Feed error:",
                feed_url,
                e
            )

            continue


        # ====================================================
        # FILTER ARTICLES
        # ====================================================

        for article in articles:

            article["link"] = normalize_url(
                article["link"]
            )


            if not article["link"]:
                continue


            # Same URL during this run
            if article["link"] in seen_urls:
                continue


            seen_urls.add(
                article["link"]
            )


            # Already posted previously
            if is_duplicate(
                article,
                posted
            ):
                continue


            # Quality filter
            if not relevant(article):
                continue


            article["score"] = score_article(
                article
            )


            candidates.append(
                article
            )


    # ========================================================
    # REMOVE SIMILAR STORIES FROM DIFFERENT SOURCES
    # ========================================================

    final_candidates = []


    for article in candidates:

        duplicate = False


        for index, existing in enumerate(
            final_candidates
        ):

            similarity = title_similarity(
                article["title"],
                existing["title"]
            )


            if similarity >= 0.82:

                duplicate = True


                # Keep the stronger article
                if (
                    article["score"]
                    >
                    existing["score"]
                ):

                    final_candidates[index] = (
                        article
                    )


                break


        if not duplicate:

            final_candidates.append(
                article
            )


    # ========================================================
    # BEST NEWS FIRST
    # ========================================================

    final_candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # ========================================================
    # POST
    # ========================================================

    posted_count = 0


    for article in final_candidates:

        if posted_count >= MAX_POSTS_PER_RUN:
            break


        message = (
            "🍿 ANIME NEWS\n\n"
            f"{article['title']}\n\n"
            f"🔗 Source: {article['link']}"
        )


        result = send_telegram(
            message
        )


        if result and result.get("ok"):

            posted.append({
                "url": article["link"],
                "title": article["title"],
            })


            posted_count += 1


            print(
                "POSTED:",
                article["title"],
                "| Score:",
                article["score"]
            )


        else:

            print(
                "FAILED:",
                article["title"]
            )


    # ========================================================
    # SAVE HISTORY
    # ========================================================

    save_posted(
        posted
    )


    print(
        f"Finished. Posted {posted_count} article(s)."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
