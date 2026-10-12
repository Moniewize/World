import calendar
import html
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import requests

# ==============================================================================
# CUSTOM CLOSING TEXT
# ==============================================================================
CUSTOM_FOOTER_TEXT = "\n\n*Source:* BBC, DW, CNN\n*Brought by*: RAC-FUTO Editorial Team"

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID") or os.environ.get("GREEN_API_ID_INSTANCE")
API_TOKEN = os.environ.get("GREEN_API_TOKEN")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")  # one or several, separated by commas

# Optional: the host shown as "apiUrl" in your Green API console instance settings
GREEN_API_URL = (os.environ.get("GREEN_API_URL") or "").strip().rstrip("/")
GREEN_API_HOSTS = [h for h in dict.fromkeys([
    GREEN_API_URL,                 # your own host, if set
    "https://api.greenapi.com",    # Green API's universal host
    "https://api.green-api.com",   # the old host
]) if h]
GREEN_STATE = {"down": False}      # set once every host proved unreachable

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# STRICTLY OFFICIAL BROADCASTERS ONLY
RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",      # BBC News World
    "https://rss.dw.com/rdf/rss-en-world",            # Deutsche Welle World
    "http://rss.cnn.com/rss/edition_world.rss"        # CNN World
]
ALLOWED_DOMAINS = ("bbc.com", "bbc.co.uk", "dw.com", "cnn.com")

MAX_AGE_DAYS = 7
DROP_OFF_TOPIC_SPORTS = True  # False: keep them, ranked lower

EXCLUDED_SPORTS = ["basketball", "nba", "tennis", "golf", "cricket", "nfl", "boxing", "ufc"]
FOOTBALL_KEYWORDS = ["football", "fifa", "world cup", "champions league", "premier league", "soccer"]
EXCLUDED_RE = re.compile(r"\b(" + "|".join(EXCLUDED_SPORTS) + r")\b")
FOOTBALL_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in FOOTBALL_KEYWORDS) + r")\b")
SPORT_RE = re.compile(r"\bsports?\b")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def safe(text):
    """Hides secret tokens in anything that is printed."""
    text = str(text)
    for secret in (API_TOKEN, TELEGRAM_TOKEN):
        if secret:
            text = text.replace(secret, "***")
    return text


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def clean_link(url):
    """Strips query parameters and tracking paths to leave short, clean links."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))


def sport_status(title, summary):
    """Returns 'ok' or 'other_sport'."""
    text = clean_text(f"{title} {summary}").lower()
    if EXCLUDED_RE.search(text):
        return "other_sport"
    if SPORT_RE.search(text) and not FOOTBALL_RE.search(text):
        return "other_sport"
    return "ok"


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):  # some feeds only carry "updated"
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


def allowed_domain(link):
    host = urlparse(link).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def fetch_feed(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
    response.raise_for_status()
    return feedparser.parse(response.content)


# ==============================================================================
# FILTERING & RELEVANCE ENGINE
# ==============================================================================
def get_headlines():
    articles = []
    seen_titles, seen_links = set(), set()
    now = datetime.now(timezone.utc)
    oldest_allowed = now - timedelta(days=MAX_AGE_DAYS)

    for feed_url in RSS_FEEDS:
        try:
            data = fetch_feed(feed_url)
        except Exception as error:
            print(f"Feed failed ({feed_url}): {safe(error)}")
            continue

        kept, newest = 0, None
        for entry in data.entries:
            title = clean_text(entry.get("title", ""))
            raw_link = entry.get("link", "").strip()
            summary = entry.get("summary", "")

            if not title or not raw_link or not allowed_domain(raw_link):
                continue

            pub_date = entry_date(entry)
            if not pub_date:
                continue
            newest = max(newest, pub_date) if newest else pub_date

            if pub_date < oldest_allowed or pub_date > now + timedelta(hours=1):
                continue

            link = clean_link(raw_link)
            if title in seen_titles or link in seen_links:
                continue

            off_topic = sport_status(title, summary) == "other_sport"
            if off_topic and DROP_OFF_TOPIC_SPORTS:
                continue

            seen_titles.add(title)
            seen_links.add(link)
            kept += 1
            articles.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "relevant": not off_topic
            })

        newest_text = f"{newest:%d %b %H:%M} UTC" if newest else "none"
        print(f"{feed_url}: {len(data.entries)} entries, {kept} kept, newest entry {newest_text}.")

    if not articles:
        return []

    mid_point = sum(a["pub_date"].timestamp() for a in articles) / len(articles)

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
# WHATSAPP DISPATCH ENGINE (TEXT-ONLY)
# ==============================================================================
def green_post(endpoint, **kwargs):
    """Sends a request to Green API, trying each host. Moves on only if no connection was made."""
    if GREEN_STATE["down"]:
        raise ConnectionError("Green API was unreachable earlier in this run")
    last_error = None
    for round_number in range(2):
        for host in list(GREEN_API_HOSTS):
            link = f"{host}/waInstance{INSTANCE_ID}/{endpoint}/{API_TOKEN}"
            try:
                response = requests.post(link, timeout=(10, 60), **kwargs)
            except requests.ConnectionError as error:  # no connection: nothing was sent
                last_error = error
                print(f"Green API host not reachable: {host.split('//')[1]}")
                continue
            response.raise_for_status()
            print(f"Green API host used: {host.split('//')[1]}")
            if host != GREEN_API_HOSTS[0]:  # try the host that worked first next time
                GREEN_API_HOSTS.remove(host)
                GREEN_API_HOSTS.insert(0, host)
            return response.json()
        if round_number == 0:
            print("No Green API host reachable. Waiting 20 seconds, then trying again.")
            time.sleep(20)
    GREEN_STATE["down"] = True
    raise last_error


def chat_identifier(raw):
    cleaned = raw.strip().replace("+", "").replace(" ", "")
    return cleaned if ("@g.us" in cleaned or "@c.us" in cleaned) else f"{cleaned}@c.us"


def whatsapp_ready():
    return bool(INSTANCE_ID and API_TOKEN and TARGET_CHAT_ID)


def telegram_ready():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def send_whatsapp_briefing(message):
    """Returns (messages_sent, problems)."""
    if not whatsapp_ready():
        print("WhatsApp skipped: Green API environment variables not set.")
        return 0, []
    sent, problems = 0, []
    for raw in (p for p in TARGET_CHAT_ID.split(",") if p.strip()):
        chat = chat_identifier(raw)
        try:
            green_post("sendMessage", json={"chatId": chat, "message": message})
            sent += 1
            print(f"WhatsApp briefing delivered to {chat}")
        except Exception as error:
            problems.append(f"WhatsApp {chat}: {safe(error)}")
            print(f"WhatsApp dispatch failed for {chat}: {safe(error)}")
        time.sleep(3)
    return sent, problems


# ==============================================================================
# TELEGRAM DISPATCH ENGINE (TEXT-ONLY)
# ==============================================================================
def split_for_telegram(text, limit=4000):  # Telegram accepts at most 4096 characters
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


def send_telegram_briefing(message):
    """Returns (messages_sent, problems)."""
    if not telegram_ready():
        print("Telegram skipped: Telegram environment variables not set.")
        return 0, []

    link = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in split_for_telegram(message):
        delivered = False
        for extra in ({"parse_mode": "Markdown"}, {}):  # plain text if Markdown is rejected
            try:
                response = requests.post(
                    link, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, **extra}, timeout=30
                )
            except Exception as error:
                print(f"Telegram not reachable: {safe(error)}")
                return 0, [f"Telegram: {safe(error)}"]
            if response.status_code == 400 and extra:
                print(f"Telegram rejected the formatting ({response.text[:150]}). "
                      "Retrying as plain text.")
                continue
            if not response.ok:
                reason = response.text[:300]
                print(f"Telegram refused ({response.status_code}): {reason}")
                return 0, [f"Telegram {response.status_code}: {reason}"]
            delivered = True
            break
        if not delivered:
            return 0, ["Telegram: delivery failed"]

    print("Telegram briefing delivered.")
    return 1, []


# ==============================================================================
# SCRIPT EXECUTION
# ==============================================================================
def main():
    if not (whatsapp_ready() or telegram_ready()):
        print("No delivery channel is configured (WhatsApp or Telegram variables missing).")
        sys.exit(1)

    articles = get_headlines()
    if not articles:
        print("NOT SENT: no articles found meeting the recency and source criteria.")
        sys.exit(1)

    message_lines = [
        "Here are some of the news reports that you shouldn't miss this morning:",
        ""
    ]
    for index, item in enumerate(articles, start=1):
        # characters that break bold text or links in chat apps are removed
        safe_title = re.sub(r"[*_`\[\]]", "", item["title"])
        message_lines.append(f"{index}. *{safe_title}*")
        message_lines.append(f"   {item['link']}\n")

    full_message = "\n".join(message_lines) + CUSTOM_FOOTER_TEXT

    print("Dispatching news briefings...")
    delivered, problems = 0, []
    for send in (send_whatsapp_briefing, send_telegram_briefing):
        sent, issues = send(full_message)
        delivered += sent
        problems += issues

    if delivered == 0:
        print("NOT DELIVERED: no channel accepted the message.")
        sys.exit(1)
    if problems:
        print("PROBLEMS (the message reached some recipients):", *problems, sep="\n- ")
        sys.exit(1)  # marks the run as failed so GitHub emails you


if __name__ == "__main__":
    main()