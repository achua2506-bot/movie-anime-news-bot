import os
import re
import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from html import unescape


# ============================================================
# SETTINGS
# ============================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

FEEDS = [
    "https://www.animenewsnetwork.com/rss.xml",
    "https://www.otakunews.com/Rss",
    "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
]

DATA_FILE = Path("posted.json")

# Maximum posts during one GitHub Actions run
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
    r"\banimation studio\b",
    r"\banimated series\b",
    r"\banimated film\b",
    r"\bcrunchyroll\b",
]


# ============================================================
# STRONG NEWS
# ============================================================

STRONG_NEWS_PATTERNS = [
    r"\bofficially announced\b",
    r"\bofficial announcement\b",
    r"\bannounced\b",
    r"\bconfirmed\b",
    r"\bofficially confirmed\b",

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
    r"\bepisode\s+\d+\s+release date\b",
    r"\bepisode\s+\d+\s+delayed\b",
    r"\bepisode\s+\d+\s+postponed\b",
    r"\bepisode\s+\d+\s+rescheduled\b",
    r"\bepisode\s+\d+\s+cancelled\b",
    r"\bepisode\s+\d+\s+canceled\b",
    r"\bepisode\s+\d+\s+schedule\b",
    r"\bepisode\s+\d+\s+air date\b",

    r"\bepisodes?\s+delayed\b",
    r"\bepisodes?\s+postponed\b",
    r"\bepisodes?\s+rescheduled\b",
    r"\bepisodes?\s+cancelled\b",
    r"\bepisodes?\s+canceled\b",
]


# ============================================================
# UNWANTED TITLE CONTENT
# ============================================================

BAD_TITLE_PATTERNS = [
    # Reviews / interviews
    r"\breview\b",
    r"\binterview\b",
    r"\bpodcast\b",

    # Rankings and listicles
    r"\branking\b",
    r"\brankings\b",
    r"\btop\s+\d+\b",
    r"\b\d+\s+(?:best|worst|greatest|favorite|favourite)\b",
    r"\bbest\s+anime\b",
    r"\bworst\s+anime\b",

    # Opinions / reactions
    r"\bopinion\b",
    r"\breaction\b",
    r"\bfan theory\b",
    r"\bfan theories\b",
    r"\btheory\b",

    # Rumours
    r"\brumor\b",
    r"\brumour\b",
    r"\brumors\b",
    r"\brumours\b",

    # Entertainment noise
    r"\bcelebrity\b",
    r"\bgossip\b",
    r"\bfashion\b",

    # Merchandise
    r"\bmerchandise\b",
    r"\bcollectible\b",
    r"\bcollectibles\b",
    r"\bfigurine\b",
    r"\bfigures?\b",

    # Cosplay / quizzes
    r"\bcosplay\b",
    r"\bquiz\b",

    # Games
    r"\bvideo game\b",
    r"\bmobile game\b",
    r"\bgame news\b",
]


# ============================================================
# INAPPROPRIATE CONTENT
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
# TEXT HELPERS
# ============================================================

def clean(text):
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def matches_any(text, patterns):
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


# ============================================================
# GET FEED
# ============================================================

def get_feed(url):
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MovieAnimeNewsBot/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:
            return response.read()

    except Exception as error:
        print(f"Feed error: {url} -> {error}")
        return b""


# ============================================================
# PARSE RSS / ATOM
# ============================================================

def parse_feed(data):

    if not data:
        return []

    try:
        root = ET.fromstring(data)
    except Exception as error:
        print(f"XML error: {error}")
        return []

    results = []

    # RSS
    for item in root.findall(".//item"):

        title = item.findtext(
            "title",
            ""
        ).strip()

        link = item.findtext(
            "link",
            ""
        ).strip()

        description = item.findtext(
            "description",
            ""
        ).strip()

        if title and link:

            results.append({
                "title": title,
                "link": link,
                "description": description
            })

    # Atom
    if not results:

        namespace = {
            "atom":
            "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            namespace
        ):

            title = entry.findtext(
                "atom:title",
                "",
                namespace
            ).strip()

            description = entry.findtext(
                "atom:summary",
                "",
                namespace
            ).strip()

            link = ""

            link_element = entry.find(
                "atom:link",
                namespace
            )

            if link_element is not None:
                link = link_element.attrib.get(
                    "href",
                    ""
                ).strip()

            if title and link:

                results.append({
                    "title": title,
                    "link": link,
                    "description": description
                })

    return results


# ============================================================
# NORMALIZE URL
# ============================================================

def normalize_url(url):

    url = url.strip()

    # Remove common tracking parameters
    url = re.sub(
        r"[?&](utm_[^&]+|fbclid|gclid)=[^&]*",
        "",
        url,
        flags=re.IGNORECASE
    )

    return url.rstrip("?&")


# ============================================================
# SCORE ARTICLE
# ============================================================

def score_article(item):

    title = clean(
        item["title"]
    ).lower()

    description = clean(
        item["description"]
    ).lower()

    text = title + " " + description


    # --------------------------------------------------------
    # Immediate inappropriate-content rejection
    # --------------------------------------------------------

    if matches_any(
        text,
        ADULT_PATTERNS
    ):
        return -100


    # --------------------------------------------------------
    # Immediate obvious-noise rejection
    # --------------------------------------------------------

    if matches_any(
        title,
        BAD_TITLE_PATTERNS
    ):
        return -50


    score = 0


    # --------------------------------------------------------
    # Anime relevance
    # --------------------------------------------------------

    anime_hits = sum(
        1
        for pattern in ANIME_PATTERNS
        if re.search(
            pattern,
            text,
            re.IGNORECASE
        )
    )

    if anime_hits >= 1:
        score += 4

    if anime_hits >= 2:
        score += 2


    # --------------------------------------------------------
    # Strong news signals
    # --------------------------------------------------------

    for pattern in STRONG_NEWS_PATTERNS:

        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 6

        elif re.search(
            pattern,
            description,
            re.IGNORECASE
        ):
            score += 2


    # --------------------------------------------------------
    # Important episode news
    # --------------------------------------------------------

    for pattern in EPISODE_NEWS_PATTERNS:

        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 6

        elif re.search(
            pattern,
            description,
            re.IGNORECASE
        ):
            score += 2


    # --------------------------------------------------------
    # ANY season number
    #
    # Season 1
    # Season 2
    # Season 6
    # Season 10
    # Season 100
    #
    # No fixed list.
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Official wording
    # --------------------------------------------------------

    official_words = [
        "officially",
        "official announcement",
        "official trailer",
        "official teaser",
        "confirmed",
        "announced",
    ]

    for word in official_words:

        if word in title:
            score += 3


    # --------------------------------------------------------
    # IMPORTANT:
    #
    # NO GENERAL CAST / VOICE ACTOR BONUS.
    #
    # We deliberately removed it to reduce noise.
    # --------------------------------------------------------


    # --------------------------------------------------------
    # Soft description penalties
    #
    # These don't automatically reject the article because
    # the description may mention unrelated material.
    # --------------------------------------------------------

    soft_bad_words = [
        "interview",
        "podcast",
        "fashion",
        "celebrity",
        "gossip",
        "reaction",
        "fan theory",
        "merchandise",
        "cosplay",
        "video game",
        "mobile game",
    ]

    for word in soft_bad_words:

        if word in description:
            score -= 1


    # --------------------------------------------------------
    # Rumour penalty in description
    # --------------------------------------------------------

    rumour_words = [
        "rumor",
        "rumour",
        "rumors",
        "rumours",
    ]

    for word in rumour_words:

        if word in description:
            score -= 2


    return score


# ============================================================
# FINAL FILTER
# ============================================================

def relevant(item):

    title = clean(
        item["title"]
    ).lower()

    description = clean(
        item["description"]
    ).lower()

    text = title + " " + description

    score = score_article(item)

    print(
        f"SCORE {score}: {item['title']}"
    )


    # Must actually be anime-related
    if not any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in ANIME_PATTERNS
    ):
        return False


    # Minimum quality threshold
    if score < 7:
        return False


    return True


# ============================================================
# LOAD POSTED LINKS
# ============================================================

def load_posted():

    if DATA_FILE.exists():

        try:
            return set(
                json.loads(
                    DATA_FILE.read_text()
                )
            )

        except Exception as error:
            print(
                f"posted.json error: {error}"
            )

    return set()


# ============================================================
# SAVE POSTED LINKS
# ============================================================

def save_posted(posted):

    DATA_FILE.write_text(
        json.dumps(
            list(posted)[-1000:],
            indent=2
        )
    )


# ============================================================
# SEND TELEGRAM
# ============================================================

def send_telegram(text):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = json.dumps({
        "chat_id": CHANNEL,
        "text": text,
        "disable_web_page_preview": False
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type":
            "application/json"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:
            response.read()

        time.sleep(3)

    except urllib.error.HTTPError as error:

        if error.code == 429:

            retry_after = 10

            try:

                data = json.loads(
                    error.read().decode()
                )

                retry_after = data.get(
                    "parameters",
                    {}
                ).get(
                    "retry_after",
                    10
                )

            except Exception:
                pass

            print(
                "Telegram rate limit. "
                f"Waiting {retry_after} seconds..."
            )

            time.sleep(retry_after)

            with urllib.request.urlopen(
                request,
                timeout=20
            ) as response:
                response.read()

            time.sleep(3)

        else:
            raise


# ============================================================
# MAIN
# ============================================================

def main():

    posted = load_posted()

    candidates = []

    seen_this_run = set()


    # --------------------------------------------------------
    # READ FEEDS
    # --------------------------------------------------------

    for feed in FEEDS:

        print(
            f"\nChecking feed: {feed}"
        )

        data = get_feed(feed)

        items = parse_feed(data)


        for item in items:

            item["link"] = normalize_url(
                item["link"]
            )


            # Skip already-posted articles
            if item["link"] in posted:
                continue


            # Skip duplicates within this run
            if item["link"] in seen_this_run:
                continue


            if relevant(item):

                candidates.append(item)

                seen_this_run.add(
                    item["link"]
                )


    # --------------------------------------------------------
    # HIGHEST SCORE FIRST
    # --------------------------------------------------------

    candidates.sort(
        key=lambda item: score_article(item),
        reverse=True
    )


    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

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


        print(
            f"POSTING: {item['title']}"
        )


        send_telegram(message)


        posted.add(
            item["link"]
        )

        posted_this_run += 1


    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_posted(posted)


    print(
        f"\nFinished. "
        f"Posted {posted_this_run} articles."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
