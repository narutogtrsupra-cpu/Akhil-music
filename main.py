import os
import asyncio
import logging

from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
import yt_dlp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
SESSION_STRING = os.environ["SESSION_STRING"]

# Bot receives commands; the logged-in user account joins and streams voice chats.
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)
user = Client(
    "music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)
calls = PyTgCalls(user)

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "ytsearch1",
    "extractor_args": {
        "youtube": {
            "player_client": ["android_vr"]
        }
    }
}

def find_audio(query: str):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            entries = info.get("entries") or []
            if not entries:
                raise ValueError("No matching song was found.")
            info = entries[0]
        return info["url"], info.get("title", query), info.get("webpage_url", "")

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Music bot is online. Add me to a group and use /play song name.\\n"
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
        
        calls.play(
    message.chat.id,
    MediaStream(audio_url, video_flags=MediaStream.Flags.IGNORE)
)
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        await status.edit_text(
            "Couldn't start playback. Make sure the linked user account is in this "
            "group, a voice chat is active, and the hosting environment supports FFmpeg. "
            f"Error: `{str(exc)[:250]}`"
        )

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    log.info("Music bot started")
    # Keep the process alive while Pyrogram handles incoming messages.
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
