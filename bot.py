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
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing! Set it in your .env file or environment variables.")

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

# Updated working API endpoints - Public & Reliable
API_ENDPOINTS = [
    ("https://terabox.hoyoverse.workers.dev/api/download?url={}", "cloudflare"),
    ("https://terabox-downloader.vercel.app/api/download?url={}", "vercel"),
    ("https://terabox-api.onrender.com/api/download?url={}", "render"),
    ("https://terabox.app/api/download?url={}", "terabox-app"),
    ("https://api.example.terabox.cloud/download?url={}", "cloud"),
    ("https://tb.thinker.workers.dev/?url={}", "workers"),
    ("https://terabox-dl.workers.dev/?url={}", "workers-dl"),
]

def get_headers(referer_url=""):
    """Generate headers for better API compatibility."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    if referer_url:
        headers["Referer"] = referer_url
    else:
        headers["Referer"] = "https://www.google.com/"
    
    # Add cookie if available
    if TERABOX_COOKIE:
        headers["Cookie"] = TERABOX_COOKIE
        logging.info("✅ Using TeraBox cookie for authentication")
    
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
    if data.get("error") or data.get("status") == "error" or data.get("code") != 0 and data.get("code") != "0":
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
        data.get("download_link")
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
                nested.get("download")
            )
        elif isinstance(nested, list) and len(nested) > 0:
            if isinstance(nested[0], dict):
                download_url = (
                    nested[0].get("download_url") or 
                    nested[0].get("dlink") or 
                    nested[0].get("url") or
                    nested[0].get("file_url") or
                    nested[0].get("link") or
                    nested[0].get("download")
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
    """Cycles through multiple public API services until one successfully resolves the link."""
    
    surl = extract_surl_from_url(url)
    logging.info(f"🔍 Processing URL: {url}")
    if surl:
        logging.info(f"📍 Extracted surl: {surl}")
    
    # URL variations for better compatibility
    url_variations = [url]
    if surl:
        url_variations.append(f"https://1024terabox.com/s/{surl}")
        url_variations.append(f"https://terabox.com/s/{surl}")
    
    headers = get_headers(url)
    
    # Try each API endpoint
    for api_url_template, api_name in API_ENDPOINTS:
        for url_variant in url_variations:
            try:
                encoded_url = quote(url_variant, safe=':/?=&')
                api_url = api_url_template.format(encoded_url)
                
                logging.info(f"🔄 Trying {api_name} API...")
                response = requests.get(api_url, headers=headers, timeout=15, allow_redirects=True)
                
                logging.info(f"📡 {api_name} Response Status: {response.status_code}")
                
                # Accept 200 and 201 status codes
                if response.status_code in [200, 201]:
                    try:
                        data = response.json()
                        logging.info(f"📦 {api_name} Response: {json.dumps(data)[:300]}")
                        
                        dl_url, st_url, filename = parse_api_response(data)
                        if dl_url:
                            logging.info(f"✅ SUCCESS from {api_name}: {filename}")
                            return dl_url, st_url, filename
                        else:
                            logging.warning(f"⚠️ No download URL in {api_name} response")
                    except json.JSONDecodeError as e:
                        logging.warning(f"❌ {api_name} returned invalid JSON: {e}")
                        # Try parsing as text response
                        if response.text and len(response.text) > 10:
                            logging.info(f"Raw response: {response.text[:200]}")
                        continue
                elif response.status_code == 429:
                    logging.warning(f"⏱️ {api_name} rate limited, trying next...")
                    continue
                else:
                    logging.warning(f"⚠️ {api_name} returned status {response.status_code}")
                    
            except requests.exceptions.Timeout:
                logging.warning(f"⏱️ {api_name} timeout - trying next endpoint")
                continue
            except requests.exceptions.ConnectionError:
                logging.warning(f"🌐 {api_name} connection error - trying next endpoint")
                continue
            except Exception as e:
                logging.warning(f"❌ {api_name} error: {str(e)[:100]}")
                continue

    logging.error("❌ All APIs failed to extract download link")
    return None, None, "TeraBox_Video.mp4"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookie_status = "✅ Authenticated" if TERABOX_COOKIE else "🔓 Public mode"
    
    welcome_text = (
        "👋 **Welcome to TeraBox Streamer & Downloader Bot!**\n\n"
        "Send me any TeraBox video link, and I will generate instant links "
        "for **online streaming** and **direct downloading**.\n\n"
        "✅ **Supported Domains:**\n"
        "• terabox.com\n"
        "• 1024terabox.com\n"
        "• 1024tera.com\n"
        "• teraboxapp.com\n"
        "• mirrobox.com\n"
        "• And other TeraBox mirrors!\n\n"
        f"🔐 **Mode:** {cookie_status}\n"
        "🚀 **Status:** Using 7 public APIs for maximum compatibility\n\n"
        "📌 **Usage:** Just send the TeraBox link and wait!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text(
            "❌ **Invalid Link.**\n\n"
            "Please send a valid TeraBox link:\n"
            "• `https://terabox.com/s/xxxxx`\n"
            "• `https://1024terabox.com/s/xxxxx`\n"
            "• `https://1024tera.com/wap/share/filelist?surl=xxxxx`",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("🔎 **Processing...**\n\nTrying 7 different public APIs, please wait...")

    download_url, stream_url, file_name = fetch_terabox_media(terabox_url)

    if not download_url:
        await status_msg.edit_text(
            "⚠️ **Unable to Process This Link**\n\n"
            "Possible reasons:\n"
            "✗ Link is password-protected\n"
            "✗ Link is expired or deleted\n"
            "✗ It's a folder (not a single file)\n"
            "✗ File is too large\n"
            "✗ Public APIs are temporarily down\n\n"
            "💡 **What to try:**\n"
            "1️⃣ Verify the link is public (no password)\n"
            "2️⃣ Try a different TeraBox domain variant\n"
            "3️⃣ Copy the link again and retry\n"
            "4️⃣ Wait 5 minutes and try again\n\n"
            "📝 **Note:** If all public APIs fail, you may need a premium/authenticated API."
        )
        return

    buttons = [
        [InlineKeyboardButton("▶️ Watch Online", url=stream_url)],
        [InlineKeyboardButton("⬇️ Direct Download", url=download_url)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    caption = (
        f"🎬 **File:** `{file_name}`\n\n"
        f"✅ **Download ready!**\n\n"
        f"• **Watch Online:** Stream in browser\n"
        f"• **Direct Download:** Save to device"
    )

    await status_msg.edit_text(caption, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is active and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()
