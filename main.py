import os
import asyncio
import logging
import requests
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")

# --- RENDER WEB SERVICE PORT BINDER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

keep_alive()
# --------------------------------------------------

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
SESSION_STRING = os.environ["SESSION_STRING"]
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the host environment.")

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

SONG_FILE = "current_song.mp3"

def download_audio_track(query: str):
    """Fetch track using public Invidious API and download MP3 locally without bot checks"""
    try:
        if os.path.exists(SONG_FILE):
            os.remove(SONG_FILE)

        # Public Invidious instance search endpoint
        search_url = f"https://invidious.perennialverse.net/api/v1/search?q={requests.utils.quote(query)}&type=video"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        response = requests.get(search_url, headers=headers, timeout=10)
        data = response.json()
        
        if not data or not isinstance(data, list):
            raise ValueError("No tracks found.")
            
        video_id = data[0].get("videoId")
        title = data[0].get("title", query)
        
        if not video_id:
            raise ValueError("Could not find video ID.")
            
        # Get direct stream formats from Invidious
        details_url = f"https://invidious.perennialverse.net/api/v1/videos/{video_id}"
        details_resp = requests.get(details_url, headers=headers, timeout=10)
        details_data = details_resp.json()
        
        adaptive_formats = details_data.get("adaptiveFormats", [])
        audio_url = None
        for fmt in adaptive_formats:
            if "audio" in fmt.get("type", ""):
                audio_url = fmt.get("url")
                break
                
        if not audio_url:
            # Fallback to standard formats
            format_streams = details_data.get("formatStreams", [])
            if format_streams:
                audio_url = format_streams[0].get("url")
                
        if not audio_url:
            raise ValueError("Direct audio stream unavailable.")
            
        # Download locally
        log.info("Downloading track locally: %s", title)
        audio_resp = requests.get(audio_url, headers=headers, timeout=20)
        with open(SONG_FILE, "wb") as f:
            f.write(audio_resp.content)
            
        return SONG_FILE, title
    except Exception as exc:
        log.error("Download failed: %s", exc)
        raise ValueError(f"Could not download song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Invidious Music Bot is online!\n"
        "Use `/song [name]` to download and stream music smoothly."
    )

@bot.on_message(filters.command("song") & filters.group)
async def song_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/song [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"📥 Downloading `{query}`...")
    
    try:
        file_path, title = await asyncio.to_thread(download_audio_track, query)
        
        # Stream the local file directly into the voice chat
        await calls.play(
            message.chat.id,
            MediaStream(file_path),
        )
        await status.edit_text(f"🎶 Now playing locally: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        await status.edit_text(f"Error: `{str(exc)[:200]}`")

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    log.info("Music bot started successfully")
    try:
        await asyncio.Event().wait()
    finally:
        await calls.stop()
        await user.stop()
        await bot.stop()

if __name__ == "__main__":
    bot.run(main())
