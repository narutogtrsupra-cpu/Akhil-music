import os
import asyncio
import logging
from threading import Thread
from flask import Flask

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
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
SESSION_STRING = os.environ["SESSION_STRING"]
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the host environment.")

# --- COOKIES SETUP FOR RENDER ---
cookies_content = os.getenv("COOKIES_TEXT")
cookies_path = "cookies.txt"

if cookies_content:
    with open(cookies_path, "w") as f:
        f.write(cookies_content)
    log.info("Cookies file successfully loaded from COOKIES_TEXT environment variable.")
else:
    log.warning("COOKIES_TEXT environment variable not found. YouTube might block requests if IP is flagged.")
# --------------------------------

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

SEARCH_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
    "noplaylist": True,
    "cookiefile": cookies_path if os.path.exists(cookies_path) else None,
}
TRACK_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "ignoreerrors": True,
    "cookiefile": cookies_path if os.path.exists(cookies_path) else None,
}

def find_audio(query: str):
    sources = [
        ("YouTube", f"ytsearch5:{query}"),
        ("SoundCloud", f"scsearch5:{query}"),
    ]
    for source_name, search_query in sources:
        log.info("Searching %s for: %s", source_name, query)
        try:
            with yt_dlp.YoutubeDL(SEARCH_OPTIONS) as search_ydl:
                search_info = search_ydl.extract_info(search_query, download=False)
            entries = (search_info or {}).get("entries") or []
        except Exception as exc:
            log.warning("%s search failed: %s", source_name, exc)
            continue

        if not entries:
            continue

        for entry in entries:
            if not entry:
                continue
            candidate_url = entry.get("webpage_url") or entry.get("url")
            if not candidate_url:
                continue
            if source_name == "YouTube" and not candidate_url.startswith(("http://", "https://")):
                candidate_url = f"https://www.youtube.com/watch?v={candidate_url}"
            try:
                with yt_dlp.YoutubeDL(TRACK_OPTIONS) as track_ydl:
                    info = track_ydl.extract_info(candidate_url, download=False)
                if not info or not info.get("url"):
                    continue
                title = info.get("title") or entry.get("title") or query
                page_url = info.get("webpage_url") or candidate_url
                log.info("Selected playable result from %s: %s", source_name, title)
                return info["url"], title, page_url
            except Exception as exc:
                log.warning("Skipping unavailable result: %s", exc)

    raise ValueError("Could not find a playable result on YouTube or SoundCloud.")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Music bot is online. Add me to a group and use /play song name.\n"
        "The linked user account must also be in the group and able to join voice chats."
    )

@bot.on_message(filters.command("play") & filters.group)
async def play_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /play song name")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"🔎 Searching for: {query}")
    try:
        audio_url, title, webpage_url = await asyncio.to_thread(find_audio, query)
        await calls.play(
            message.chat.id,
            MediaStream(audio_url, video_flags=MediaStream.Flags.IGNORE),
        )
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        await status.edit_text(f"Couldn't start playback. Error: `{str(exc)[:250]}`")

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    log.info("Music bot started")
    try:
        await asyncio.Event().wait()
    finally:
        await calls.stop()
        await user.stop()
        await bot.stop()

if __name__ == "__main__":
    bot.run(main())
