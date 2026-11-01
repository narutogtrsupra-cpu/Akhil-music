import os
import asyncio
import logging
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
import yt_dlp

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
    """Use yt-dlp to download the track locally as an MP3 file"""
    try:
        # Remove old song file if it exists
        if os.path.exists(SONG_FILE):
            os.remove(SONG_FILE)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'current_song',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }

        search_query = f"ytsearch1:{query}"
        log.info("Downloading local track via yt-dlp for: %s", query)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=True)
            if 'entries' in info:
                info = info['entries'][0]
            title = info.get('title', query)

        if not os.path.exists(SONG_FILE):
            # Check if it saved with a different extension before converting
            for f in os.listdir('.'):
                if f.startswith('current_song.'):
                    os.rename(f, SONG_FILE)
                    break

        if not os.path.exists(SONG_FILE):
            raise ValueError("Failed to save audio file locally.")

        return SONG_FILE, title
    except Exception as exc:
        log.error("Download failed: %s", exc)
        raise ValueError(f"Could not download song: {str(exc)[:100]}")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Local yt-dlp Music Bot is online!\n"
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
