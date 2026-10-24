# Telegram Voice-Chat Music Bot (starter)

This is a starter project for `/play song name` in a Telegram group voice chat.

## Important limitations
- This is a starter, not a guaranteed one-click deployment. Voice-chat library versions and host system packages can affect compatibility.
- Telegram bot accounts generally cannot act as the voice-chat streaming account. This project uses **two clients**: your bot token receives commands, and a separate Telegram user account (`SESSION_STRING`) joins/streams.
- The user account must be a member of the group. Start a voice chat in the group before testing `/play`.
- The host needs FFmpeg and enough CPU/RAM for streaming. Some free hosts prohibit long-running workers or do not include FFmpeg.
- Use audio sources you have permission to stream and follow YouTube/Telegram terms and local copyright law.

## Environment variables
Configure these in the hosting dashboard, not in GitHub:
- `API_ID` — from https://my.telegram.org
- `API_HASH` — from https://my.telegram.org
- `BOT_TOKEN` — from @BotFather
- `SESSION_STRING` — a Pyrogram session string for a Telegram user account

**Never commit these values to GitHub or send them in chat.** A session string can give access to your Telegram account. Only generate/use it on a device and service you trust.

## Deploy
1. Upload `main.py`, `requirements.txt`, and `Procfile` to the root of your GitHub repository.
2. On the host, set the four environment variables above.
3. Start command: `python main.py`
4. Ensure FFmpeg is installed and the host allows a persistent worker.
5. Add the bot and the user account to the group, start a voice chat, then test `/play Safar`.

## Current commands
- `/start`
- `/play <song name>`

Pause, resume, skip, queue, and stop are not implemented in this starter yet.
