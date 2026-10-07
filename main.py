import os
import re
import time
from datetime import datetime, timezone, timedelta
import feedparser
from whatsapp_api_client_python import API

# ==============================================================================
# 📝 CUSTOM CLOSING TEXT (2-Line Paragraph at the end)
# ==============================================================================
CUSTOM_FOOTER_TEXT = "\n\nBrought to you by my bot.\nStay informed and have a great week!"

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")
import os
import re
import time
from datetime import datetime, timezone, timedelta
import feedparser
import requests
from whatsapp_api_client_python import API

# ==============================================================================
# 📝 CUSTOM CLOSING TEXT (2-Line Paragraph at the end)
# ==============================================================================
CUSTOM_FOOTER_TEXT = "\n\n*Source:* CNN, BBC, etc.\n*Brought by:* RAC-FUTO Ediorial Team"

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")
IMAGE_URL = os.environ.get("IMAGE_URL", "") 

# OFFICIAL & REPUTABLE INTERNATIONAL BROADCASTERS / AGENCIES
RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",             # BBC News
    "http://rss.cnn.com/rss/edition_world.rss",              # CNN
    "https://www.aljazeera.com/xml/rss/all.xml",             # Al Jazeera
    "https://www.npr.org/rss/rss.php?id=1004",               # NPR World
    "https://rss.dw.com/rdf/rss-en-world",                   # Deutsche Welle (DW)
    "https://www.rssfeedurl.com/reuters/worldNews"          # Reuters World
]

EXCLUDED_SPORTS = ["basketball", "nba", "tennis", "golf", "cricket", "nfl", "boxing", "ufc"]
FOOTBALL_KEYWORDS = ["football", "fifa", "world cup",  "international football", "soccer"]

# ==============================================================================
# FILTERING & RELEVANCE ENGINE
# ==============================================================================
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

            # Parse publish date safely
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                pub_date = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)
            else:
                pub_date = now

            # THRESHOLD DISQUALIFICATION: Discard if older than 7 days
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

    # WORKFLOW PRIORITY SORTING ENGINE:
    # 1: Relevant & Recent
    # 2: Less Relevant & Recent
    # 3: Relevant & Older (within 7-day window)
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

        # Primary sort: rank (1 to 3), Secondary sort: newest timestamp first
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
        print("No news articles found within the 7-day window.")
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

    # 1. Send Header Image (if URL provided)
    if IMAGE_URL and IMAGE_URL.strip():
        print(f"Sending header image from: {IMAGE_URL.strip()}")
        img_resp = green_api.sending.sendFileByUrl(
            TARGET_CHAT_ID,
            IMAGE_URL.strip(),
            "headline_header.jpg",
            "*Today's Biggest Headlines*"
        )
        print("Image Dispatch Status:", getattr(img_resp, 'data', img_resp))

    # 2. Send main news text + 2-line custom footer as a single message
    response = green_api.sending.sendMessage(TARGET_CHAT_ID, full_message)

    if response and hasattr(response, 'data') and response.data:
        print("Message sent successfully! Message ID:", response.data.get("idMessage"))
    else:
        print("Failed to dispatch text message. Check Green API credentials and TARGET_CHAT_ID format.")

if __name__ == "__main__":
    send_whatsapp()