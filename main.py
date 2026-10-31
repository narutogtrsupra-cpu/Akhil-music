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
    """Fetch track from Jamendo and download MP3 locally with strict null safety"""
    try:
        client_id = "5c6a51d8"
        search_url = f"https://api.jamendo.com/v3.0/tracks/?client_id={client_id}&format=json&limit=1&search={requests.utils.quote(query)}"
        
        response = requests.get(search_url, timeout=10)
        try:
            data = response.json()
        except Exception:
            raise ValueError("API did not return valid JSON.")
            
        if not data or not isinstance(data, dict):
            raise ValueError("Empty API response.")
            
        results = data.get("results")
        if not results or not isinstance(results, list):
            raise ValueError("No tracks found.")
            
        track = results[0]
        if not track or not isinstance(track, dict):
            raise ValueError("Invalid track data.")
            
        title = track.get("name", query)
        audio_url = track.get("audio")
        
        if not audio_url:
            raise ValueError("Direct download link missing.")
            
        # Download locally to ensure zero streaming format errors
        log.info("Downloading track locally: %s", title)
        audio_resp = requests.get(audio_url, timeout=20)
        if audio_resp.status_code != 200:
            raise ValueError("Failed to download audio file.")
            
        with open(SONG_FILE, "wb") as f:
            f.write(audio_resp.content)
            
        return SONG_FILE, title
    except Exception as exc:
        log.error("Download failed: %s", exc)
        raise ValueError(f"Could not download song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Secure Local Music Bot is online!\n"
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
        
        # Play local file directly into voice chat
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
