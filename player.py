"""Per-chat playback state. All queue transitions share the same lock."""
import asyncio
import logging
import random
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def progress(elapsed, duration):
    if not duration:
        return f"{timestamp(elapsed)} / unknown duration"
    elapsed = min(elapsed, duration)
    filled = min(12, int(12 * elapsed / duration))
    return f"{'━' * filled}●{'─' * (12 - filled)}\n{timestamp(elapsed)} / {timestamp(duration)}"


@dataclass
class State:
    queue: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: asyncio.Lock = field(default_factory=asyncio.Lock)
    generation: int = 0
    paused: bool = False
    loop: bool = False
    volume: int = 100
    started: float = 0
    elapsed: float = 0
    card: object = None
    ticker: object = None

    def position(self):
        return self.elapsed + (0 if self.paused else time.monotonic() - self.started)


def discard(track):
    if track.get('directory'):
        shutil.rmtree(track['directory'], ignore_errors=True)


class Player:
    def __init__(self, calls, stream, announce, refresh):
        self.calls, self.stream = calls, stream
        self.announce, self.refresh = announce, refresh
        self.chats = defaultdict(State)

    async def enqueue(self, chat, track, generation):
        state = self.chats[chat]
        async with state.lock:
            if generation != state.generation:
                discard(track)
                return None
            state.queue.append(track)
            position = len(state.queue) - 1
            if position == 0:
                await self._start(chat, state)
            return position

    async def _retire_card(self, state):
        if state.ticker:
            state.ticker.cancel()
            state.ticker = None
        if state.card:
            try:
                await state.card.edit_reply_markup(reply_markup=None)
            except Exception:
                log.warning('Could not retire old player controls', exc_info=True)
            state.card = None

    async def _start(self, chat, state):
        await self._retire_card(state)
        while state.queue:
            track = state.queue[0]
            try:
                await self.calls.play(chat, self.stream(track['file_path']))
            except Exception:
                log.exception('Could not play %s', track['title'])
                discard(state.queue.pop(0))
                continue
            try:
                # Replacing a paused stream may retain the call's paused state.
                await self.calls.resume(chat)
            except Exception:
                log.warning('Could not resume new stream', exc_info=True)
            state.paused, state.elapsed, state.started = False, 0, time.monotonic()
            try:
                await self.calls.change_volume_call(chat, state.volume)
            except Exception:
                log.warning('Could not apply volume', exc_info=True)
            try:
                state.card = await self.announce(chat, state)
            except Exception:
                log.exception('Could not send song card; audio continues')
            if state.card:
                state.ticker = asyncio.create_task(self._tick(chat, state))
            return
        try:
            await self.calls.leave_call(chat)
        except Exception:
            log.debug('Already disconnected', exc_info=True)

    async def _tick(self, chat, state):
        try:
            while True:
                await asyncio.sleep(10)
                async with state.lock:
                    await self.update(state)
        except asyncio.CancelledError:
            pass

    async def update(self, state):
        if state.card and state.queue:
            try:
                await self.refresh(state)
            except Exception:
                log.warning('Could not refresh progress', exc_info=True)

    async def advance(self, chat, natural=False, expected=None):
        state = self.chats[chat]
        async with state.lock:
            if not state.queue or (expected is not None and state.queue[0] is not expected):
                return 'Nothing is playing.'
            track = state.queue.pop(0)
            if natural and state.loop:
                state.queue.append(track)
            await self._start(chat, state)
            if not (natural and state.loop):
                discard(track)
            return 'Skipped to the next song.' if state.queue else 'Queue finished.'

    async def control(self, chat, action, value=None, card_id=None):
        state = self.chats[chat]
        if action == 'skip':
            # Snapshot identity before waiting for another transition.
            if card_id and (not state.card or state.card.id != card_id):
                return 'These controls belong to an old song.'
            return await self.advance(chat, expected=state.queue[0] if state.queue else None)
        async with state.lock:
            if card_id and (not state.card or state.card.id != card_id):
                return 'These controls belong to an old song.'
            if action == 'stop':
                state.generation += 1
                state.loop = False
                leave_failed = False
                try:
                    await self.calls.leave_call(chat)
                except Exception:
                    leave_failed = True
                    log.warning('Could not leave voice chat', exc_info=True)
                tracks, state.queue = state.queue, []
                await self._retire_card(state)
                for track in tracks:
                    discard(track)
                state.paused = False
                return ('Queue cleared, but leaving the voice chat failed. Try /stop again.'
                        if leave_failed else 'Stopped playback and cleared the queue.')
            if not state.queue:
                return 'Nothing is playing.'
            if action == 'toggle':
                action = 'resume' if state.paused else 'pause'
            if action == 'pause' and not state.paused:
                await self.calls.pause(chat)
                state.elapsed = state.position()
                state.paused = True
            elif action == 'resume' and state.paused:
                await self.calls.resume(chat)
                state.started = time.monotonic()
                state.paused = False
            elif action == 'restart':
                await self._start(chat, state)
            elif action == 'loop':
                state.loop = not state.loop
            elif action == 'shuffle':
                waiting = state.queue[1:]
                random.shuffle(waiting)
                state.queue[1:] = waiting
            elif action == 'volume':
                await self.calls.change_volume_call(chat, value)
                state.volume = value
            await self.update(state)
            return {'pause': 'Paused.', 'resume': 'Resumed.', 'restart': 'Restarted song.',
                    'loop': f"Queue loop: {'ON' if state.loop else 'OFF'}.",
                    'shuffle': 'Shuffled upcoming songs.', 'volume': f'Volume: {state.volume}%.'}[action]
