import os
import re
import time
from datetime import datetime, timezone, timedelta
import feedparser
from whatsapp_api_client_python import API

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")
IMAGE_URL = os.environ.get("IMAGE_URL", "") 

# Custom footer with a 2-line paragraph space before it
CUSTOM_FOOTER_TEXT = "\n\n\n📌 *Stay informed and have a great week ahead!*"

# RSS Feeds
RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://rss.cnn.com/rss/edition_world.rss"
]

# Filtering rules
EXCLUDED_SPORTS = ["basketball", "nba", "tennis", "golf", "cricket", "nfl", "boxing", "ufc"]
FOOTBALL_KEYWORDS = ["football", "fifa", "world cup", "champions league", "premier league", "soccer"]

# ==========================================
# 2. FILTERING & RELEVANCE ENGINE
# ==========================================
def is_relevant(title, summary):
    """Filters out non-football sports."""
    text = f"{title} {summary}".lower()
    for sport in EXCLUDED_SPORTS:
        if sport in text:
            return False
    if "sport" in text:
        return any(fb in text for fb in FOOTBALL_KEYWORDS)
    return True

def get_headlines():
    articles = []
    seen = set()
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    for feed in RSS_FEEDS:
        data = feedparser.parse(feed)
        for entry in data.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if not title or title in seen:
                continue

            # Parse publication date
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                pub_date = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)
            else:
                pub_date = now

            # Disqualify articles older than 7 days
            if pub_date < seven_days_ago:
                continue

            seen.add(title)
            relevant = is_relevant(title, summary)

            articles.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "relevant": relevant
            })

    if not articles:
        return []

    # Priority ranking logic:
    # 1: Relevant & Recent
    # 2: Less Relevant & Recent
    # 3: Relevant & Older (within 7 days)
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

    # Scale to 12 if enough articles exist, else default to 10
    limit = 12 if len(articles) >= 12 else 10
    return articles[:limit]

# ==========================================
# 3. WHATSAPP DISPATCH ENGINE
# ==========================================
def send_whatsapp():
    articles = get_headlines()
    if not articles:
        print("No articles found within the 7-day window.")
        return

    # Construct the formatted message
    message_lines = [
        "*Today's Biggest Headlines*",
        "",
        "Here are some of the news reports that you shouldn't miss this morning:",
        ""
    ]

    for index, item in enumerate(articles, start=1):
        message_lines.append(f"{index}. *{item['title']}*")
        message_lines.append(f"   {item['link']}\n")

    # Attach footer with two-line paragraph spacing
    full_message = "\n".join(message_lines) + CUSTOM_FOOTER_TEXT

    green_api = API.GreenAPI(INSTANCE_ID, API_TOKEN)

    # Send Image + Text Caption together if IMAGE_URL secret exists
    if IMAGE_URL and IMAGE_URL.strip():
        response = green_api.sending.sendFileByUrl(
            TARGET_CHAT_ID,
            IMAGE_URL.strip(),
            "headline_header.jpg",
            full_message
        )
    else:
        # Fallback to pure text message if no IMAGE_URL secret is provided
        response = green_api.sending.sendMessage(TARGET_CHAT_ID, full_message)

    if response and hasattr(response, 'data') and response.data:
        print("Sent successfully! Message ID:", response.data.get("idMessage"))
    else:
        print("Failed to send message. Verify Green API credentials and TARGET_CHAT_ID format.")

if __name__ == "__main__":
    send_whatsapp()