# Herodraft sounds

The `--herodraft` practice board plays the real Dota 2 Captains Mode sounds
from these files. They are exported from the user's own Dota 2 install
(with Source 2 Viewer) and are **never committed** to this repo — see
`.gitignore` (`scout/assets/sounds/*`, with this README excluded). If a file
here is ever missing, the board falls back to a small synthesized
equivalent instead, so sound never hard-fails.

Event map (relative volumes are the client's own, from
`soundevents/game_sounds_ui_imported.vsndevts`; the board multiplies each
by the volume slider):

| File               | Event                                                         | Vol  |
|--------------------|----------------------------------------------------------------|------|
| `music.mp3`        | Loops from Start draft, fades out (~2s) on completion/leaving  | 0.35 |
| `draft_start.mp3`  | Plays once when Start draft is pressed                         | 0.16 |
| `advance.mp3`      | Every time the draft order advances to the next step           | 0.20 |
| `ban.mp3`          | A ban locks in, either team                                    | 0.16 |
| `pick.mp3`         | A pick locks in, either team                                   | 0.16 |
| `pick_made.mp3`    | Right after `pick.mp3`, only for the user's own picks           | 0.66 |
| `countdown.mp3`    | Once per second: last 5s of the main timer, and all of reserve | 0.30 |
| `announcer_10s.mp3`| Once per turn, when the main timer crosses 10s remaining        | 0.66 |
| `announcer_5s.mp3` | Once per turn, when the main timer crosses 5s remaining (pre-empts that second's countdown tick) | 0.66 |
| `your_ban.mp3`     | A new turn begins and it's the user's turn to ban               | 0.66 |
| `your_pick.mp3`    | A new turn begins and it's the user's turn to pick              | 0.66 |
| `enemy_ban.mp3`    | A new turn begins and it's the enemy's turn to ban              | 0.66 |
| `enemy_pick.mp3`   | A new turn begins and it's the enemy's turn to pick             | 0.66 |

Draft completion has no dedicated line in the client itself: the board just
stops the ticks and fades the music (a synthesized chime is used only if
this whole folder is empty).

Accepted extensions: `.mp3`, `.ogg`, `.wav`, `.webm`. Any filename other
than the thirteen above is ignored — `herodraft.py` only serves these
names, with one of those four extensions, from this folder.
