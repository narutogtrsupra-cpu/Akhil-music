import os
import asyncio
import logging
import tempfile
from pathlib import Path
from html import escape
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls, filters as call_filters
from pytgcalls.types import MediaStream, StreamEnded, Device
from pyrogram.enums import ParseMode
from player import Player, timestamp, progress, discard
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

def download_audio_track(query):
    directory = tempfile.mkdtemp(prefix='music-')
    options = {
        'format': 'bestaudio/best', 'outtmpl': f'{directory}/audio.%(ext)s',
        'writethumbnail': True, 'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'},
            {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'},
        ],
    }
    try:
        for source in [f'ytsearch1:{query}', f'scsearch1:{query}']:
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(source, download=True)
                    if info and 'entries' in info:
                        info = next((entry for entry in info['entries'] if entry), None)
                audio = Path(directory) / 'audio.mp3'
                if info and audio.is_file():
                    thumbs = list(Path(directory).glob('*.jpg'))
                    return dict(file_path=str(audio), title=info.get('title') or query,
                                duration=int(info.get('duration') or 0), directory=directory,
                                thumb=str(thumbs[0]) if thumbs else info.get('thumbnail'))
            except Exception:
                log.warning('Audio source failed', exc_info=True)
                for file in Path(directory).iterdir():
                    file.unlink()
        raise ValueError('Could not download song. Try another title or upload audio.')
    except BaseException:
        discard({'directory': directory})
        raise


def get_control_markup(paused=False):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('↺ Restart', callback_data='cb_restart'),
         InlineKeyboardButton('▶ Resume' if paused else '⏸ Pause', callback_data='cb_toggle')],
        [InlineKeyboardButton('⏹ Stop', callback_data='cb_stop'),
         InlineKeyboardButton('⏭ Skip', callback_data='cb_skip')],
        [InlineKeyboardButton('🔀 Shuffle', callback_data='cb_shuffle'),
         InlineKeyboardButton('🔁 Loop queue', callback_data='cb_loop')],
    ])


def caption(state):
    song = state.queue[0]
    return (
        f"{'⏸ PAUSED' if state.paused else '▶ NOW PLAYING'}\n\n"
        f"<b>{escape(song['title'][:180])}</b>\n"
        f"Requested by: {escape(song['user'][:100])}\n"
        f"Volume: {state.volume}% · Queue loop: {'ON' if state.loop else 'OFF'}\n\n"
        f"{progress(state.position(), song['duration'])}\n"
        f"Up next: {len(state.queue) - 1} song(s)"
    )


async def announce(chat, state):
    kwargs = dict(reply_markup=get_control_markup(state.paused), parse_mode=ParseMode.HTML)
    if state.queue[0].get('thumb'):
        try:
            return await bot.send_photo(chat, photo=state.queue[0]['thumb'], caption=caption(state), **kwargs)
        except Exception:
            log.warning('Thumbnail unavailable; sending text card', exc_info=True)
    return await bot.send_message(chat, caption(state), **kwargs)


async def refresh(state):
    kwargs = dict(reply_markup=get_control_markup(state.paused), parse_mode=ParseMode.HTML)
    if state.card.photo:
        await state.card.edit_caption(caption(state), **kwargs)
    else:
        await state.card.edit_text(caption(state), **kwargs)


player = Player(calls, lambda path: MediaStream(path, video_flags=MediaStream.Flags.IGNORE), announce, refresh)


@calls.on_update(call_filters.stream_end(StreamEnded.Type.AUDIO, Device.MICROPHONE))
async def stream_end_handler(client, update):
    state = player.chats[update.chat_id]
    current = state.queue[0] if state.queue else None
    if current is not None:
        await player.advance(update.chat_id, natural=True, expected=current)


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

@bot.on_message(filters.command(['song', 'play']) & filters.group)
async def song_command(_, message):
    offline = message.reply_to_message and message.reply_to_message.audio
    if len(message.command) < 2 and not offline:
        await message.reply_text('Use /song <name> or reply to an audio file with /play.')
        return
    state = player.chats[message.chat.id]
    generation = state.generation
    status = await message.reply_text('📥 Loading song…')
    track = None
    try:
        async with state.requests:
            if generation != state.generation:
                await status.edit_text('Request cancelled by /stop.')
                return
            if offline:
                directory = tempfile.mkdtemp(prefix='music-')
                track = {'directory': directory}
                path = await message.reply_to_message.download(file_name=f'{directory}/audio')
                if not path:
                    raise ValueError('Audio download failed.')
                track.update(file_path=os.path.abspath(path), title=offline.title or offline.file_name or 'Audio',
                             duration=offline.duration or 0, thumb=None)
                if offline.thumbs:
                    try:
                        track['thumb'] = await bot.download_media(offline.thumbs[-1].file_id,
                                                                  file_name=f'{directory}/thumb.jpg')
                    except Exception:
                        log.warning('Could not download thumbnail', exc_info=True)
            else:
                track = await asyncio.to_thread(download_audio_track, ' '.join(message.command[1:]))
            track['user'] = message.from_user.first_name if message.from_user else 'Admin'
            position = await player.enqueue(message.chat.id, track, generation)
            track = None
        await status.edit_text('Request cancelled by /stop.' if position is None else
                               f'➕ Added to queue · position {position}' if position else
                               'Playback request processed. Use /queue to view the player.')
    except Exception as exc:
        if track:
            discard(track)
        log.exception('Song request failed')
        await status.edit_text(f'Could not load song: {str(exc)[:150]}', parse_mode=ParseMode.DISABLED)


@bot.on_message(filters.command(['stop', 'pause', 'resume', 'skip', 'next', 'restart',
                                  'shuffle', 'loop', 'volume']) & filters.group)
async def control_command(_, message):
    action = message.command[0].lower()
    action = 'skip' if action == 'next' else action
    volume = None
    if action == 'volume':
        if len(message.command) != 2 or not message.command[1].isdigit() or not 1 <= int(message.command[1]) <= 200:
            await message.reply_text('Usage: /volume <1-200>')
            return
        volume = int(message.command[1])
    try:
        await message.reply_text(await player.control(message.chat.id, action, volume))
    except Exception:
        log.exception('Control failed')
        await message.reply_text('Could not control playback. Check the voice chat.')


@bot.on_message(filters.command('queue') & filters.group)
async def queue_command(_, message):
    state = player.chats[message.chat.id]
    if not state.queue:
        await message.reply_text('The music queue is empty.')
        return
    lines = ['🎵 Music queue:']
    for index, song in enumerate(state.queue[:25]):
        label = 'Paused' if state.paused else 'Playing'
        lines.append(f"{label if index == 0 else index}: {song['title'][:100]} ({timestamp(song['duration'])})")
    if len(state.queue) > 25:
        lines.append(f'…and {len(state.queue) - 25} more')
    await message.reply_text('\n'.join(lines), parse_mode=ParseMode.DISABLED)


@bot.on_callback_query()
async def callback_handler(_, callback_query):
    if callback_query.data == 'cb_help':
        await callback_query.answer('Commands: /song <name>, /play (reply to audio), /pause, /resume, '
                                    '/skip, /stop, /restart, /queue, /shuffle, /loop, /volume <1-200>', show_alert=True)
        return
    action = callback_query.data.removeprefix('cb_')
    if action not in {'restart', 'toggle', 'stop', 'skip', 'shuffle', 'loop'}:
        await callback_query.answer('Use the controls on the latest song card.')
        return
    try:
        result = await player.control(callback_query.message.chat.id, action,
                                      card_id=callback_query.message.id)
        await callback_query.answer(result)
    except Exception:
        log.exception('Button action failed')
        await callback_query.answer('Action failed. Check the voice chat.', show_alert=True)


async def main():
    keep_alive()
    await bot.start()
    await user.start()
    await calls.start()
    log.info('NGS-MUSIC-BOT started successfully')
    try:
        await asyncio.Event().wait()
    finally:
        for state in player.chats.values():
            if state.ticker:
                state.ticker.cancel()
        await calls.stop()
        await user.stop()
        await bot.stop()


if __name__ == '__main__':
    bot.run(main())
