"""Persistent group settings and shared playlists (SQLite)."""
from contextlib import contextmanager
import json
import re
import sqlite3


class Storage:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (
                    chat INTEGER PRIMARY KEY, admins_only INTEGER NOT NULL DEFAULT 0,
                    votes_required INTEGER NOT NULL DEFAULT 2
                );
                CREATE TABLE IF NOT EXISTS playlists (
                    chat INTEGER NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL,
                    item TEXT NOT NULL, PRIMARY KEY (chat, name, position)
                );
                CREATE TABLE IF NOT EXISTS authorized_users (
                    chat INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    PRIMARY KEY (chat, user_id)
                );
                CREATE TABLE IF NOT EXISTS autoplay (
                    chat INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def name(value):
        if not re.fullmatch(r'[\w-]{1,30}', value, re.UNICODE):
            raise ValueError('Playlist names must be 1–30 letters, numbers, underscores or hyphens.')
        return value.lower()

    def settings(self, chat):
        with self.connect() as db:
            row = db.execute('SELECT admins_only, votes_required FROM settings WHERE chat=?', (chat,)).fetchone()
        return (bool(row[0]), row[1]) if row else (False, 2)

    def set_setting(self, chat, *, admins_only=None, votes_required=None):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO settings (chat) VALUES (?)', (chat,))
            if admins_only is not None:
                db.execute('UPDATE settings SET admins_only=? WHERE chat=?', (int(admins_only), chat))
            if votes_required is not None:
                db.execute('UPDATE settings SET votes_required=? WHERE chat=?', (votes_required, chat))

    def is_authorized(self, chat, user_id):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM authorized_users WHERE chat=? AND user_id=?', (chat, user_id)).fetchone() is not None

    def authorize(self, chat, user_id, enabled=True):
        with self.connect() as db:
            if enabled:
                db.execute('INSERT OR IGNORE INTO authorized_users VALUES (?, ?)', (chat, user_id))
            else:
                db.execute('DELETE FROM authorized_users WHERE chat=? AND user_id=?', (chat, user_id))

    def autoplay_enabled(self, chat):
        with self.connect() as db:
            row = db.execute('SELECT enabled FROM autoplay WHERE chat=?', (chat,)).fetchone()
        return bool(row and row[0])

    def set_autoplay(self, chat, enabled):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO autoplay VALUES (?, ?)', (chat, int(enabled)))

    def save(self, chat, name, item):
        name = self.name(name)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT COUNT(*) FROM playlists WHERE chat=? AND name=?', (chat, name)).fetchone()[0]
            if count >= 100:
                raise ValueError('A playlist can hold at most 100 songs.')
            next_pos = db.execute('SELECT COALESCE(MAX(position), 0)+1 FROM playlists WHERE chat=? AND name=?', (chat, name)).fetchone()[0]
            db.execute('INSERT INTO playlists VALUES (?, ?, ?, ?)', (chat, name, next_pos, json.dumps(item)))
        return count + 1

    def names(self, chat):
        with self.connect() as db:
            return db.execute('SELECT name, COUNT(*) FROM playlists WHERE chat=? GROUP BY name ORDER BY name', (chat,)).fetchall()

    def items(self, chat, name):
        name = self.name(name)
        with self.connect() as db:
            rows = db.execute('SELECT item FROM playlists WHERE chat=? AND name=? ORDER BY position', (chat, name)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def remove(self, chat, name, index):
        name = self.name(name)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT position FROM playlists WHERE chat=? AND name=? ORDER BY position LIMIT 1 OFFSET ?', (chat, name, index - 1)).fetchone() if index > 0 else None
            if not row:
                return False
            db.execute('DELETE FROM playlists WHERE chat=? AND name=? AND position=?', (chat, name, row[0]))
            return True

    def delete(self, chat, name):
        name = self.name(name)
        with self.connect() as db:
            return db.execute('DELETE FROM playlists WHERE chat=? AND name=?', (chat, name)).rowcount
