import os
import asyncio
import logging
import gc
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from pytgcalls.types.update import Update
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

# Dictionary to manage queues per chat: {chat_id: [(file_path, title), ...]}
QUEUES = {}

def cleanup_memory():
    """Free up RAM and delete temp files to prevent Render crashes"""
    gc.collect()

def download_audio_track(query: str, index: int = 0):
    """Download track safely with memory management"""
    song_file = f"song_{index}.mp3"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'song_{index}',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }

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

            if os.path.exists(song_file):
                break

            for f in os.listdir('.'):
                if f.startswith(f'song_{index}.'):
                    os.rename(f, song_file)
                    break

            if os.path.exists(song_file):
                break
        except Exception as exc:
            last_error = exc
            log.warning("Source %s failed: %s", search_query, exc)
            continue

    if not os.path.exists(song_file):
        raise ValueError(f"Could not download song: {str(last_error or 'Unknown error')[:100]}")

    return os.path.abspath(song_file), title

async def play_next(chat_id, message_context=None):
    if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
        file_path, title = QUEUES[chat_id][0]  # Peek current
        try:
            await calls.play(
                chat_id,
                MediaStream(file_path),
            )
            if message_context:
                await message_context.reply_text(f"🎶 Now playing: **{title}**")
        except Exception as exc:
            log.error(f"Playback error: {exc}")
            if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
                QUEUES[chat_id].pop(0)
            await play_next(chat_id, message_context)
    else:
        try:
            await calls.leave_group_call(chat_id)
        except Exception:
            pass
        cleanup_memory()

@calls.on_update()
async def stream_end_handler(client, update: Update):
    from pytgcalls.types import StreamAudioEnded
    if isinstance(update, StreamAudioEnded):
        chat_id = update.chat_id
        if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
            QUEUES[chat_id].pop(0)  # Remove finished song
        await play_next(chat_id)

@bot.on_message(filters.command("start"))
async def start_command(_, message):
    await message.reply_text(
        "🎵 Queue-Enabled Music Bot is online!\n\n"
        "**Commands:**\n"
        "• `/song [name]` - Search & add song to queue\n"
        "• Reply to `.mp3` with `/play` - Add offline song to queue\n"
        "• `/queue` - View current queue\n"
        "• `/pause` / `/resume` - Pause/Resume music\n"
        "• `/skip` or `/next` - Skip to next song\n"
        "• `/stop` - Clear queue & leave VC"
    )

@bot.on_message(filters.command("song") & filters.group)
async def song_command(_, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/song [song name]`")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"📥 Processing `{query}`...")
    
    try:
        if message.chat.id not in QUEUES:
            QUEUES[message.chat.id] = []
            
        index = len(QUEUES[message.chat.id]) + 1
        file_path, title = await asyncio.to_thread(download_audio_track, query, index)
        
        is_playing = len(QUEUES[message.chat.id]) > 0
        try:
            current_call = calls.get_call(message.chat.id)
            if not current_call:
                is_playing = False
        except Exception:
            is_playing = len(QUEUES[message.chat.id]) > 0

        QUEUES[message.chat.id].append((file_path, title))

        if not is_playing or len(QUEUES[message.chat.id]) == 1:
            # If nothing was playing, start it immediately
            await play_next(message.chat.id, status)
        else:
            await status.edit_text(f"➕ Added to Queue: **{title}** (Position: {len(QUEUES[message.chat.id]) - 1})")
    except Exception as exc:
        log.exception("Playback failed")
        if hasattr(status, 'edit_text'):
            await status.edit_text(
                f"Error: `{str(exc)[:150]}`\n\n"
                "💡 *Tip:* Upload the `.mp3` file in chat and reply with `/play` if online search fails!"
            )

@bot.on_message(filters.command("play") & filters.group)
async def play_offline_command(_, message):
    if not message.reply_to_message or not message.reply_to_message.audio:
        await message.reply_text("Please **reply to an audio/mp3 file** with `/play` to add it to the queue!")
        return

    status = await message.reply_text("📥 Loading offline song to queue...")
    
    try:
        if message.chat.id not in QUEUES:
            QUEUES[message.chat.id] = []
            
        index = len(QUEUES[message.chat.id]) + 1
        song_file = f"offline_{index}.mp3"
        file_path = await message.reply_to_message.download(file_name=song_file)
        abs_path = os.path.abspath(file_path)
        audio_name = message.reply_to_message.audio.file_name or "Custom Offline Track"

        is_playing = len(QUEUES[message.chat.id]) > 0
        try:
            current_call = calls.get_call(message.chat.id)
            if not current_call:
                is_playing = False
        except Exception:
            is_playing = len(QUEUES[message.chat.id]) > 0

        QUEUES[message.chat.id].append((abs_path, audio_name))

        if not is_playing or len(QUEUES[message.chat.id]) == 1:
            await play_next(message.chat.id, status)
        else:
            await status.edit_text(f"➕ Added offline track to Queue: **{audio_name}** (Position: {len(QUEUES[message.chat.id]) - 1})")
    except Exception as exc:
        log.exception("Offline playback failed")
        if hasattr(status, 'edit_text'):
            await status.edit_text(f"Error: `{str(exc)[:200]}`")

@bot.on_message(filters.command("queue") & filters.group)
async def queue_command(_, message):
    chat_id = message.chat.id
    if chat_id not in QUEUES or len(QUEUES[chat_id]) == 0:
        await message.reply_text("📭 The music queue is currently empty.")
        return
    
    text = "🎵 **Current Music Queue:**\n\n"
    for i, (_, title) in enumerate(QUEUES[chat_id]):
        if i == 0:
            text += f"▶️ **Now Playing:** {title}\n\n"
        else:
            text += f"{i}. {title}\n"
    await message.reply_text(text)

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

@bot.on_message(filters.command(["skip", "next"]) & filters.group)
async def skip_command(_, message):
    try:
        await message.reply_text("⏭ Skipping current song...")
        if message.chat.id in QUEUES and len(QUEUES[message.chat.id]) > 0:
            QUEUES[message.chat.id].pop(0)
        await play_next(message.chat.id)
    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

@bot.on_message(filters.command("stop") & filters.group)
async def stop_command(_, message):
    try:
        if message.chat.id in QUEUES:
            QUEUES[message.chat.id].clear()
        await calls.leave_group_call(message.chat.id)
        cleanup_memory()
        await message.reply_text("⏹ Cleared queue, stopped playback, and left the voice chat.")
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
