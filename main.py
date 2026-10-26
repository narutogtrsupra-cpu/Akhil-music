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
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
SESSION_STRING = os.environ["SESSION_STRING"]
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN (or TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN / TOKEN) in the host environment.")

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

# Search metadata first, then extract each result individually. This lets us skip
# tracks that are unavailable or DRM-protected and try the next source.
SEARCH_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
    "noplaylist": True,
}
TRACK_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "ignoreerrors": True,
}


def find_audio(query: str):
    """Try YouTube search first, then SoundCloud; skip unplayable results."""
    sources = [
        ("YouTube", f"ytsearch5:{query}"),
        ("SoundCloud", f"scsearch5:{query}"),
    ]
    failures = []

    for source_name, search_query in sources:
        log.info("Searching %s for: %s", source_name, query)
        try:
            with yt_dlp.YoutubeDL(SEARCH_OPTIONS) as search_ydl:
                search_info = search_ydl.extract_info(search_query, download=False)
            entries = (search_info or {}).get("entries") or []
        except Exception as exc:
            log.warning("%s search failed: %s", source_name, exc)
            failures.append(f"{source_name} search failed")
            continue

        if not entries:
            log.warning("No results from %s", source_name)
            failures.append(f"no {source_name} results")
            continue

        for entry in entries:
            if not entry:
                continue
            candidate_url = entry.get("webpage_url") or entry.get("url")
            if not candidate_url:
                continue
            # Flat search entries can contain an ID instead of a full URL.
            if source_name == "YouTube" and not candidate_url.startswith(("http://", "https://")):
                candidate_url = f"https://www.youtube.com/watch?v={candidate_url}"
            try:
                with yt_dlp.YoutubeDL(TRACK_OPTIONS) as track_ydl:
                    info = track_ydl.extract_info(candidate_url, download=False)
                if not info or not info.get("url"):
                    log.warning("Skipping unplayable %s result: %s", source_name, entry.get("title", "unknown title"))
                    continue
                title = info.get("title") or entry.get("title") or query
                page_url = info.get("webpage_url") or candidate_url
                log.info("Selected playable result from %s: %s", source_name, title)
                return info["url"], title, page_url
            except Exception as exc:
                # Do not log the resolved media URL; it can contain temporary tokens.
                log.warning("Skipping unavailable/DRM-protected %s result %r: %s", source_name, entry.get("title", "unknown title"), exc)

    raise ValueError(
        "Could not find a playable result on YouTube or SoundCloud. "
        "Try another song title, or check whether the host can reach these services."
    )


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
    status = await message.reply_text(f"🔎 Searching YouTube and SoundCloud for: {query}")
    try:
        audio_url, title, webpage_url = await asyncio.to_thread(find_audio, query)
        log.info("Starting playback for chat %s: %s", message.chat.id, title)
        await calls.play(
            message.chat.id,
            MediaStream(audio_url, video_flags=MediaStream.Flags.IGNORE),
        )
        log.info("PyTgCalls play() returned for chat %s", message.chat.id)
        await status.edit_text(f"🎶 Now playing: **{title}**")
    except Exception as exc:
        log.exception("Playback failed")
        await status.edit_text(
            "Couldn't start playback. Confirm a voice chat is active, the linked user account "
            "is in the group, and FFmpeg is available on the host. "
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
