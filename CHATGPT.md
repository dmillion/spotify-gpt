# ChatGPT Operating Guide

This repository is a small Spotify playlist curation tool. A user can ask ChatGPT to curate or revise playlist files in this repo, then run the local sync script to push those changes to their own Spotify account.

## Primary goal

When the user asks for playlist curation, make the requested music changes in the repository rather than only returning a prose list.

Typical requests:

- "Add 15 songs like these."
- "Make this playlist sludgier."
- "Remove the songs that are too slow."
- "Build me a new playlist around these three bands."

## Repository layout

- `spotify_playlist.py` — creates a Spotify playlist from a track-list file.
- `sync_playlist.py` — syncs a track-list file into an existing Spotify playlist without intentionally duplicating tracks.
- `playlists/` — playlist definitions.
- `.env.example` — example Spotify configuration only.
- `README.md` — installation and usage instructions.

Playlist files use this format:

```text
# comments are allowed
Artist | Track Title
Another Artist | Another Track
```

## How to handle playlist requests

1. Read the relevant playlist file before editing it.
2. Preserve existing tracks unless the user explicitly asks to remove or replace them.
3. Add tracks that genuinely fit the user's stated musical direction; do not pad the list with generic genre staples merely to hit a number.
4. Avoid duplicate artist/title entries.
5. Prefer canonical Spotify artist and track spellings when known.
6. Keep useful section comments when they help explain the playlist's structure.
7. Commit the resulting playlist-file change to GitHub.
8. Tell the user the simple local command needed to sync it.

For the existing sludge playlist, the Spotify playlist has been renamed to:

```text
Sludge Grinder
```

The corresponding source file is:

```text
playlists/sludge-with-grind-brain.txt
```

A normal sync is:

```bash
python sync_playlist.py --name "Sludge Grinder"
```

A safe preview is:

```bash
python sync_playlist.py --name "Sludge Grinder" --dry-run
```

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

Keep instructions short. After making a playlist change, the preferred user-facing directions are generally:

```bash
git pull
python sync_playlist.py --name "Playlist Name"
```

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

1. Create a new text file under `playlists/` with a descriptive filename.
2. Populate it using `Artist | Track Title` lines.
3. Commit it.
4. Give the user a dry-run command first, for example:

```bash
python spotify_playlist.py playlists/new-list.txt --name "New Playlist" --dry-run
```

Then, if the matches look right:

```bash
python spotify_playlist.py playlists/new-list.txt --name "New Playlist"
```

After creation, future iterations should use `sync_playlist.py` against that playlist rather than creating duplicates.
