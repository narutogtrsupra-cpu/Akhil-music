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
    """Directly fetch music using JioSaavn's official public API search endpoint"""
    try:
        search_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(search_url, headers=headers, timeout=10)
        data = response.json()
        
        songs = data.get("songs", {}).get("data", [])
        if not songs:
            raise ValueError("No songs found.")
            
        # Get the song ID of the first match
        song = songs[0]
        song_id = song.get("id")
        title = song.get("title", query).replace("&quot;", "'").replace("&amp;", "&")
        
        # Fetch direct media stream URL using the official song details endpoint
        details_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0&_format=json&pids={song_id}"
        details_resp = requests.get(details_url, headers=headers, timeout=10)
        details_data = details_resp.json()
        
        song_info = details_data.get(song_id, {})
        audio_url = song_info.get("media_url") or song_info.get("encrypted_media_url")
        
        if not audio_url:
            # Fallback format mapping if needed
            media_url = song_info.get("media_preview_url", "")
            if media_url:
                audio_url = media_url.replace("_96_p.mp4", "_320.mp4")
                
        if not audio_url:
            raise ValueError("Could not extract audio stream link.")
            
        log.info("Found stable track: %s", title)
        return audio_url, title
    except Exception as exc:
        log.error("JioSaavn search failed: %s", exc)
        raise ValueError("Could not fetch song. Try a different name.")

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
            MediaStream(audio_url, video_flags=MediaStream.Flags.IGNORE),
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
