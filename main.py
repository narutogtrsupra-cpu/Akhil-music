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
    """Search Archive.org for stable, direct MP3 streams with zero blocks"""
    try:
        search_url = f"https://archive.org/advancedsearch.php?q={requests.utils.quote(query)}+AND+mediatype:audio&fl[]=identifier&fl[]=title&rows=1&output=json"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(search_url, headers=headers, timeout=10)
        data = response.json()
        
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            raise ValueError("No tracks found.")
            
        doc = docs[0]
        identifier = doc.get("identifier")
        title = doc.get("title", query)
        
        meta_url = f"https://archive.org/metadata/{identifier}"
        meta_resp = requests.get(meta_url, headers=headers, timeout=10)
        meta_data = meta_resp.json()
        
        files = meta_data.get("files", [])
        mp3_file = None
        for file in files:
            if file.get("name", "").endswith(".mp3"):
                mp3_file = file.get("name")
                break
                
        if not mp3_file and files:
            mp3_file = files[0].get("name")
            
        if not identifier or not mp3_file:
            raise ValueError("Could not extract audio file link.")
            
        audio_url = f"https://archive.org/download/{identifier}/{mp3_file}"
        log.info("Found stable Archive.org track: %s", title)
        return audio_url, title
    except Exception as exc:
        log.error("Search failed: %s", exc)
        raise ValueError(f"Could not fetch song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Stable Music Bot is online!\n"
        "Use `/play [song name]` to stream music smoothly without any errors."
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/play [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"🔎 Searching archive: {query}")
    try:
        audio_url, title = await asyncio.to_thread(find_audio, query)
        await calls.play(
            message.chat.id,
            MediaStream(
                audio_url,
                format=MediaStream.AudioFormats.opus,
            ),
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
