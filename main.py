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

def find_audio(query: str):
    """Search with robust safety checks to prevent NoneType crashes"""
    try:
        search_url = f"https://jiosaavn-api-private.vercel.app/search/songs?query={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(search_url, headers=headers, timeout=10)
        
        try:
            data = response.json()
        except Exception:
            raise ValueError("API returned invalid data format.")
            
        if not data or not isinstance(data, dict):
            raise ValueError("Empty response from search API.")
            
        # Safely extract results
        container = data.get("data")
        results = []
        if isinstance(container, dict):
            results = container.get("results", [])
        elif isinstance(container, list):
            results = container
            
        if not results:
            raise ValueError("No tracks found.")
            
        song = results[0]
        title = song.get("name") or song.get("title") or query
        
        # Get download link
        download_urls = song.get("downloadUrl", [])
        audio_url = None
        if isinstance(download_urls, list) and download_urls:
            last_item = download_urls[-1]
            if isinstance(last_item, dict):
                audio_url = last_item.get("link") or last_item.get("url")
        
        # Fallback fields if downloadUrl is structured differently
        if not audio_url:
            audio_url = song.get("media_url") or song.get("encrypted_media_url")
            
        if not audio_url:
            raise ValueError("Direct audio stream unavailable.")
            
        log.info("Found track successfully: %s", title)
        return audio_url, title
    except Exception as exc:
        log.error("Search failed: %s", exc)
        raise ValueError(f"Could not fetch song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Music Bot is online!\n"
        "Use `/play [song name]` to stream music smoothly."
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/play [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"🔎 Searching: {query}")
    try:
        audio_url, title = await asyncio.to_thread(find_audio, query)
        await calls.play(
            message.chat.id,
            MediaStream(audio_url),
        )
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        await status.edit_text(f"Playback error: `{str(exc)[:200]}`")

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
