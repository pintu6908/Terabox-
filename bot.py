import logging
import os
import re
import requests
import json
from urllib.parse import quote, urlparse, parse_qs
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load configuration from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIE_JSON = os.getenv("COOKIE_JSON", "")
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "")

# Use COOKIE_JSON if available, otherwise fall back to TERABOX_COOKIE
AUTH_COOKIE = COOKIE_JSON or TERABOX_COOKIE

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing! Set it in your .env file or environment variables.")

if not AUTH_COOKIE:
    logging.warning("⚠️ WARNING: No COOKIE_JSON or TERABOX_COOKIE found in .env - Bot will use public APIs only")
else:
    logging.info("✅ Authentication cookie loaded successfully")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Expanded list of TeraBox domains & mirrors
TERABOX_DOMAINS = [
    "terabox", "1024terabox", "1024tera", "teraboxapp", "freeterabox", 
    "mirrobox", "neobox", "dubox", "terasharelink", 
    "momolee", "tibimbox", "gibimbox"
]

# API endpoints optimized for authenticated requests
API_ENDPOINTS = [
    ("https://terabox.hoyoverse.workers.dev/api/download?url={}", "hoyoverse"),
    ("https://terabox-downloader.vercel.app/api/download?url={}", "vercel"),
    ("https://terabox-api.onrender.com/api/download?url={}", "render"),
    ("https://tb.thinker.workers.dev/?url={}", "thinker"),
    ("https://terabox-dl.workers.dev/?url={}", "workers-dl"),
    ("https://terabox.app/api/download?url={}", "terabox-app"),
]

def get_headers(referer_url="", use_auth=True):
    """Generate headers with cookie authentication."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }
    
    if referer_url:
        headers["Referer"] = referer_url
    else:
        headers["Referer"] = "https://www.terabox.com/"
    
    # FORCE authentication - use cookie JSON if available
    if use_auth and AUTH_COOKIE:
        headers["Cookie"] = AUTH_COOKIE
        logging.info("🔐 Using COOKIE_JSON for authentication")
    
    return headers

def extract_url(text: str) -> str | None:
    """Extracts any valid TeraBox or mirror URL from the text."""
    urls = re.findall(r"https?://[^\s]+", text)
    for url in urls:
        url_lower = url.lower()
        if any(domain in url_lower for domain in TERABOX_DOMAINS):
            url = re.sub(r'[\)\]\}\s"\']+$', '', url)
            return url
    return None

def extract_surl_from_url(url: str) -> str | None:
    """Extracts the surl parameter from TeraBox URLs."""
    try:
        if "surl=" in url:
            surl_match = re.search(r'surl=([a-zA-Z0-9_-]+)', url)
            if surl_match:
                return surl_match.group(1)
        
        if "/s/" in url:
            parts = url.split("/s/")
            if len(parts) > 1:
                surl = parts[1].split("?")[0].split("&")[0]
                return surl if surl else None
    except Exception as e:
        logging.error(f"Error extracting surl: {e}")
    
    return None

def parse_api_response(data: dict) -> tuple[str | None, str | None, str]:
    """Dynamically locates download link, stream link, and file name across different API structures."""
    if not isinstance(data, dict):
        return None, None, "TeraBox_Video.mp4"

    # Check for error responses
    if data.get("error") or data.get("status") == "error":
        logging.warning(f"API returned error: {data}")
        return None, None, "TeraBox_Video.mp4"

    # Extract download URL across common keys
    download_url = (
        data.get("download_url") or 
        data.get("downloadLink") or 
        data.get("direct_link") or 
        data.get("dlink") or
        data.get("url") or
        data.get("file_url") or
        data.get("link") or
        data.get("download") or
        data.get("dl_link") or
        data.get("download_link") or
        data.get("fs_id")
    )
    
    # Handle nested data payloads if present
    if not download_url and "data" in data:
        nested = data["data"]
        if isinstance(nested, dict):
            download_url = (
                nested.get("download_url") or 
                nested.get("dlink") or 
                nested.get("url") or 
                nested.get("file_url") or
                nested.get("link") or
                nested.get("download") or
                nested.get("fs_id")
            )
        elif isinstance(nested, list) and len(nested) > 0:
            if isinstance(nested[0], dict):
                download_url = (
                    nested[0].get("download_url") or 
                    nested[0].get("dlink") or 
                    nested[0].get("url") or
                    nested[0].get("file_url") or
                    nested[0].get("link") or
                    nested[0].get("download") or
                    nested[0].get("fs_id")
                )

    # Extract stream URL
    stream_url = (
        data.get("stream_url") or 
        data.get("video_url") or 
        data.get("play_url") or
        download_url
    )

    # Extract file name
    file_name = (
        data.get("file_name") or 
        data.get("filename") or 
        data.get("title") or 
        data.get("name") or
        data.get("file") or
        "TeraBox_Video.mp4"
    )

    return download_url, stream_url, file_name

def fetch_terabox_media(url: str) -> tuple[str | None, str | None, str]:
    """Fetches media using authenticated cookie for better success rate."""
    
    surl = extract_surl_from_url(url)
    logging.info(f"🔍 Processing URL: {url}")
    if surl:
        logging.info(f"📍 Extracted surl: {surl}")
    
    # URL variations
    url_variations = [url]
    if surl:
        url_variations.append(f"https://1024terabox.com/s/{surl}")
        url_variations.append(f"https://terabox.com/s/{surl}")
    
    # FORCE authenticated headers
    headers = get_headers(url, use_auth=True)
    
    logging.info("🔐 Attempting with COOKIE_JSON authentication...")
    
    for api_url_template, api_name in API_ENDPOINTS:
        for url_variant in url_variations:
            try:
                encoded_url = quote(url_variant, safe=':/?=&')
                api_url = api_url_template.format(encoded_url)
                
                logging.info(f"🔄 Trying {api_name} with auth cookie...")
                response = requests.get(
                    api_url, 
                    headers=headers, 
                    timeout=20, 
                    allow_redirects=True,
                    verify=True
                )
                
                logging.info(f"📡 {api_name} Status: {response.status_code}")
                
                if response.status_code in [200, 201]:
                    try:
                        data = response.json()
                        logging.info(f"📦 {api_name} Response: {json.dumps(data)[:300]}")
                        
                        dl_url, st_url, filename = parse_api_response(data)
                        if dl_url:
                            logging.info(f"✅ SUCCESS from {api_name} with AUTH: {filename}")
                            return dl_url, st_url, filename
                        else:
                            logging.warning(f"⚠️ No download URL in {api_name} response")
                    except json.JSONDecodeError as e:
                        logging.warning(f"❌ {api_name} invalid JSON: {e}")
                        continue
                elif response.status_code == 429:
                    logging.warning(f"⏱️ {api_name} rate limited")
                    continue
                else:
                    logging.warning(f"⚠️ {api_name} returned {response.status_code}")
                    
            except requests.exceptions.Timeout:
                logging.warning(f"⏱️ {api_name} timeout")
                continue
            except requests.exceptions.ConnectionError:
                logging.warning(f"🌐 {api_name} connection error")
                continue
            except Exception as e:
                logging.warning(f"❌ {api_name} error: {str(e)[:100]}")
                continue

    logging.error("❌ All authenticated API attempts failed")
    return None, None, "TeraBox_Video.mp4"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_status = "🔐 Authenticated (COOKIE_JSON)" if AUTH_COOKIE else "🔓 Public Mode"
    
    welcome_text = (
        "👋 **Welcome to TeraBox Downloader Bot!**\n\n"
        "Send me any TeraBox video link for instant download!\n\n"
        "✅ **Supported:**\n"
        "• terabox.com\n"
        "• 1024terabox.com\n"
        "• 1024tera.com\n"
        "• All TeraBox mirrors\n\n"
        f"🔐 **Authentication:** {auth_status}\n"
        "🚀 **Status:** Ready to process links\n\n"
        "📌 Just send the link and wait for results!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text(
            "❌ **Invalid Link**\n\n"
            "Send a valid TeraBox link:\n"
            "• `https://terabox.com/s/xxxxx`\n"
            "• `https://1024terabox.com/s/xxxxx`",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text(
        "🔎 **Processing with authenticated access...**\n\nPlease wait..."
    )

    download_url, stream_url, file_name = fetch_terabox_media(terabox_url)

    if not download_url:
        await status_msg.edit_text(
            "⚠️ **Processing Failed**\n\n"
            "• Link may be password-protected\n"
            "• Link may be expired\n"
            "• It might be a folder\n"
            "• APIs temporarily unavailable\n\n"
            "Try again in a moment."
        )
        return

    buttons = [
        [InlineKeyboardButton("▶️ Watch Online", url=stream_url)],
        [InlineKeyboardButton("⬇️ Download", url=download_url)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    caption = (
        f"🎬 **File:** `{file_name}`\n\n"
        f"✅ Ready to download!"
    )

    await status_msg.edit_text(caption, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot started - Using COOKIE_JSON authentication")
    app.run_polling()

if __name__ == "__main__":
    main()
