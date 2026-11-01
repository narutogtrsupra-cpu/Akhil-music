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
    """Download track optimized for speed with multi-source fallback"""
    if os.path.exists(SONG_FILE):
        os.remove(SONG_FILE)

    # Use a faster, smaller audio format target to speed up download and conversion
    ydl_opts = {
        'format': 'worstaudio/worst',  
        'outtmpl': 'current_song',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '96',  # Lower quality = faster download and encoding
        }],
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }

    search_queries = [
        f"scsearch1:{query}",
        f"ytsearch1:{query}"
    ]

    last_error = None
    title = query

    for search_query in search_queries:
        try:
            log.info("Trying fast search query: %s", search_query)
            current_opts = ydl_opts.copy()
            if search_query.startswith("ytsearch1:"):
                current_opts['extractor_args'] = {
                    'youtube': {
                        'player-client': ['android', 'web']
                    }
                }

            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)
                if 'entries' in info:
                    info = info['entries'][0]
                title = info.get('title', query)

            if os.path.exists(SONG_FILE):
                break
            
            for f in os.listdir('.'):
                if f.startswith('current_song.'):
                    os.rename(f, SONG_FILE)
                    break

            if os.path.exists(SONG_FILE):
                break
        except Exception as exc:
            last_error = exc
            log.warning("Source %s failed: %s", search_query, exc)
            continue

    if not os.path.exists(SONG_FILE):
        raise ValueError(f"Could not download song: {str(last_error or 'Unknown error')[:100]}")

    return os.path.abspath(SONG_FILE), title

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Fast Music Bot is online!\n"
        "Use `/song [name]` to stream music with reduced latency."
    )

@bot.on_message(filters.command("song") & filters.group)
async def song_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/song [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"⚡ Fetching `{query}`...")
    
    try:
        file_path, title = await asyncio.to_thread(download_audio_track, query)
        
        # Stream the optimized local file instantly
        await calls.play(
            message.chat.id,
            MediaStream(file_path),
        )
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        if hasattr(status, 'edit_text'):
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
