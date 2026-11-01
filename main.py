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
    """Fetch exact song match from public music API and download locally"""
    if os.path.exists(SONG_FILE):
        os.remove(SONG_FILE)

    try:
        # Public Saavn song search API endpoint
        search_url = f"https://jiosaavn-api-private.vercel.app/search/songs?query={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        log.info("Querying music API for: %s", query)
        response = requests.get(search_url, headers=headers, timeout=10)
        data = response.json()
        
        results = data.get("data", {}).get("results", [])
        if not results:
            raise ValueError("No matching songs found via API.")
            
        song = results[0]
        title = song.get("name", query)
        
        # Get the highest available quality download link (.mp3)
        download_urls = song.get("downloadUrl", [])
        audio_url = None
        if download_urls:
            # Grabs the highest quality link from the array
            audio_url = download_urls[-1].get("link") or download_urls[-1].get("url")
            
        if not audio_url:
            raise ValueError("Direct audio stream link unavailable.")
            
        log.info("Downloading API track locally: %s", title)
        audio_resp = requests.get(audio_url, headers=headers, timeout=30)
        if audio_resp.status_code != 200:
            raise ValueError("Failed to download audio file stream.")
            
        with open(SONG_FILE, "wb") as f:
            f.write(audio_resp.content)
            
        return os.path.abspath(SONG_FILE), title
    except Exception as exc:
        log.error("API download failed: %s", exc)
        raise ValueError(f"Could not download song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 API Music Bot is online!\n\n"
        "**Commands:**\n"
        "• `/song [name]` - Search & play exact songs\n"
        "• `/pause` - Pause music\n"
        "• `/resume` - Resume music\n"
        "• `/stop` or `/skip` - Stop & leave VC"
    )

@bot.on_message(filters.command("song") & filters.group)
async def song_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/song [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"🔍 Searching API for `{query}`...")
    
    try:
        file_path, title = await asyncio.to_thread(download_audio_track, query)
        
        await calls.play(
            message.chat.id,
            MediaStream(file_path),
        )
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        if hasattr(status, 'edit_text'):
            await status.edit_text(f"Error: `{str(exc)[:200]}`")

@bot.on_message(filters.command("pause") & filters.group)
async def pause_command(_, message):
    try:
        await calls.pause(message.chat.id)
        await message.reply_text("⏸ Paused the music.")
    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

@bot.on_message(filters.command("resume") & filters.group)
async def resume_command(_, message):
    try:
        await calls.resume(message.chat.id)
        await message.reply_text("▶️ Resumed the music.")
    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

@bot.on_message(filters.command(["stop", "skip", "next"]) & filters.group)
async def stop_command(_, message):
    try:
        await calls.leave_group_call(message.chat.id)
        await message.reply_text("⏹ Stopped playback and left the voice chat.")
    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

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
