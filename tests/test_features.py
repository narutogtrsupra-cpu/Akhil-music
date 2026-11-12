import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.update(API_ID='12345', API_HASH='test', BOT_TOKEN='12345:test', SESSION_STRING='test')
os.environ['MUSIC_DB_PATH'] = str(Path(tempfile.mkdtemp()) / 'test.sqlite3')
with patch('static_ffmpeg.add_paths'):
    import main

from player import Player
from storage import Storage


class StorageTests(unittest.TestCase):
    def test_authorization_and_autoplay_are_per_group_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'db.sqlite3')
            store = Storage(path)
            store.authorize(1, 42)
            store.set_autoplay(1, True)
            reopened = Storage(path)
            self.assertTrue(reopened.is_authorized(1, 42))
            self.assertFalse(reopened.is_authorized(2, 42))
            self.assertTrue(reopened.autoplay_enabled(1))
            self.assertFalse(reopened.autoplay_enabled(2))
            reopened.authorize(1, 42, False)
            self.assertFalse(reopened.is_authorized(1, 42))


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_and_audio_streams_and_seek(self):
        audio = main.make_stream({'file_path': '/tmp/audio.mp3'})
        video = main.make_stream({'file_path': '/tmp/video.mp4', 'video': True}, 20)
        self.assertIsNone(audio.camera)
        self.assertIsNotNone(video.camera)
        self.assertIn('-ss 20', video.camera.path)

    async def test_autoplay_does_not_override_new_request(self):
        calls = SimpleNamespace(play=AsyncMock(), resume=AsyncMock(), change_volume_call=AsyncMock(), leave_call=AsyncMock())
        player = Player(calls, lambda track, offset=0: track, AsyncMock(return_value=None), AsyncMock())
        state = player.chats[1]
        state.queue.append({'title': 'Requested', 'file_path': 'requested', 'duration': 1})
        with tempfile.TemporaryDirectory() as directory:
            track = {'title': 'Auto', 'file_path': 'auto', 'directory': directory}
            self.assertIsNone(await player.enqueue(1, track, state.generation, only_if_empty=True))
            self.assertEqual([song['title'] for song in state.queue], ['Requested'])
            calls.play.assert_not_awaited()
            self.assertFalse(Path(directory).exists())

    async def test_autoplay_uses_new_source_and_honors_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(str(Path(directory) / 'db.sqlite3'))
            store.set_autoplay(1, True)
            player = SimpleNamespace(enqueue=AsyncMock())
            track = {'title': 'Next'}
            with patch.object(main, 'store', store), patch.object(main, 'player', player), \
                 patch.object(main, 'search_tracks', return_value=[{'title': 'Old', 'url': 'old'}, {'title': 'Next', 'url': 'next'}]), \
                 patch.object(main, 'download_audio_track', return_value=track):
                await main.autoplay_next(1, {'title': 'Old', 'source_url': 'old'}, 4)
            player.enqueue.assert_awaited_once_with(1, track, 4, only_if_empty=True)

    async def test_autoplay_does_not_override_pending_download(self):
        calls = SimpleNamespace(play=AsyncMock())
        player = Player(calls, lambda track, offset=0: track, AsyncMock(), AsyncMock())
        state = player.chats[1]
        state.pending_requests = 1
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(await player.enqueue(1, {'directory': directory}, 0, only_if_empty=True))
            calls.play.assert_not_awaited()

    async def test_restricted_controls_allow_authorized_user(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(str(Path(directory) / 'db.sqlite3'))
            store.set_setting(1, admins_only=True)
            store.authorize(1, 42)
            with patch.object(main, 'store', store), patch.object(main, 'is_admin', AsyncMock(return_value=False)):
                self.assertTrue(await main.may_control(1, 42))
                self.assertFalse(await main.may_control(1, 43))

    async def test_owner_restriction_and_restart_signal(self):
        message = SimpleNamespace(command=['restart'], from_user=SimpleNamespace(id=12), reply_text=AsyncMock())
        event = asyncio.Event()
        with patch.object(main, 'OWNER_ID', 34), patch.object(main, 'restart_requested', event):
            await main.maintenance_command(None, message)
            self.assertFalse(event.is_set())
            message.from_user.id = 34
            await main.maintenance_command(None, message)
            self.assertTrue(event.is_set())
