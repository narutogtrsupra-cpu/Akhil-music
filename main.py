import os
import asyncio
import logging
import tempfile
import time
import secrets
import sys
from pathlib import Path
from html import escape
from threading import Thread
from flask import Flask

# Automatically load static ffmpeg for pytgcalls
import static_ffmpeg
static_ffmpeg.add_paths()

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from pytgcalls import PyTgCalls, filters as call_filters
from pytgcalls.types import MediaStream, StreamEnded, Device
from pyrogram.enums import ParseMode, ChatMemberStatus
from player import Player, timestamp, progress, discard
from storage import Storage
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
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the host environment.")

bot = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
calls = PyTgCalls(user)

def download_audio_track(query, direct=False):
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
        sources = [query] if direct else [f'ytsearch1:{query}', f'scsearch1:{query}']
        for source in sources:
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
                                source_url=info.get('webpage_url') if info.get('webpage_url', '').startswith(('https://', 'http://')) else None,
                                thumb=str(thumbs[0]) if thumbs else info.get('thumbnail'))
            except Exception:
                log.warning('Audio source failed', exc_info=True)
                for file in Path(directory).iterdir():
                    file.unlink()
        raise ValueError('Could not download song. Try another title or upload audio.')
    except BaseException:
        discard({'directory': directory})
        raise


def download_video_track(query, direct=False):
    directory = tempfile.mkdtemp(prefix='music-')
    try:
        options = {'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                   'merge_output_format': 'mp4', 'outtmpl': f'{directory}/video.%(ext)s',
                   'quiet': True, 'no_warnings': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query if direct else f'ytsearch1:{query}', download=True)
            if info and 'entries' in info:
                info = next((entry for entry in info['entries'] if entry), None)
        files = [p for p in Path(directory).glob('video.*') if p.suffix.lower() in ('.mp4', '.mkv', '.webm')]
        if not info or not files:
            raise ValueError('Could not download video.')
        url = info.get('webpage_url') or ''
        return dict(file_path=str(files[0]), title=info.get('title') or query,
                    duration=int(info.get('duration') or 0), directory=directory,
                    source_url=url if url.startswith(('http://', 'https://')) else None,
                    thumb=info.get('thumbnail'), video=True)
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
        [InlineKeyboardButton('🗳 Vote to skip', callback_data='cb_vote')],
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


def make_stream(track, offset=0):
    return MediaStream(track['file_path'], video_flags=MediaStream.Flags.AUTO_DETECT if track.get('video') else MediaStream.Flags.IGNORE,
                       ffmpeg_parameters=f'-ss {int(offset)}' if offset else None)


player = Player(calls, make_stream, announce, refresh)
store = Storage(os.environ.get('MUSIC_DB_PATH', 'music.sqlite3'))
searches = {}
restart_requested = asyncio.Event()

COMMANDS = [
    ('start', '🚀 Start bot / main menu'), ('play', 'Play music'), ('vplay', 'Play video'),
    ('pause', '⏸ Pause stream'), ('resume', '▶ Resume music'), ('skip', '⏭ Skip track'),
    ('stop', '⏹ Stop playing'), ('end', '🛑 End session'), ('replay', '🔄 Replay track'),
    ('queue', '📜 View queue'), ('shuffle', '🔀 Shuffle queue'), ('seek', '⏱ Seek time'),
    ('loop', '🔁 Loop queue'), ('settings', '⚙ Bot settings'), ('autoplay', '✨ Autoplay toggle'),
    ('auth', '🔐 Authorize user'), ('mode', '🎛 Control mode'), ('volume', '🔊 Set volume'),
    ('reboot', '🔄 Reboot bot'), ('reload', '♻ Reload bot code'), ('restart', '⚡ Restart bot worker'),
    ('speed', '🚀 Check ping'), ('clean', '🧹 Clear expired search cache'),
]

HELP = ('Start a group voice chat, then use /play <name or URL> or /vplay <name or URL>. '
        'Reply to an audio or video with /play or /vplay. Controls: /pause /resume /skip '
        '/stop /end /replay /queue /shuffle /seek <time> /loop /volume <1-200>. '
        'Group admins: /settings, /autoplay on|off, /mode admin|all, /auth (reply or user ID). '
        'More: /search /voteskip /playlist /remove /clearqueue /votethreshold.')


def search_tracks(query):
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True,
                           'noplaylist': True}) as ydl:
        result = ydl.extract_info(f'ytsearch5:{query}', download=False)
    entries = []
    for item in (result or {}).get('entries', []):
        if not item or not item.get('id'):
            continue
        video_id = item['id']
        # YouTube IDs have a limited alphabet; never expose an arbitrary URL to the downloader.
        if len(video_id) != 11 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in video_id):
            continue
        entries.append({'title': item.get('title') or 'Untitled',
                        'url': f'https://www.youtube.com/watch?v={video_id}',
                        'duration': int(item.get('duration') or 0)})
    return entries


async def is_admin(chat, user_id):
    if not user_id:
        return False
    try:
        member = await bot.get_chat_member(chat, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        log.warning('Could not check group administrator', exc_info=True)
        return False


async def may_control(chat, user_id):
    restricted, _ = store.settings(chat)
    return not restricted or (user_id and store.is_authorized(chat, user_id)) or await is_admin(chat, user_id)


def parse_seek(value):
    parts = value.split(':')
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError('Use /seek 1:30 or /seek 90.')
    if any(int(part) >= 60 for part in parts[1:]):
        raise ValueError('Minutes and seconds after a colon must be below 60.')
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds



@calls.on_update(call_filters.stream_end(StreamEnded.Type.AUDIO, Device.MICROPHONE))
async def stream_end_handler(client, update):
    state = player.chats[update.chat_id]
    current = state.queue[0] if state.queue else None
    if current is not None:
        generation = state.generation
        result = await player.advance(update.chat_id, natural=True, expected=current)
        if (result == 'Queue finished.' and generation == state.generation and not state.queue
                and not state.loop and store.autoplay_enabled(update.chat_id)):
            asyncio.create_task(autoplay_next(update.chat_id, current, generation))


async def autoplay_next(chat, previous, generation):
    """Select one different search result; discard it if another request wins the race."""
    try:
        results = await asyncio.to_thread(search_tracks, previous['title'])
        result = next((r for r in results if r['url'] != previous.get('source_url')
                       and r['title'].casefold() != previous['title'].casefold()), None)
        if not result or not store.autoplay_enabled(chat):
            return
        track = await asyncio.to_thread(download_audio_track, result['url'], True)
        track['user'] = 'Autoplay'
        if not store.autoplay_enabled(chat):
            discard(track)
            return
        await player.enqueue(chat, track, generation, only_if_empty=True)
    except Exception:
        log.exception('Autoplay could not load a related track')


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


@bot.on_message(filters.command('start') & filters.group)
async def group_start(_, message):
    await message.reply_text(HELP)

async def enqueue_item(chat, item, requester, generation):
    state = player.chats[chat]
    track = None
    state.pending_requests += 1
    try:
        async with state.requests:
            if generation != state.generation:
                return None
            if item['kind'] in ('audio', 'video_upload'):
                directory = tempfile.mkdtemp(prefix='music-')
                track = {'directory': directory}
                path = await bot.download_media(item['file_id'], file_name=f'{directory}/audio')
                if not path:
                    raise ValueError('Audio download failed.')
                track.update(file_path=os.path.abspath(path), title=item['title'],
                             duration=item.get('duration', 0), thumb=None, audio_id=item['file_id'],
                             thumb_id=item.get('thumb_id'))
                track['video'] = item['kind'] == 'video_upload'
                if item.get('thumb_id'):
                    try:
                        track['thumb'] = await bot.download_media(item['thumb_id'], file_name=f'{directory}/thumb.jpg')
                    except Exception:
                        log.warning('Could not download thumbnail', exc_info=True)
            else:
                downloader = download_video_track if item.get('video') else download_audio_track
                track = await asyncio.to_thread(downloader, item['query'], item['kind'] == 'url')
            track['user'] = requester
            position = await player.enqueue(chat, track, generation)
            track = None
            return position
    except BaseException:
        if track:
            discard(track)
        raise
    finally:
        state.pending_requests -= 1


def position_message(position):
    if position is None:
        return 'Request cancelled by /stop or /clearqueue.'
    if position == -1:
        return 'Could not start playback. Check that the voice chat is active and the assistant has joined.'
    return f'➕ Added to queue · position {position}' if position else 'Song started. Use /queue to see upcoming songs.'


@bot.on_message(filters.command(['song', 'play', 'vplay']) & filters.group)
async def song_command(_, message):
    video = message.command[0].lower() == 'vplay'
    reply = message.reply_to_message
    offline = reply and (reply.video if video else reply.audio)
    if len(message.command) < 2 and not offline:
        await message.reply_text('Use /play <name> or /vplay <name>, or reply to an audio or video file respectively.')
        return
    chat = message.chat.id
    generation = player.chats[chat].generation
    status = await message.reply_text('📥 Loading song…')
    if offline:
        thumbs = getattr(offline, 'thumbs', None) or []
        item = dict(kind='video_upload' if video else 'audio', file_id=offline.file_id,
                    title=getattr(offline, 'title', None) or offline.file_name or ('Video' if video else 'Audio'), duration=offline.duration or 0,
                    thumb_id=thumbs[-1].file_id if thumbs else None)
    else:
        query = ' '.join(message.command[1:])
        item = dict(kind='url' if query.startswith(('https://', 'http://')) else 'query', query=query, video=video)
    try:
        result = await enqueue_item(chat, item, message.from_user.first_name if message.from_user else 'Admin', generation)
        await status.edit_text(position_message(result))
    except Exception:
        log.exception('Song request failed')
        await status.edit_text('Could not load song. Try another title or upload an audio file.')


@bot.on_message(filters.command('search') & filters.group)
async def search_command(_, message):
    if len(message.command) < 2 or not message.from_user:
        await message.reply_text('Use /search <song name>.')
        return
    status = await message.reply_text('🔎 Searching…')
    try:
        results = await asyncio.to_thread(search_tracks, ' '.join(message.command[1:]))
        if not results:
            await status.edit_text('No songs found. Try another search.')
            return
        now = time.monotonic()
        for key in list(searches):
            if searches[key]['expires'] <= now:
                del searches[key]
        token = secrets.token_urlsafe(8)
        searches[token] = dict(chat=message.chat.id, user=message.from_user.id,
                               generation=player.chats[message.chat.id].generation,
                               expires=now + 300, results=results)
        buttons = [[InlineKeyboardButton(f"{i + 1}. {r['title'][:55]} ({timestamp(r['duration'])})",
                                         callback_data=f'search:{token}:{i}')]
                   for i, r in enumerate(results)]
        await status.edit_text('Choose a song (results expire in 5 minutes):', reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        log.exception('Search failed')
        await status.edit_text('Search failed. Please try again.')


@bot.on_message(filters.command(['stop', 'end', 'pause', 'resume', 'skip', 'next', 'replay',
                                  'shuffle', 'loop', 'volume']) & filters.group)
async def control_command(_, message):
    action = message.command[0].lower()
    action = 'skip' if action == 'next' else action
    action = {'end': 'stop', 'replay': 'restart'}.get(action, action)
    if not await may_control(message.chat.id, message.from_user.id if message.from_user else None):
        await message.reply_text('Only group admins and authorized users can use playback controls in this group. Try /voteskip.')
        return
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


@bot.on_message(filters.command(['remove', 'clearqueue', 'seek']) & filters.group)
async def queue_control_command(_, message):
    chat = message.chat.id
    if not await may_control(chat, message.from_user.id if message.from_user else None):
        await message.reply_text('Only group admins and authorized users can use this control.')
        return
    action = message.command[0].lower()
    try:
        if action == 'clearqueue':
            result = await player.clear_queue(chat)
        elif action == 'remove':
            if len(message.command) != 2 or not message.command[1].isdigit():
                raise ValueError('Use /remove <upcoming queue number>.')
            result = await player.remove(chat, int(message.command[1]))
        else:
            if len(message.command) != 2:
                raise ValueError('Use /seek 1:30 or /seek 90.')
            result = await player.seek(chat, parse_seek(message.command[1]))
        await message.reply_text(result)
    except ValueError as exc:
        await message.reply_text(str(exc))
    except Exception:
        log.exception('Queue control failed')
        await message.reply_text('Could not complete that action. Check the voice chat.')


@bot.on_message(filters.command('voteskip') & filters.group)
async def vote_command(_, message):
    if not message.from_user:
        await message.reply_text('A user account is needed to vote.')
        return
    _, threshold = store.settings(message.chat.id)
    await message.reply_text(await player.vote_skip(message.chat.id, message.from_user.id, threshold))


@bot.on_message(filters.command(['admincontrols', 'votethreshold']) & filters.group)
async def settings_command(_, message):
    chat = message.chat.id
    if not await is_admin(chat, message.from_user.id if message.from_user else None):
        await message.reply_text('Only a group admin can change these settings. Send the command from your user account.')
        return
    action = message.command[0].lower()
    if action == 'admincontrols':
        if len(message.command) != 2 or message.command[1].lower() not in ('on', 'off'):
            await message.reply_text('Use /admincontrols on or /admincontrols off.')
            return
        enabled = message.command[1].lower() == 'on'
        store.set_setting(chat, admins_only=enabled)
        await message.reply_text(f"Admin-only playback controls: {'ON' if enabled else 'OFF'}. Members can still request songs and use /voteskip.")
    else:
        if len(message.command) != 2 or not message.command[1].isdigit() or not 1 <= int(message.command[1]) <= 20:
            await message.reply_text('Use /votethreshold <1-20>.')
            return
        value = int(message.command[1])
        store.set_setting(chat, votes_required=value)
        # Start a fresh vote when the rule changes.
        state = player.chats[chat]
        async with state.lock:
            state.votes.clear()
        await message.reply_text(f'Skip voting now requires {value} distinct user(s).')


@bot.on_message(filters.command(['settings', 'autoplay', 'auth', 'unauth', 'mode']) & filters.group)
async def feature_settings(_, message):
    chat = message.chat.id
    action = message.command[0].lower()
    user_id = message.from_user.id if message.from_user else None
    if action == 'settings':
        restricted, threshold = store.settings(chat)
        await message.reply_text(f"Control mode: {'admin and authorized' if restricted else 'all members'}\n"
                                 f"Autoplay: {'ON' if store.autoplay_enabled(chat) else 'OFF'}\n"
                                 f"Skip votes required: {threshold}\n"
                                 'Admins: /mode admin|all, /autoplay on|off, /auth or /unauth by reply or user ID.')
        return
    if not await is_admin(chat, user_id):
        await message.reply_text('Only a group admin can change these settings.')
        return
    args = message.command[1:]
    if action in ('auth', 'unauth'):
        target = message.reply_to_message.from_user if message.reply_to_message else None
        if not args and target:
            target_id = target.id
        elif len(args) == 1 and args[0].isdigit() and int(args[0]) > 0:
            target_id = int(args[0])
        else:
            await message.reply_text(f'Use /{action} <user ID> or reply to a user.')
            return
        store.authorize(chat, target_id, action == 'auth')
        await message.reply_text(f"User {target_id} {'authorized' if action == 'auth' else 'removed from authorized users'}.")
    elif action == 'autoplay':
        if len(args) > 1 or (args and args[0].lower() not in ('on', 'off')):
            await message.reply_text('Use /autoplay, /autoplay on or /autoplay off.')
            return
        enabled = args[0].lower() == 'on' if args else not store.autoplay_enabled(chat)
        store.set_autoplay(chat, enabled)
        await message.reply_text(f"Autoplay: {'ON' if enabled else 'OFF'}.")
    else:
        if len(args) != 1 or args[0].lower() not in ('admin', 'all'):
            await message.reply_text('Use /mode admin or /mode all.')
            return
        store.set_setting(chat, admins_only=args[0].lower() == 'admin')
        await message.reply_text('Control mode updated. Admin mode also permits authorized users.')


@bot.on_message(filters.command(['speed', 'clean', 'reboot', 'reload', 'restart']))
async def maintenance_command(_, message):
    action = message.command[0].lower()
    if action == 'speed':
        started = time.monotonic()
        status = await message.reply_text('Checking bot response…')
        await status.edit_text(f'Bot response time: {(time.monotonic() - started) * 1000:.0f} ms.')
        return
    if not OWNER_ID or not message.from_user or message.from_user.id != OWNER_ID:
        await message.reply_text('Only the configured bot owner can use this command.')
        return
    if action == 'clean':
        expired = [key for key, value in searches.items() if value['expires'] <= time.monotonic()]
        for key in expired:
            del searches[key]
        await message.reply_text(f'Cleared {len(expired)} expired search result(s).')
        return
    await message.reply_text('Restarting the bot worker and reloading its code. Active queues will be cleared.')
    restart_requested.set()


def saved_track(song):
    if song.get('audio_id'):
        return dict(kind='video_upload' if song.get('video') else 'audio', file_id=song['audio_id'], title=song['title'],
                    duration=song['duration'], thumb_id=song.get('thumb_id'))
    if song.get('source_url'):
        return dict(kind='url', query=song['source_url'], title=song['title'], video=song.get('video', False))
    raise ValueError('This song has no reusable source. Search for it again or upload an audio file.')


@bot.on_message(filters.command('playlist') & filters.group)
async def playlist_command(_, message):
    chat = message.chat.id
    args = message.command[1:]
    help_text = ('/playlist list · /playlist show <name> · /playlist save <name> (current song) · '
                 '/playlist play <name> · /playlist remove <name> <number> · /playlist delete <name>')
    if not args:
        await message.reply_text(help_text)
        return
    action = args[0].lower()
    try:
        if action == 'list' and len(args) == 1:
            names = store.names(chat)
            await message.reply_text('Playlists:\n' + '\n'.join(f'{name}: {count} song(s)' for name, count in names[:80]) + (f'\n…and {len(names)-80} more' if len(names) > 80 else '') if names else 'No playlists yet. Use /playlist save <name>.', parse_mode=ParseMode.DISABLED)
        elif action == 'save' and len(args) == 2:
            state = player.chats[chat]
            async with state.lock:
                if not state.queue:
                    await message.reply_text('Play a song first, then use /playlist save <name>.')
                    return
                item = saved_track(state.queue[0])
                count = store.save(chat, args[1], item)
            await message.reply_text(f'Saved to {args[1]} ({count} song(s)).', parse_mode=ParseMode.DISABLED)
        elif action == 'show' and len(args) == 2:
            items = store.items(chat, args[1])
            lines = [f"{i}. {item.get('title', 'Audio')[:100]}" for i, item in enumerate(items[:30], 1)]
            if len(items) > 30:
                lines.append(f'…and {len(items) - 30} more')
            await message.reply_text(('Playlist ' + args[1] + ':\n' + '\n'.join(lines)) if lines else 'Playlist is empty or does not exist.', parse_mode=ParseMode.DISABLED)
        elif action == 'play' and len(args) == 2:
            items = store.items(chat, args[1])
            if not items:
                await message.reply_text('Playlist is empty or does not exist.')
                return
            generation = player.chats[chat].generation
            status = await message.reply_text(f'Loading {len(items)} song(s) from playlist…')
            added = failed = 0
            for item in items:
                try:
                    result = await enqueue_item(chat, item, message.from_user.first_name if message.from_user else 'Admin', generation)
                    if result is None:
                        break
                    if result == -1:
                        failed += 1
                    else:
                        added += 1
                except Exception:
                    failed += 1
                    log.warning('Playlist item failed', exc_info=True)
            cancelled = generation != player.chats[chat].generation
            await status.edit_text(f'Playlist: {added} song(s) loaded, {failed} failed.' + (' Remaining requests cancelled.' if cancelled else ''))
        elif action == 'remove' and len(args) == 3 and args[2].isdigit():
            found = store.remove(chat, args[1], int(args[2]))
            await message.reply_text('Song removed from playlist.' if found else 'Song number not found.')
        elif action == 'delete' and len(args) == 2:
            found = store.delete(chat, args[1])
            await message.reply_text('Playlist deleted.' if found else 'Playlist not found.')
        else:
            await message.reply_text(help_text)
    except ValueError as exc:
        await message.reply_text(str(exc), parse_mode=ParseMode.DISABLED)
    except Exception:
        log.exception('Playlist action failed')
        await message.reply_text('Playlist action failed. Check the bot storage and try again.')


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
    if callback_query.data.startswith('search:'):
        try:
            _, token, raw_index = callback_query.data.split(':')
            result_set = searches.get(token)
            requester = callback_query.from_user
            if (not result_set or result_set['expires'] <= time.monotonic()
                    or result_set['chat'] != callback_query.message.chat.id):
                await callback_query.answer('Search expired. Please search again.', show_alert=True)
                return
            if not requester or requester.id != result_set['user']:
                await callback_query.answer('Only the person who searched can choose.', show_alert=True)
                return
            index = int(raw_index)
            if index < 0 or index >= len(result_set['results']):
                raise ValueError('Invalid result')
            result = result_set['results'][index]
            del searches[token]
            await callback_query.answer('Loading selected song…')
            try:
                await callback_query.message.edit_text('📥 Loading selected song…')
                position = await enqueue_item(result_set['chat'], dict(kind='url', query=result['url']),
                                              requester.first_name, result_set['generation'])
                await callback_query.message.edit_text(position_message(position))
            except Exception:
                log.exception('Could not load search result')
                await callback_query.message.edit_text('Could not load this song. Try another result.')
        except (ValueError, IndexError):
            await callback_query.answer('Invalid search result.', show_alert=True)
        return
    if callback_query.data == 'cb_vote':
        if not callback_query.from_user:
            await callback_query.answer('A user account is needed to vote.', show_alert=True)
            return
        chat = callback_query.message.chat.id
        _, threshold = store.settings(chat)
        result = await player.vote_skip(chat, callback_query.from_user.id, threshold, callback_query.message.id)
        await callback_query.answer(result, show_alert=True)
        return
    if callback_query.data == 'cb_help':
        await callback_query.answer()
        await callback_query.message.reply_text(HELP)
        return
    action = callback_query.data.removeprefix('cb_')
    if action not in {'restart', 'toggle', 'stop', 'skip', 'shuffle', 'loop'}:
        await callback_query.answer('Use the controls on the latest song card.')
        return
    chat = callback_query.message.chat.id
    if not await may_control(chat, callback_query.from_user.id if callback_query.from_user else None):
        await callback_query.answer('Only admins and authorized users can use these controls. You can vote to skip.', show_alert=True)
        return
    try:
        result = await player.control(chat, action,
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
    await bot.set_bot_commands([BotCommand(command, description) for command, description in COMMANDS])
    log.info('NGS-MUSIC-BOT started successfully')
    try:
        await restart_requested.wait()
    finally:
        for chat in list(player.chats):
            await player.control(chat, 'stop')
        await calls.stop()
        await user.stop()
        await bot.stop()
    os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == '__main__':
    bot.run(main())
