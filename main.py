import os
import asyncio
import logging
import gc
import random
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from pytgcalls.types.update import Update
import yt_dlp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("musicbot")

# --- WEB SERVICE PORT BINDER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

keep_alive()
# ---------------------------------------------

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
SESSION_STRING = os.environ["SESSION_STRING"]
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the host environment.")

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

# Structures for Queue & Modes
QUEUES = {}          # {chat_id: [{'file_path': str, 'title': str, 'duration': str, 'thumb': str, 'user': str}, ...]}
LOOP_MODES = {}      # {chat_id: False / True}
VOLUMES = {}         # {chat_id: int}
IDLE_TASKS = {}      # {chat_id: asyncio.Task}

def cleanup_memory():
    gc.collect()

def download_audio_track(query: str, index: int = 0):
    song_file = f"song_{index}.mp3"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'song_{index}',
        'writethumbnail': True,
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'},
            {'key': 'EmbedThumbnail'},
            {'key': 'FFmpegMetadata'}
        ],
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }

    search_queries = [f"scsearch1:{query}", f"ftymusic:{query}"]
    title = query
    duration_str = "03:45"
    thumb_path = None

    for search_query in search_queries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)
                if info and 'entries' in info and len(info['entries']) > 0:
                    info = info['entries'][0]
                
                title = info.get('title', query) if info else query
                dur_sec = info.get('duration', 225) if info else 225
                mins, secs = divmod(int(dur_sec), 60)
                duration_str = f"{mins:02d}:{secs:02d}"

            if os.path.exists(song_file):
                break
            for f in os.listdir('.'):
                if f.startswith(f'song_{index}.'):
                    os.rename(f, song_file)
                    break
            if os.path.exists(song_file):
                break
        except Exception as exc:
            log.warning("Source failed: %s", exc)

    if not os.path.exists(song_file):
        raise ValueError("Could not download song track.")

    for ext in ['.jpg', '.webp', '.png']:
        if os.path.exists(f"song_{index}{ext}"):
            thumb_path = f"song_{index}{ext}"
            break

    return os.path.abspath(song_file), title, duration_str, thumb_path

def get_control_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮", callback_data="cb_skip"),
            InlineKeyboardButton("⏸", callback_data="cb_pause_resume"),
            InlineKeyboardButton("⏹", callback_data="cb_stop"),
            InlineKeyboardButton("⏭", callback_data="cb_skip")
        ],
        [
            InlineKeyboardButton("🔀 Shuffle", callback_data="cb_shuffle"),
            InlineKeyboardButton("🔁 Loop", callback_data="cb_loop")
        ]
    ])

async def auto_leave_timer(chat_id):
    try:
        await asyncio.sleep(180)
        if chat_id in QUEUES and len(QUEUES[chat_id]) == 0:
            try:
                await calls.leave_group_call(chat_id)
            except Exception:
                pass
            await bot.send_message(chat_id, "💤 Left voice chat due to inactivity.")
    except asyncio.CancelledError:
        pass

async def play_next(chat_id):
    if chat_id in IDLE_TASKS:
        IDLE_TASKS[chat_id].cancel()

    if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
        current = QUEUES[chat_id][0]
        
        try:
            vol = VOLUMES.get(chat_id, 100)
            await calls.play(
                chat_id,
                MediaStream(current['file_path']),
            )
            
            caption = (
                f"▶️ **STARTED STREAMING**\n\n"
                f"✨ **Title** : {current['title']}\n"
                f"⏱ **Duration** : {current['duration']} Minutes\n"
                f"👤 **Requested By** : {current['user']}\n"
                f"🔊 **Volume** : {vol}%\n"
                f"🔁 **Loop Mode** : {'ON' if LOOP_MODES.get(chat_id, False) else 'OFF'}"
            )
            
            if current['thumb'] and os.path.exists(current['thumb']):
                await bot.send_photo(
                    chat_id,
                    photo=current['thumb'],
                    caption=caption,
                    reply_markup=get_control_markup()
                )
            else:
                await bot.send_message(
                    chat_id,
                    text=caption,
                    reply_markup=get_control_markup()
                )
        except Exception as exc:
            log.error(f"Playback error: {exc}")
            if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
                QUEUES[chat_id].pop(0)
            await play_next(chat_id)
    else:
        try:
            await calls.leave_group_call(chat_id)
        except Exception:
            pass
        cleanup_memory()
        IDLE_TASKS[chat_id] = asyncio.create_task(auto_leave_timer(chat_id))

@calls.on_update()
async def stream_end_handler(client, update: Update):
    update_str = str(type(update))
    if "Ended" in update_str or "Finished" in update_str or "Update" in update_str or "Stream" in update_str:
        chat_id = getattr(update, "chat_id", None)
        if chat_id and chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
            if not LOOP_MODES.get(chat_id, False):
                QUEUES[chat_id].pop(0)
            else:
                item = QUEUES[chat_id].pop(0)
                QUEUES[chat_id].append(item)
            await play_next(chat_id)

@bot.on_message(filters.command("start") & filters.private)
async def start_command(_, message):
    welcome_caption = (
        f"✨ **HeY {message.from_user.mention} !**\n\n"
        f"🔘 **THIS IS `NGS-MUSIC-BOT` 🎵 !**\n\n"
        f"▶️ **A FAST & POWERFUL TELEGRAM MUSIC PLAYER BOT WITH SOME AWESOME FEATURES.**\n\n"
        f"🔘 **CLICK ON THE HELP BUTTON TO GET INFORMATION ABOUT MY MODULES AND COMMANDS.**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD ME IN YOUR GROUP ➕", url=f"https://t.me/{message._client.me.username}?startgroup=true")],
        [InlineKeyboardButton("🛠 HELP COMMANDS", callback_data="cb_help")],
        [
            InlineKeyboardButton("🌙 OWNER", url="https://t.me/NGSAKHIL"),
            InlineKeyboardButton("📢 UPDATES", url="https://t.me/chilkamut")
        ],
        [InlineKeyboardButton("💬 SUPPORT", url="https://t.me/chilkamut")],
        [InlineKeyboardButton("💻 SOURCE CODE", url="https://github.com/")]
    ])

    try:
        await message.reply_photo(
            photo="start_img.jpg", 
            caption=welcome_caption,
            reply_markup=keyboard
        )
    except Exception:
        await message.reply_text(
            text=welcome_caption,
            reply_markup=keyboard
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
        file_path, title, duration, thumb = await asyncio.to_thread(download_audio_track, query, index)
        
        user_name = message.from_user.mention if message.from_user else "Admin"
        song_data = {
            'file_path': file_path,
            'title': title,
            'duration': duration,
            'thumb': thumb,
            'user': user_name
        }

        is_playing = len(QUEUES[message.chat.id]) > 0
        QUEUES[message.chat.id].append(song_data)

        if not is_playing or len(QUEUES[message.chat.id]) == 1:
            await status.delete()
            await play_next(message.chat.id)
        else:
            await status.edit_text(f"➕ Added to Queue: **{title}** (Position: {len(QUEUES[message.chat.id]) - 1})")
    except Exception as exc:
        log.exception("Playback failed")
        if hasattr(status, 'edit_text'):
            await status.edit_text(f"Error: `{str(exc)[:150]}`")

@bot.on_message(filters.command("play") & filters.group)
async def play_offline_command(_, message):
    if not message.reply_to_message or not message.reply_to_message.audio:
        await message.reply_text("Please **reply to an audio/mp3 file** with `/play`!")
        return

    status = await message.reply_text("📥 Loading offline track...")
    try:
        if message.chat.id not in QUEUES:
            QUEUES[message.chat.id] = []
            
        index = len(QUEUES[message.chat.id]) + 1
        song_file = f"offline_{index}.mp3"
        file_path = await message.reply_to_message.download(file_name=song_file)
        abs_path = os.path.abspath(file_path)
        audio_name = message.reply_to_message.audio.file_name or "Custom Audio"
        user_name = message.from_user.mention if message.from_user else "Admin"

        song_data = {
            'file_path': abs_path,
            'title': audio_name,
            'duration': "03:30",
            'thumb': None,
            'user': user_name
        }

        is_playing = len(QUEUES[message.chat.id]) > 0
        QUEUES[message.chat.id].append(song_data)

        if not is_playing or len(QUEUES[message.chat.id]) == 1:
            await status.delete()
            await play_next(message.chat.id)
        else:
            await status.edit_text(f"➕ Added offline track to Queue: **{audio_name}** (Position: {len(QUEUES[message.chat.id]) - 1})")
    except Exception as exc:
        await status.edit_text(f"Error: {exc}")

@bot.on_message(filters.command("shuffle") & filters.group)
async def shuffle_command(_, message):
    chat_id = message.chat.id
    if chat_id not in QUEUES or len(QUEUES[chat_id]) <= 2:
        await message.reply_text("❌ Not enough songs in queue to shuffle.")
        return
    
    current = QUEUES[chat_id].pop(0)
    random.shuffle(QUEUES[chat_id])
    QUEUES[chat_id].insert(0, current)
    await message.reply_text("🔀 Queue has been successfully shuffled!")

@bot.on_message(filters.command("loop") & filters.group)
async def loop_command(_, message):
    chat_id = message.chat.id
    current_status = LOOP_MODES.get(chat_id, False)
    LOOP_MODES[chat_id] = not current_status
    status_text = "ENABLED 🔂" if LOOP_MODES[chat_id] else "DISABLED ❌"
    await message.reply_text(f"🔁 Loop mode is now **{status_text}**")

@bot.on_message(filters.command("volume") & filters.group)
async def volume_command(_, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/volume [1-200]` (e.g., `/volume 150`)")
        return
    
    vol = int(message.command[1])
    if vol < 1 or vol > 200:
        await message.reply_text("❌ Volume must be between 1 and 200.")
        return

    chat_id = message.chat.id
    VOLUMES[chat_id] = vol
    try:
        await calls.change_volume(chat_id, vol)
        await message.reply_text(f"🔊 Volume successfully updated to **{vol}%**")
    except Exception as exc:
        await message.reply_text(f"Error updating volume: {exc}")

@bot.on_message(filters.command("queue") & filters.group)
async def queue_command(_, message):
    chat_id = message.chat.id
    if chat_id not in QUEUES or len(QUEUES[chat_id]) == 0:
        await message.reply_text("📭 The music queue is currently empty.")
        return
    
    text = "🎵 **Current Music Queue:**\n\n"
    for i, song in enumerate(QUEUES[chat_id]):
        if i == 0:
            text += f"▶️ **Now Playing:** {song['title']} (Req by: {song['user']})\n\n"
        else:
            text += f"{i}. {song['title']} (Req by: {song['user']})\n"
    await message.reply_text(text)

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
        if message.chat.id in LOOP_MODES:
            LOOP_MODES[message.chat.id] = False
        await calls.leave_group_call(message.chat.id)
        cleanup_memory()
        await message.reply_text("⏹ Cleared queue, stopped playback, and left the voice chat.")
    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

@bot.on_callback_query()
async def callback_handler(_, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "cb_skip":
        if chat_id in QUEUES and len(QUEUES[chat_id]) > 0:
            QUEUES[chat_id].pop(0)
        await play_next(chat_id)
        await callback_query.answer("Skipped to next song!")
    elif data == "cb_pause_resume":
        try:
            await calls.pause(chat_id)
            await callback_query.answer("Paused!")
        except Exception:
            try:
                await calls.resume(chat_id)
                await callback_query.answer("Resumed!")
            except Exception:
                await callback_query.answer("Action failed.")
    elif data == "cb_stop":
        if chat_id in QUEUES:
            QUEUES[chat_id].clear()
        await calls.leave_group_call(chat_id)
        await callback_query.answer("Stopped playback!")
    elif data == "cb_loop":
        current = LOOP_MODES.get(chat_id, False)
        LOOP_MODES[chat_id] = not current
        await callback_query.answer(f"Loop Mode: {'ON' if LOOP_MODES[chat_id] else 'OFF'}")
    elif data == "cb_shuffle":
        if chat_id in QUEUES and len(QUEUES[chat_id]) > 2:
            current = QUEUES[chat_id].pop(0)
            random.shuffle(QUEUES[chat_id])
            QUEUES[chat_id].insert(0, current)
            await callback_query.answer("Queue shuffled!")
        else:
            await callback_query.answer("Not enough songs to shuffle!", show_alert=True)
    elif data == "cb_help":
        await callback_query.answer(
            "Commands:\n• /song [name] - Play online\n• /play - Play offline (reply to audio)\n• /queue - View list\n• /skip - Next track",
            show_alert=True
        )

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    log.info("NGS-MUSIC-BOT started successfully")
    try:
        await asyncio.Event().wait()
    finally:
        await calls.stop()
        await user.stop()
        await bot.stop()

if __name__ == "__main__":
    bot.run(main())
