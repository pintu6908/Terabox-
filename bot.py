import logging
import os
import re
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load configuration from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing! Set it in your .env file or environment variables.")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Expanded list of TeraBox domains & mirrors
TERABOX_DOMAINS = [
    "terabox", "1024terabox", "teraboxapp", "freeterabox", 
    "mirrobox", "neobox", "dubox", "terasharelink", 
    "momolee", "tibimbox", "gibimbox"
]

# Multiple API endpoints for fallback redundancy
API_ENDPOINTS = [
    "https://terabox-dl.qtls.workers.dev/?url={}",
    "https://terabox-downloader-api.vercel.app/api?url={}",
    "https://api.teraboxdownloader.workers.dev/?url={}"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def extract_url(text: str) -> str | None:
    """Extracts any valid TeraBox or mirror URL from the text."""
    urls = re.findall(r"https?://[^\s]+", text)
    for url in urls:
        url_lower = url.lower()
        if any(domain in url_lower for domain in TERABOX_DOMAINS):
            return url
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
        data.get("url")
    )
    
    # Handle nested data payloads if present
    if not download_url and "data" in data and isinstance(data["data"], dict):
        nested = data["data"]
        download_url = nested.get("download_url") or nested.get("dlink") or nested.get("url")

    # Extract stream URL
    stream_url = data.get("stream_url") or download_url

    # Extract file name
    file_name = (
        data.get("file_name") or 
        data.get("filename") or 
        data.get("title") or 
        "TeraBox_Video.mp4"
    )

    return download_url, stream_url, file_name

def fetch_terabox_media(url: str) -> tuple[str | None, str | None, str]:
    """Cycles through multiple fallback APIs until one successfully resolves the link."""
    for endpoint in API_ENDPOINTS:
        try:
            api_url = endpoint.format(url)
            logging.info(f"Attempting API: {api_url}")
            response = requests.get(api_url, headers=HEADERS, timeout=12)
            
            if response.status_code == 200:
                data = response.json()
                dl_url, st_url, filename = parse_api_response(data)
                if dl_url:
                    return dl_url, st_url, filename
        except Exception as e:
            logging.warning(f"Endpoint failed ({endpoint}): {e}")
            continue

    return None, None, "TeraBox_Video.mp4"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Welcome to TeraBox Streamer & Downloader Bot!**\n\n"
        "Send me any TeraBox video link, and I will generate instant links "
        "for **online streaming** and **direct downloading**."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text(
            "❌ **Invalid Link.** Please send a valid TeraBox link (e.g., `terabox.com`, `1024terabox.com`, `teraboxapp.com`).",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("🔎 Processing link across fallback servers, please wait...")

    download_url, stream_url, file_name = fetch_terabox_media(terabox_url)

    if not download_url:
        await status_msg.edit_text(
            "⚠️ **Processing Failed.** The link might be password-protected, contain a folder instead of a single video, or be expired."
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
