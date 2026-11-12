<!-- coderabbit-ai-generated:v1 -->

# Music Bot: Step-by-Step Feature Guide

## 1. Get started

1. Install the dependencies in `requirements.txt` and run `python main.py` on a persistent worker with FFmpeg.
2. Configure `API_ID`, `API_HASH`, `BOT_TOKEN` (or `TELEGRAM_BOT_TOKEN`), and `SESSION_STRING`. Set `OWNER_ID` to your numeric Telegram user ID to enable owner maintenance commands. Keep these values private.
3. Add the bot and its assistant account to your Telegram group and start a voice chat. The assistant must be able to join it.
4. Open the bot privately and send `/start`, or send `/start` in the group to see the command summary. Telegram's command menu lists the main features.

## 2. Play music and video

- `/play Believer` searches for music and starts playback, or adds it to the queue if something is playing. `/song` is an alias. A supported URL also works.
- Reply to an audio file with `/play` to play it.
- `/vplay <name or URL>` searches for and plays video in the voice chat. Reply to a Telegram video with `/vplay` to play that file. Video needs a group call that supports video and sufficient bandwidth.
- `/search <name>` shows five choices. The requester must select a result within five minutes.

## 3. Control playback

1. Send `/pause` to pause and `/resume` to continue.
2. Send `/skip` to move to the next item; `/next` does the same. `/voteskip` lets members vote to skip.
3. Send `/replay` to start the current item again. This replaces the former `/restart` track command.
4. Send `/stop` or `/end` to leave the call, clear the queue, and cancel pending requests.
5. Send `/seek 1:30` or `/seek 90` to jump to a position before the end. The duration must be known.
6. Send `/volume 80` to set the volume from 1 to 200. `/loop` toggles repeating the queue; `/shuffle` mixes upcoming items only.
7. Use the buttons on the current song card for common controls. Old cards cannot control a new song.

## 4. Manage the queue and playlists

- `/queue` displays the current item and numbered upcoming items. `/remove 2` removes upcoming item 2. `/clearqueue` removes upcoming items and cancels pending downloads while the current item continues.
- `/playlist save favourites` saves the current item. `/playlist list` lists playlists; `/playlist show favourites` displays its items.
- `/playlist play favourites` loads its items. `/playlist remove favourites 2` removes an item; `/playlist delete favourites` deletes the playlist. Playlists are shared within the group and can hold up to 100 items each.

## 5. Group settings and permissions

1. Send `/settings` to see the group control mode, autoplay setting, and skip vote threshold.
2. A group admin can send `/mode admin` to restrict playback controls to group admins and authorized users, or `/mode all` to allow all members. `/admincontrols on` and `/admincontrols off` are equivalent. Song requests, playlists and skip voting remain available to members.
3. To authorize a user, an admin replies to that user's message with `/auth`, or sends `/auth 123456789` with their numeric user ID. Use `/unauth` in the same way to remove authorization. Authorization applies to that group only.
4. An admin can send `/autoplay` to toggle it, or `/autoplay on` or `/autoplay off`. When the queue finishes naturally, the bot searches using the last title and tries to play a different result. Looping the queue takes precedence. Autoplay may fail when no suitable result is found or a source is unavailable.
5. An admin can send `/votethreshold 3` to require three distinct skip votes; choose a number from 1 to 20. Changing the threshold clears existing votes.

## 6. Maintenance

- `/speed` measures the bot's response time to a Telegram message, in milliseconds.
- The configured owner can use `/clean` to remove expired in-memory search results. Temporary downloaded media is removed as items finish, are skipped, or are stopped.
- The configured owner can use `/reboot`, `/reload`, or `/restart` to restart the bot worker and reload its code. This clears active queues and reloads the built-in handlers. There is no separate plugin system or host machine restart in this project. Deploy changed files before reloading.
- The bot must be restarted after changing environment variables. Host process managers and environment settings control deployment and machine restarts.

## 7. Data and troubleshooting

- Group settings, authorized users and playlists use SQLite. Set `MUSIC_DB_PATH` to a writable file on persistent storage, such as `/data/music.sqlite3`, and back it up. Queues, votes and temporary search results are in memory and reset on restart.
- If playback fails, check that the group voice chat is active, the assistant account can join, FFmpeg is available, and the media source is accessible. Try another source if a download fails.
- The bot checks admin status through Telegram. Anonymous admins should send settings commands from their user account. Owner commands require a numeric `OWNER_ID` matching the sender.
- Use media you have permission to stream. Test the bot in a real group after deployment.
