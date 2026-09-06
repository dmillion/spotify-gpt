# ChatGPT Operating Guide

This repository is a general Spotify playlist curation tool. A user can ask ChatGPT to create, curate, or revise playlist files in this repo, then run the local scripts to push those changes to their own Spotify account.

## Primary goal

When the user asks for playlist curation, make the requested music changes in the repository rather than only returning a prose list.

Typical requests:

- "Add 15 songs like these."
- "Make this playlist sludgier."
- "Remove the songs that are too slow."
- "Build me a new playlist around these three bands."

## Important: route requests to the correct playlist

`Sludge Grinder` is only the first prototype/example playlist created with this project. It is **not** a global/default destination for new music recommendations.

Before changing a playlist, determine which playlist the user is actually discussing:

- If the user names an existing playlist or clearly continues a discussion about one, modify that playlist's source file.
- If the user asks for additions "to this playlist," "to that list," "more like these," etc., use the playlist established by the conversation context.
- If the request describes a substantially different musical concept and no existing playlist is identified, create a **new playlist definition** with an appropriate name rather than putting the tracks into `Sludge Grinder`.
- Never add unrelated recommendations to `Sludge Grinder` merely because it already exists.
- If multiple existing playlists could plausibly be the target and the conversation does not resolve the ambiguity, ask which playlist they mean before editing.

Treat every file under `playlists/` as an independent playlist definition. As the project grows, there may be many unrelated playlists covering different genres, moods, artists, eras, or purposes.

## Repository layout

- `spotify_playlist.py` — creates a Spotify playlist from a track-list file.
- `sync_playlist.py` — syncs a track-list file into an existing Spotify playlist without intentionally duplicating tracks.
- `playlists/` — independent playlist definitions.
- `.env.example` — example Spotify configuration only.
- `README.md` — installation and usage instructions.

Playlist files use this format:

```text
# comments are allowed
Artist | Track Title
Another Artist | Another Track
```

## How to handle playlist requests

1. Identify the intended playlist from the user's request and conversation context.
2. Read that playlist's source file before editing it.
3. Preserve existing tracks unless the user explicitly asks to remove or replace them.
4. Add tracks that genuinely fit the user's stated musical direction; do not pad the list with generic genre staples merely to hit a number.
5. Avoid duplicate artist/title entries.
6. Prefer canonical Spotify artist and track spellings when known.
7. Keep useful section comments when they help explain the playlist's structure.
8. Commit the resulting playlist-file change to GitHub.
9. Tell the user the simple local command needed to create or sync the correct playlist.

## Prototype/example: Sludge Grinder

The first playlist built while developing this project is:

```text
Sludge Grinder
```

Its corresponding source file is:

```text
playlists/sludge-with-grind-brain.txt
```

Only use this file when the user's request is actually about `Sludge Grinder` or clearly continues the sludge/grind playlist discussion.

A normal sync for this specific playlist is:

```bash
python sync_playlist.py --name "Sludge Grinder"
```

A safe preview is:

```bash
python sync_playlist.py --name "Sludge Grinder" --dry-run
```

These commands are examples for this playlist, not defaults for every curation request.

## Git workflow

The intended audience may not be comfortable with Git. Do not make the user manage branches, rebases, merges, or pull requests unless necessary.

If the connected GitHub account has permission to write to this repository, prefer a simple commit to the working branch or `main` according to the user's established workflow. If a separate branch is required by permissions or policy, create and manage it yourself and explain only the minimal next step the user needs.

Do not ask a nontechnical user to fork the repository unless there is no simpler permission model available.

## Spotify-account separation

The repository contains shared code and playlist definitions. Spotify authentication is local to each user's computer.

Each Spotify user should normally create their own Spotify Developer app and place their own Client ID in a local `.env` file. The browser OAuth flow determines which Spotify account receives playlist changes.

Never commit, request, or expose:

- `.env`
- OAuth access tokens
- OAuth refresh tokens
- Spotify Client Secrets
- other credentials

This project uses Authorization Code + PKCE and does not require a Spotify Client Secret.

The OAuth token cache lives outside the repository at:

```text
~/.cache/spotify-gpt/token.json
```

## For nontechnical users

Keep instructions short. After modifying an existing playlist, the preferred user-facing directions are generally:

```bash
git pull
python sync_playlist.py playlists/the-correct-file.txt --name "The Correct Playlist Name"
```

Do not omit the playlist file argument when the requested playlist is not the script's built-in/default file.

For a newly created playlist definition, give the corresponding `spotify_playlist.py` command instead.

If a one-click/local wrapper exists later, prefer that instead of terminal commands.

When troubleshooting, distinguish between:

- Git/repository problems
- Python environment problems
- Spotify OAuth problems
- Spotify catalog/search mismatches
- Spotify client refresh/playback problems

Do not overwhelm the user with implementation details unless they ask.

## Curation quality

Use the user's examples as the strongest signal. If they provide tracks or bands they like, infer the musical traits they are actually responding to (riff style, groove, tempo, production, vocals, breakdowns, atmosphere, etc.) rather than relying only on genre labels.

For iterative playlist work, use their likes/dislikes from prior rounds to refine later additions.

When current Spotify availability or an exact track title is uncertain, verify it rather than inventing a catalog entry.

## Creating a new playlist

For a new playlist:

1. Choose a concise Spotify playlist name that fits the musical concept. If naming is subjective or important to the user, offer/confirm the name rather than forcing one.
2. Create a new text file under `playlists/` with a descriptive, unique filename.
3. Populate it using `Artist | Track Title` lines.
4. Commit it without modifying unrelated playlist files.
5. Give the user a dry-run command first, for example:

```bash
python spotify_playlist.py playlists/new-list.txt --name "New Playlist" --dry-run
```

Then, if the matches look right:

```bash
python spotify_playlist.py playlists/new-list.txt --name "New Playlist"
```

After creation, future iterations should modify that same source file and use `sync_playlist.py` with both the correct file and playlist name, for example:

```bash
python sync_playlist.py playlists/new-list.txt --name "New Playlist"
```

Do not route later additions into another playlist merely because that playlist was created earlier in the project's history.
