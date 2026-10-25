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
    # Read search results as metadata first; then test each track separately.
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
}


def find_audio(query: str):
    """Return the first playable SoundCloud result, skipping DRM/unavailable tracks."""
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            search = ydl.extract_info(f"scsearch5:{query}", download=False)
        except Exception as exc:
            raise ValueError(f"SoundCloud search failed: {exc}") from exc

        entries = (search or {}).get("entries") or []
        if not entries:
            raise ValueError("No matching songs were found on SoundCloud.")

        for entry in entries:
            if not entry:
                continue

            candidate_url = entry.get("webpage_url") or entry.get("url")
            if not candidate_url:
                continue

            try:
                info = ydl.extract_info(candidate_url, download=False)
                if not info or not info.get("url"):
                    log.warning("Skipping unavailable result: %s", entry.get("title", candidate_url))
                    continue

                return (
                    info["url"],
                    info.get("title") or entry.get("title") or query,
                    info.get("webpage_url") or candidate_url,
                )
            except Exception as exc:
                log.warning(
                    "Skipping unavailable/DRM-protected SoundCloud result %r: %s",
                    entry.get("title") or candidate_url,
                    exc,
                )

    raise ValueError(
        "No playable SoundCloud result found. The search results may be DRM-protected "
        "or unavailable. Try a different song title."
    )

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
        
        await calls.play(
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

    try:
        await asyncio.Event().wait()
    finally:
        await calls.stop()
        await user.stop()
        await bot.stop()

if __name__ == "__main__":
    bot.run(main())
            
