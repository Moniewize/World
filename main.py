import os
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse
import feedparser
import requests
from whatsapp_api_client_python import API

# ==============================================================================
# 📝 CONFIGURATION & ASSETS
# ==============================================================================
CUSTOM_FOOTER_TEXT = "\n\n*Source:* BBC, DW, CNN\n*Brought by*: RAC-FUTO Editorial Team"

# Path to the image file uploaded in your GitHub repository workspace
IMAGE_PATH = "banner.jpg"  # <-- Change this to match your exact uploaded filename (e.g., image.png)

# Green API credentials (WhatsApp)
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")

# Telegram credentials
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

            parsed_domain = urlparse(raw_link).netloc.lower()
            if not any(domain in parsed_domain for domain in ["bbc.com", "bbc.co.uk", "dw.com", "cnn.com"]):
                continue

            published_parsed = entry.get("published_parsed")
            if not published_parsed:
                continue

            pub_date = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)

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
# WHATSAPP DISPATCH ENGINE (WITH IMAGE SUPPORT)
# ==============================================================================
def send_whatsapp_briefing(message):
    """Sends the briefing with the repository image via Green API."""
    if not INSTANCE_ID or not API_TOKEN or not TARGET_CHAT_ID:
        print("⚠️ Skipping WhatsApp: Missing Green API environment variables.")
        return

    try:
        green_api = API.GreenAPI(INSTANCE_ID, API_TOKEN)
        
        if os.path.exists(IMAGE_PATH):
            # Sends image with caption text using Green API SDK
            response = green_api.sending.sendFileByUpload(TARGET_CHAT_ID, IMAGE_PATH, os.path.basename(IMAGE_PATH), message)
        else:
            # Fallback to text message if image file is missing
            response = green_api.sending.sendMessage(TARGET_CHAT_ID, message)

        if response and hasattr(response, 'data') and response.data:
            print("✅ WhatsApp briefing successfully delivered!")
        else:
            print("⚠️ WhatsApp dispatch returned unexpected response.")
    except Exception as e:
        print(f"❌ WhatsApp dispatch failed: {e}")

# ==============================================================================
# TELEGRAM DISPATCH ENGINE (WITH IMAGE SUPPORT)
# ==============================================================================
def send_telegram_briefing(message):
    """Sends the briefing with the repository image via Telegram Bot API."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Skipping Telegram: Missing Telegram environment variables.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        
        if os.path.exists(IMAGE_PATH):
            with open(IMAGE_PATH, "rb") as img_file:
                files = {"photo": img_file}
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": message,
                    "parse_mode": "Markdown"
                }
                response = requests.post(url, data=payload, files=files, timeout=30)
        else:
            # Fallback to text-only send if image is missing
            text_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            }
            response = requests.post(text_url, json=payload, timeout=20)

        response.raise_for_status()
        print("✅ Telegram briefing successfully delivered!")
    except Exception as e:
        print(f"❌ Telegram dispatch failed: {e}")

# ==============================================================================
# SCRIPT EXECUTION
# ==============================================================================
if __name__ == "__main__":
    articles = get_headlines()
    if not articles:
        print("No articles found meeting the recency and source criteria.")
    else:
        message_lines = [
            "Here are some of the news reports that you shouldn't miss this morning:",
            ""
        ]

        for index, item in enumerate(articles, start=1):
            # Safe title formatting for group parsers
            safe_title = item['title'].replace('*', '').replace('_', '').replace('`', '')
            message_lines.append(f"{index}. *{safe_title}*")
            message_lines.append(f"   {item['link']}\n")

        full_message = "\n".join(message_lines) + CUSTOM_FOOTER_TEXT

        print("🚀 Dispatching news briefings concurrently...")
        
        # Run both dispatches concurrently in the same pipeline execution
        send_whatsapp_briefing(full_message)
        send_telegram_briefing(full_message)