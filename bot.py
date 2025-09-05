import os
import re
import sys
import time
import signal
import logging
from collections import defaultdict
from io import BytesIO
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import yt_dlp
    import requests
    from telegram import Update
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install yt-dlp python-telegram-bot requests")
    sys.exit(1)

# ==========================
# Config from environment
# ==========================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 10))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 50))
COOKIES_FILE = "cookies.txt" if os.path.exists("cookies.txt") else None

# ==========================
# Logging setup
# ==========================
def setup_logging():
    os.makedirs("logs", exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.FileHandler("logs/bot.log")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging()

# ==========================
# Rate Limiting
# ==========================
user_last_request = defaultdict(float)

# ==========================
# Helpers
# ==========================
def sanitize_filename(filename: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*]', "_", filename)
    return clean[:100]

def download_audio_info(url: str):
    ydl_opts = {
        "format": "bestaudio[ext=mp3]/bestaudio/best",
        "quiet": True,
        "nocheckcertificate": True,
        "cookies": COOKIES_FILE,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

# ==========================
# Handlers
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hey! Send me a KukuFM link and I’ll try to fetch the audio.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_time = time.time()

    # Rate limit check
    if current_time - user_last_request[user_id] < RATE_LIMIT_SECONDS:
        await update.message.reply_text("⏳ Please wait before making another request.")
        return
    user_last_request[user_id] = current_time

    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("❌ Please send a valid URL.")
        return

    try:
        info = download_audio_info(url)
        if not info or "url" not in info:
            await update.message.reply_text("❌ Could not fetch audio.")
            return

        audio_url = info["url"]
        title = sanitize_filename(info.get("title", "audio"))

        response = requests.get(audio_url, stream=True, timeout=60)
        response.raise_for_status()

        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_FILE_SIZE_MB * 1024 * 1024:
            await update.message.reply_text(f"❌ File too large (> {MAX_FILE_SIZE_MB}MB).")
            return

        audio_data = BytesIO(response.content)
        audio_data.name = f"{title}.mp3"

        await update.message.reply_audio(audio_data)
        logger.info(f"✅ Sent audio: {title}")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ==========================
# Health server
# ==========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

# ==========================
# Graceful shutdown
# ==========================
def signal_handler(sig, frame):
    logger.info("🛑 Bot shutting down gracefully...")
    sys.exit(0)

# ==========================
# Main
# ==========================
def main():
    if TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ Please set your actual BOT_TOKEN in environment variables!")
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    Thread(target=start_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot started successfully")
    app.run_polling()

if __name__ == "__main__":
    main()
