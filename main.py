import os
import re
import feedparser
from whatsapp_api_client_python import API

# Load credentials from GitHub Secrets
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")

# News sources
RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://rss.cnn.com/rss/edition_world.rss"
]

# Filtering rules
EXCLUDED_SPORTS = ["basketball", "nba", "tennis", "golf", "cricket", "nfl", "boxing", "ufc"]
FOOTBALL_KEYWORDS = ["football", "fifa", "world cup", "champions league", "premier league", "soccer"]

def is_relevant(title, summary):
    text = f"{title} {summary}".lower()
    
    # Exclude non-football sports
    for sport in EXCLUDED_SPORTS:
        if sport in text:
            return False
            
    # If "sport" is mentioned, allow only if it's international football
    if "sport" in text:
        return any(fb in text for fb in FOOTBALL_KEYWORDS)
        
    return True

def get_headlines():
    articles = []
    seen = set()

    for feed in RSS_FEEDS:
        data = feedparser.parse(feed)
        for entry in data.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if title and title not in seen and is_relevant(title, summary):
                seen.add(title)
                articles.append({"title": title, "link": link})

    # Return 12 if available, otherwise default to 10
    limit = 12 if len(articles) >= 12 else 10
    return articles[:limit]

def send_whatsapp():
    articles = get_headlines()
    if not articles:
        print("No articles found.")
        return

    # Format the WhatsApp message
    message_lines = [
        "*Today's Biggest Headlines*",
        "",
        "Here are some of the news reports that you shouldn't miss this morning:",
        ""
    ]

    for index, item in enumerate(articles, start=1):
        message_lines.append(f"{index}. *{item['title']}*")
        message_lines.append(f"   {item['link']}\n")

    full_message = "\n".join(message_lines)

    # Send via Green API
    green_api = API.GreenAPI(INSTANCE_ID, API_TOKEN)
    response = green_api.sending.sendMessage(TARGET_CHAT_ID, full_message)
    print("Sent successfully! Message ID:", response.data.get("idMessage"))

if __name__ == "__main__":
    send_whatsapp()