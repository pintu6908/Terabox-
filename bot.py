import logging
import os
import re
import requests
from urllib.parse import quote
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
    "terabox", "1024terabox", "1024tera", "teraboxapp", "freeterabox", 
    "mirrobox", "neobox", "dubox", "terasharelink", 
    "momolee", "tibimbox", "gibimbox"
]

# Multiple API endpoints for fallback redundancy
API_ENDPOINTS = [
    "https://terabox-dl.qtls.workers.dev/?url={}",
    "https://terabox-downloader-api.vercel.app/api?url={}",
    "https://api.teraboxdownloader.workers.dev/?url={}",
    "https://www.terabox-downloader.workers.dev/?url={}"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.google.com/"
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
        data.get("url") or
        data.get("file_url") or
        data.get("link")
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
                nested.get("link")
            )
        elif isinstance(nested, list) and len(nested) > 0:
            if isinstance(nested[0], dict):
                download_url = (
                    nested[0].get("download_url") or 
                    nested[0].get("dlink") or 
                    nested[0].get("url") or
                    nested[0].get("file_url") or
                    nested[0].get("link")
                )

    # Extract stream URL
    stream_url = data.get("stream_url") or download_url

    # Extract file name
    file_name = (
        data.get("file_name") or 
        data.get("filename") or 
        data.get("title") or 
        data.get("name") or
        "TeraBox_Video.mp4"
    )

    return download_url, stream_url, file_name

def fetch_terabox_media(url: str) -> tuple[str | None, str | None, str]:
    """Cycles through multiple fallback APIs until one successfully resolves the link."""
    # URL encode the link to handle special characters
    encoded_url = quote(url, safe=':/?=&')
    
    for endpoint in API_ENDPOINTS:
        try:
            api_url = endpoint.format(encoded_url)
            logging.info(f"Attempting API: {api_url}")
            response = requests.get(api_url, headers=HEADERS, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                logging.info(f"API Response: {data}")
                dl_url, st_url, filename = parse_api_response(data)
                if dl_url:
                    logging.info(f"Successfully extracted: {filename}")
                    return dl_url, st_url, filename
        except requests.exceptions.Timeout:
            logging.warning(f"Endpoint timeout ({endpoint})")
            continue
        except requests.exceptions.ConnectionError:
            logging.warning(f"Connection error ({endpoint})")
            continue
        except ValueError as e:
            logging.warning(f"Invalid JSON from {endpoint}: {e}")
            continue
        except Exception as e:
            logging.warning(f"Endpoint failed ({endpoint}): {e}")
            continue

    return None, None, "TeraBox_Video.mp4"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Welcome to TeraBox Streamer & Downloader Bot!**\n\n"
        "Send me any TeraBox video link, and I will generate instant links "
        "for **online streaming** and **direct downloading**.\n\n"
        "✅ **Supported Domains:**\n"
        "• terabox.com\n"
        "• 1024terabox.com\n"
        "• 1024tera.com\n"
        "• teraboxapp.com\n"
        "• And more mirror domains!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text(
            "❌ **Invalid Link.** Please send a valid TeraBox link (e.g., `terabox.com`, `1024terabox.com`, `1024tera.com`).",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("🔎 Processing link across fallback servers, please wait...")

    download_url, stream_url, file_name = fetch_terabox_media(terabox_url)

    if not download_url:
        await status_msg.edit_text(
            "⚠️ **Processing Failed.**\n\n"
            "This could happen if:\n"
            "• The link is password-protected\n"
            "• The link is expired or deleted\n"
            "• It's a folder (not a single file)\n"
            "• API servers are temporarily down\n\n"
            "Please try again later or check if the link is public and valid."
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
