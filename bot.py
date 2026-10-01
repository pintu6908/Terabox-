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

# Supported TeraBox domains
TERABOX_DOMAINS = [
    "terabox.com", "1024terabox.com", "teraboxapp.com",
    "freeterabox.com", "mirrobox.com", "neobox.com", "dubox.com"
]

def extract_url(text: str) -> str | None:
    """Extracts the first valid TeraBox link found in text."""
    urls = re.findall(r"https?://[^\s]+", text)
    for url in urls:
        if any(domain in url for domain in TERABOX_DOMAINS):
            return url
    return None

def fetch_terabox_media(url: str) -> dict | None:
    """Queries public parsing endpoint for media stream & download links."""
    api_url = f"https://terabox-dl.qtls.workers.dev/?url={url}"
    try:
        response = requests.get(api_url, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logging.error(f"API Error: {e}")
    return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Welcome to TeraBox Streamer & Downloader Bot!**\n\n"
        "Send me any valid TeraBox video link, and I will generate instant links "
        "for **online streaming** and **direct downloading**."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    terabox_url = extract_url(user_text)

    if not terabox_url:
        await update.message.reply_text("❌ Please send a valid TeraBox link.")
        return

    status_msg = await update.message.reply_text("🔎 Processing link, please wait...")

    media_data = fetch_terabox_media(terabox_url)

    if not media_data or "download_url" not in media_data:
        await status_msg.edit_text("⚠️ Could not process this TeraBox link. It may be private or expired.")
        return

    file_name = media_data.get("file_name", "TeraBox_Video.mp4")
    download_url = media_data.get("download_url")
    stream_url = media_data.get("stream_url", download_url)

    buttons = [
        [InlineKeyboardButton("▶️️ Watch Online", url=stream_url)],
        [InlineKeyboardButton("⬇️ Direct Download", url=download_url)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    caption = (
        f"🎬 **File Name:** `{file_name}`\n\n"
        f"• **Watch Online:** Stream directly in your web browser.\n"
        f"• **Direct Download:** Fast direct MP4 download."
    )

    await status_msg.edit_text(caption, reply_markup=reply_markup, parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
