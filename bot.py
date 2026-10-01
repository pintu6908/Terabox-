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
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "")  # Optional: Add your cookie to .env

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

# Multiple API endpoints for fallback redundancy
API_ENDPOINTS = [
    "https://terabox-downloader.workers.dev/?url={}",
    "https://terabox-downloader-v2.vercel.app/api?url={}",
    "https://terabx.com/api/link?url={}",
    "https://terashare.co/api/download?url={}",
    "https://terabox-dl.qtls.workers.dev/?url={}",
]

def get_headers():
    """Generate headers with optional cookie support."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://www.google.com/",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
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
            # Clean the URL - remove trailing characters that aren't part of the URL
            url = re.sub(r'[\)\]\}\s]+$', '', url)
            return url
    return None

def extract_surl_from_url(url: str) -> str | None:
    """Extracts the surl parameter from TeraBox URLs."""
    try:
        # Check for surl in query parameters
        if "surl=" in url:
            surl_match = re.search(r'surl=([a-zA-Z0-9_-]+)', url)
            if surl_match:
                return surl_match.group(1)
        
        # Check in path
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
        data.get("dl_link")
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
    """Cycles through multiple fallback APIs until one successfully resolves the link."""
    
    # Try to extract surl for better compatibility
    surl = extract_surl_from_url(url)
    logging.info(f"Processing URL: {url}")
    if surl:
        logging.info(f"Extracted surl: {surl}")
    
    # Prepare different URL variations for APIs
    url_variations = [url]
    if surl:
        # Add variations with just the surl
        url_variations.append(f"https://1024terabox.com/s/{surl}")
        url_variations.append(f"https://terabox.com/s/{surl}")
    
    headers = get_headers()
    
    for api_url_template in API_ENDPOINTS:
        for url_variant in url_variations:
            try:
                # URL encode the link to handle special characters
                encoded_url = quote(url_variant, safe=':/?=&')
                api_url = api_url_template.format(encoded_url)
                
                logging.info(f"Attempting API with URL: {api_url[:80]}...")
                response = requests.get(api_url, headers=headers, timeout=20)
                
                logging.info(f"API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logging.info(f"API Response Data: {json.dumps(data)[:200]}")
                        
                        dl_url, st_url, filename = parse_api_response(data)
                        if dl_url:
                            logging.info(f"✅ Successfully extracted: {filename}")
                            return dl_url, st_url, filename
                    except json.JSONDecodeError:
                        logging.warning(f"Invalid JSON response from {api_url_template}")
                        continue
                        
            except requests.exceptions.Timeout:
                logging.warning(f"Timeout from {api_url_template}")
                continue
            except requests.exceptions.ConnectionError:
                logging.warning(f"Connection error from {api_url_template}")
                continue
            except Exception as e:
                logging.warning(f"Error with {api_url_template}: {str(e)[:100]}")
                continue

    logging.error("❌ All APIs failed to extract download link")
    return None, None, "TeraBox_Video.mp4"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookie_status = "✅ Cookie configured" if TERABOX_COOKIE else "⚠️ No cookie (public links only)"
    
    welcome_text = (
        "👋 **Welcome to TeraBox Streamer & Downloader Bot!**\n\n"
        "Send me any TeraBox video link, and I will generate instant links "
        "for **online streaming** and **direct downloading**.\n\n"
        "✅ **Supported Domains:**\n"
        "• terabox.com\n"
        "• 1024terabox.com\n"
        "• 1024tera.com\n"
        "• teraboxapp.com\n"
        "• And more mirror domains!\n\n"
        f"🔐 **Status:** {cookie_status}\n\n"
        "📌 **Note:** Make sure the link is public and doesn't require a password."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text(
            "❌ **Invalid Link.** Please send a valid TeraBox link (e.g., `terabox.com/s/...`, `1024terabox.com/s/...`, `1024tera.com/wap/share/filelist?surl=...`).",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("🔎 Processing link across multiple servers, please wait...")

    download_url, stream_url, file_name = fetch_terabox_media(terabox_url)

    if not download_url:
        await status_msg.edit_text(
            "⚠️ **Processing Failed.**\n\n"
            "This could happen if:\n"
            "• The link is password-protected or requires login\n"
            "• The link is expired or deleted\n"
            "• It's a folder (not a single file)\n"
            "• The file size is too large\n"
            "• API servers are temporarily unavailable\n\n"
            "💡 **Tips:**\n"
            "• Try using a different domain (terabox.com instead of 1024terabox.com)\n"
            "• Make sure the link is public and accessible without login\n"
            "• Wait a moment and try again\n\n"
            "If the problem persists, the external APIs may need maintenance."
        )
        return

    buttons = [
        [InlineKeyboardButton("▶ Watch Online", url=stream_url)],
        [InlineKeyboardButton("⬇️ Direct Download", url=download_url)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    caption = (
        f"🎬 **File Name:** `{file_name}`\n\n"
        f"• **Watch Online:** Stream directly in your browser.\n"
        f"• **Direct Download:** Download full file directly."
    )

    await status_msg.edit_text(caption, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is active and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()
