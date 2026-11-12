<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:02d6cf0e0e9c833c6a256d540492487188bbbc2c43c6816b5007e1e08f4fbb02 -->

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:8c8bdfe9d4521ed5d52426a8f4d052b4c92f913db1cac9738182b4a8fbfeb627 -->

# Telegram Voice-Chat Music Bot

Play songs with friends in a Telegram group voice chat. `/song Believer` plays Believer; `/song Safar` adds Safar to the queue.

## Deploy

Install `requirements.txt`. Deploy `main.py`, `player.py`, `storage.py`, `requirements.txt`, `Procfile`, and `start_img.jpg`. Start with `python main.py`.

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:fb857a4a29b376d47dda460bd79709da0edab285920d0e12d1b8f44300b369e7 -->

Set `API_ID`, `API_HASH`, `BOT_TOKEN` (or `TELEGRAM_BOT_TOKEN`), and `SESSION_STRING` on your host. Set `OWNER_ID` to the bot owner’s numeric Telegram user ID to enable maintenance commands. Never share or commit secrets. Add the bot and assistant user to your group and start a voice chat. The host must support py-tgcalls 3.0.0, persistent workers and FFmpeg. Stream media you have permission to use. See [the feature guide](FEATURES.md) and [PDF guide](features-guide.pdf).

<!-- /coderabbit-ai-generated:v1 -->

## Playback and queue

- `/song <name>` or `/play <name>`: start or queue an online song. `/play` replying to audio queues the uploaded file.
- `/search <name>`: choose from five search results. Only the requester can select, and results expire after five minutes.
- `/queue`: show the current song and numbered upcoming songs.
- `/remove 2`: remove upcoming song number 2, using the numbers from `/queue`.
- `/clearqueue`: remove upcoming songs and cancel pending downloads; the current song continues.
<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:67d337cb1451ef0c1157eaa5ba66c26f2af90da07314ff3d0e58b27d5ef58d17 -->

- `/pause`, `/resume`, `/skip` (or `/next`), `/stop` (or `/end`), `/replay`, `/shuffle`, `/loop`, `/volume <1-200>`: control playback. Loop repeats the queue; skip removes the current song. `/replay` replaces the previous `/restart` track command.
- `/vplay <name or URL>` or `/vplay` replying to a video: play or queue video.
- Group admins can toggle `/autoplay` to search for another track after the queue finishes naturally.

<!-- /coderabbit-ai-generated:v1 -->
- `/seek 1:30` or `/seek 90`: jump to a time in the current song. Its duration must be known; seeking keeps a paused song paused.
- `/voteskip`: each person may vote once for the current song. Two distinct votes skip it by default. Votes reset when the song changes or playback stops. The song card also has a vote button.

## Shared playlists

Playlists are shared by a group. Names can contain up to 30 letters, numbers, underscores or hyphens. Each holds up to 100 tracks.

- `/playlist save favourites`: save the current song.
- `/playlist list`: show saved playlists.
- `/playlist show favourites`: show songs and their numbers.
- `/playlist play favourites`: download and queue songs in order. Failed or unavailable tracks are reported.
- `/playlist remove favourites 2`: remove song 2 from the saved playlist.
- `/playlist delete favourites`: delete a playlist.

Saved online songs use their source link and uploaded audio uses its Telegram file ID. A source may later become unavailable. Playback commands, song requests, and playlist edits are available to group members by default.

## Group admin settings

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:698fd124c61ba44693d32b7ed560f270f7c7674690938c92ec4cd99aaeaa1747 -->

A group administrator can use `/mode admin` or `/admincontrols on` to restrict playback controls and buttons to administrators and authorized users. `/mode all` or `/admincontrols off` restores access for everyone. An admin can authorize a user with `/auth` in reply to their message or `/auth <user ID>`, and remove access with `/unauth`. Members may still request songs, use playlists and vote to skip. Admin status is checked with Telegram for each restricted action; anonymous admins should send the setting command from their user account.

<!-- /coderabbit-ai-generated:v1 -->

A group administrator can use `/votethreshold 3` to require three distinct votes (choose 1–20). The default is 2. Setting a new threshold clears the current votes. With admin controls off, `/skip` remains available to everyone; turn them on if you want ordinary members to use voting instead.

## Data and progress

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:9f624cc00e4d86520529b536baa831773691a9804166dbb5a58d738c3fb90f30 -->

Playlists, group settings, autoplay and authorized users are stored in SQLite at `music.sqlite3`.

<!-- /coderabbit-ai-generated:v1 --> To survive host redeploys and restarts that erase local files, set `MUSIC_DB_PATH` to a writable file on your host's persistent disk, for example `/data/music.sqlite3`. Back up this database. Queues and votes remain in memory and reset when the bot restarts. Temporary song files are deleted after playback, skip or stop.

Song cards show a thumbnail when available and an estimated elapsed/total progress bar updated about every 10 seconds. Unknown durations are labeled. The bar is a display; use `/seek` to move playback.

## Verification

Run `python -m unittest discover -s tests -v`. These tests mock Telegram. After deployment, test playback, queue, search, seeking, voting, admin permissions, saved playlists and restart persistence in a real group voice chat.


<!-- /coderabbit-ai-generated:v1 -->

<!-- /coderabbit-ai-generated:v1 -->