# spotify-gpt

Small local tool for turning AI-generated track lists into Spotify playlists.

It uses Spotify's Web API with **Authorization Code + PKCE**, so no Spotify client secret is stored in the repo. The first run opens a browser for Spotify authorization; subsequent runs reuse a locally cached refresh token.

## Spotify app setup

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
2. Create an app and enable the **Web API**.
3. In the app settings, add this Redirect URI exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Copy the app's **Client ID**.

The scripts may request these scopes depending on the operation:

- `playlist-modify-private`
- `playlist-modify-public`
- `playlist-read-private`

## Local setup

```bash
git clone https://github.com/dmillion/spotify-gpt.git
cd spotify-gpt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` and replace `your_client_id_here` with the Spotify Client ID.

`.env` is already ignored by Git.

## Sharing / installing for another user

Each user should create **their own Spotify Developer app** and use their own Client ID. This keeps Spotify authorization and account access separate while allowing everyone to use the same repository and playlist files.

For another user:

1. Clone this repository.
2. Create a Spotify app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
3. Enable the Web API and add `http://127.0.0.1:8888/callback` as the Redirect URI.
4. Copy `.env.example` to `.env`.
5. Put that app's Client ID in `.env` as `SPOTIFY_CLIENT_ID`.
6. Create/activate the Python virtual environment and install `requirements.txt` as shown above.
7. Run the desired playlist command. A browser will open and the user signs into **their own Spotify account** and approves access.

No Client Secret needs to be shared or stored. This project uses PKCE.

The following files are intentionally local and should not be committed:

- `.env` — contains the user's Spotify app Client ID/configuration.
- `~/.cache/spotify-gpt/token.json` — contains that user's Spotify OAuth tokens and lives outside the repository.

Spotify Development Mode has account/app restrictions and is intended for development and personal projects. Having each person create their own developer app avoids sharing one app's user allowance and keeps credentials/account authorization isolated.

## Create the included playlist

The repo includes `playlists/sludge-with-grind-brain.txt`.

First, verify Spotify's matches without creating anything:

```bash
python spotify_playlist.py --dry-run
```

Then create the playlist:

```bash
python spotify_playlist.py
```

By default it creates a **private** playlist named `Sludge With Grind Brain`.

## Sync an existing playlist

`sync_playlist.py` adds tracks from the track-list file that are not already in an existing playlist. It does not intentionally duplicate tracks already present.

For example, to update the renamed `Sludge Grinder` playlist:

```bash
python sync_playlist.py --name "Sludge Grinder" --dry-run
python sync_playlist.py --name "Sludge Grinder"
```

The first sync may open Spotify authorization again because syncing a private playlist requires `playlist-read-private` in addition to the playlist modification scopes.

## Create another playlist

Track-list format:

```text
# comments are allowed
Artist Name | Track Title
Another Artist | Another Track
```

Then run:

```bash
python spotify_playlist.py playlists/my-playlist.txt \
  --name "My Playlist" \
  --description "Made from a ChatGPT recommendation list"
```

Add `--public` if you want the playlist public.

## Authentication/token storage

The OAuth token is stored outside the repository at:

```text
~/.cache/spotify-gpt/token.json
```

The script attempts to set the token file to user-only permissions (`0600`) and refreshes expired access tokens automatically.

To force a fresh Spotify login:

```bash
rm ~/.cache/spotify-gpt/token.json
python spotify_playlist.py --dry-run
```

## Current Spotify API endpoints used

- `GET /search` — resolve artist/title pairs to Spotify tracks
- `GET /me/playlists` — find an existing playlist for sync
- `GET /playlists/{playlist_id}/items` — read existing playlist items for deduplication
- `POST /me/playlists` — create a playlist
- `POST /playlists/{playlist_id}/items` — add up to 100 items per request

The older `/playlists/{playlist_id}/tracks` add-tracks endpoint is deprecated; this project uses the current `/items` endpoint.
