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
    """Download track using SoundCloud and Archive.org to fully avoid YouTube"""
    if os.path.exists(SONG_FILE):
        try:
            os.remove(SONG_FILE)
        except Exception:
            pass

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

    # Only use non-YouTube extractors to avoid bot checks entirely
    search_queries = [
        f"scsearch1:{query}",
        f"ftymusic:{query}"
    ]

    last_error = None
    title = query

    for search_query in search_queries:
        try:
            log.info("Trying safe search query: %s", search_query)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)
                if info and 'entries' in info and len(info['entries']) > 0:
                    info = info['entries'][0]
                title = info.get('title', query) if info else query

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
        "🎵 Secure Music Bot is online!\n\n"
        "**Commands:**\n"
        "• `/song [name]` - Download & play song\n"
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
    status = await message.reply_text(f"📥 Downloading `{query}`...")
    
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
