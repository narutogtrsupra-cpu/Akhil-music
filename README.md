<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:02d6cf0e0e9c833c6a256d540492487188bbbc2c43c6816b5007e1e08f4fbb02 -->

# Telegram Voice-Chat Music Bot

Music for Telegram group voice chats. `/song Believer` plays Believer; `/song Safar` queues Safar until Believer finishes.

## Deployment

Install `requirements.txt`. Deploy `main.py`, `player.py`, `requirements.txt`, `Procfile`, and `start_img.jpg`. Start with `python main.py`.

Set `API_ID`, `API_HASH`, `BOT_TOKEN` (or `TELEGRAM_BOT_TOKEN`), and `SESSION_STRING` in your hosting dashboard. Never commit or share secrets. Generate the assistant user session on a trusted device. Add both the assistant user and bot to your group, then start a voice chat.

The host must support py-tgcalls 3.0.0 and its native dependencies, persistent workers, and audio processing. static-ffmpeg downloads FFmpeg on first use. Stream media you have permission to use.

## Commands

- `/song <name>` or `/play <name>`: start or queue an online song.
- `/play` replying to an audio file: queue uploaded audio.
- `/pause`, `/resume`: pause and continue.
- `/skip` or `/next`: remove the current song and start the next.
- `/stop`: clear the queue, cancel pending requests, and leave the call.
- `/restart`: restart the current song.
- `/queue`: list current and upcoming songs.
- `/shuffle`: shuffle upcoming songs while keeping the current song.
- `/loop`: toggle repeating the entire queue; skip still removes a song.
- `/volume <1-200>`: change volume.
- `/start`: welcome/help in private chat.

Commands and player buttons are available to group members. Old song controls are retired. Restart replaces the misleading previous button.

## Thumbnails and progress

Song cards show the source thumbnail when available, or the uploaded Telegram audio thumbnail. If the image cannot be sent, playback continues with a text card.

The elapsed/total progress bar refreshes every 10 seconds, subject to Telegram limits. Time is estimated with a monotonic clock, freezes while paused, and resets on restart/skip. This is a display, not a draggable seek control. Unknown durations are labeled rather than guessed.

Each request owns a temporary directory. Files are deleted after completion, skip, or stop, and retained while queue looping. Queues live in memory and reset on bot restart.

## Verification

Run `python -m unittest discover -s tests -v`. Tests use mocked clients. On your host, start a voice chat, send `/song Believer` then `/song Safar`, inspect `/queue`, and test pause/resume, skip, stop, thumbnail, and progress updates. Real Telegram streaming and source access require this final check.


<!-- /coderabbit-ai-generated:v1 -->