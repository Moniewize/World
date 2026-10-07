import os
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse
import feedparser
from whatsapp_api_client_python import API

# ==============================================================================
# 📝 CUSTOM CLOSING TEXT (2-Line Paragraph at the end)
# ==============================================================================
CUSTOM_FOOTER_TEXT = "\n\n*Source:* BBC, DW\n*Brought by*: RAC-FUTO Editorial Team"

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")

# STRICTLY OFFICIAL BROADCASTERS ONLY
RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",      # BBC News World
    "https://rss.dw.com/rdf/rss-en-world",            # Deutsche Welle World
    "http://rss.cnn.com/rss/edition_world.rss"        # CNN World
]

EXCLUDED_SPORTS = ["basketball", "nba", "tennis", "golf", "cricket", "nfl", "boxing", "ufc"]
FOOTBALL_KEYWORDS = ["football", "fifa", "world cup", "champions league", "premier league", "soccer"]

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def clean_link(url):
    """Strips query parameters and tracking paths to leave short, clean links."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

def is_relevant(title, summary):
    """Filters out non-football sports."""
    text = f"{title} {summary}".lower()
    for sport in EXCLUDED_SPORTS:
        if sport in text:
            return False
    if "sport" in text:
        return any(fb in text for fb in FOOTBALL_KEYWORDS)
    return True

# ==============================================================================
# FILTERING & RELEVANCE ENGINE
# ==============================================================================
def get_headlines():
    articles = []
    seen = set()
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    # Set custom User-Agent header so CNN and DW do not block automated requests
    request_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for feed in RSS_FEEDS:
        data = feedparser.parse(feed, request_headers=request_headers)
        for entry in data.entries:
            title = entry.get("title", "").strip()
            raw_link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if not title or title in seen:
                continue

            # Ensure link comes strictly from bbc, dw, or cnn domains
            parsed_domain = urlparse(raw_link).netloc.lower()
            if not any(domain in parsed_domain for domain in ["bbc.com", "bbc.co.uk", "dw.com", "cnn.com"]):
                continue

            # Strict publication date handling: Discard entries missing valid date
            published_parsed = entry.get("published_parsed")
            if not published_parsed:
                continue

            pub_date = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)

            # Strict 7-day recency threshold
            if pub_date < seven_days_ago or pub_date > now:
                continue

            seen.add(title)
            link = clean_link(raw_link)
            relevant = is_relevant(title, summary)

            articles.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "relevant": relevant
            })

    if not articles:
        return []

    # PRIORITY PIPELINE:
    # Rank 1: Relevant & Recent
    # Rank 2: Less Relevant & Recent
    # Rank 3: Relevant & Older (within 7-day window)
    all_timestamps = [a["pub_date"].timestamp() for a in articles]
    mid_point = sum(all_timestamps) / len(all_timestamps)

    def priority_score(article):
        is_rel = article["relevant"]
        is_recent = article["pub_date"].timestamp() >= mid_point
        
        if is_rel and is_recent:
            rank = 1
        elif not is_rel and is_recent:
            rank = 2
        else:
            rank = 3

        return (rank, -article["pub_date"].timestamp())

    articles.sort(key=priority_score)
    limit = 12 if len(articles) >= 12 else 10
    return articles[:limit]

# ==============================================================================
# WHATSAPP DISPATCH ENGINE
# ==============================================================================
def send_whatsapp():
    articles = get_headlines()
    if not articles:
        print("No articles found meeting the recency and source criteria.")
        return

    message_lines = [
        "Here are some of the news reports that you shouldn't miss this morning:",
        ""
    ]

    for index, item in enumerate(articles, start=1):
        message_lines.append(f"{index}. *{item['title']}*")
        message_lines.append(f"   {item['link']}\n")

    full_message = "\n".join(message_lines) + CUSTOM_FOOTER_TEXT

    green_api = API.GreenAPI(INSTANCE_ID, API_TOKEN)
    response = green_api.sending.sendMessage(TARGET_CHAT_ID, full_message)

    if response and hasattr(response, 'data') and response.data:
        print("Message sent successfully! Message ID:", response.data.get("idMessage"))
    else:
        print("Failed to send message. Verify Green API credentials and TARGET_CHAT_ID format.")

if __name__ == "__main__":
    send_whatsapp()