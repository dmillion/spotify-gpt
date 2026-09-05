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

The script requests these scopes:

- `playlist-modify-private`
- `playlist-modify-public`

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
- `POST /me/playlists` — create the playlist
- `POST /playlists/{playlist_id}/items` — add up to 100 items per request

The older `/playlists/{playlist_id}/tracks` add-tracks endpoint is deprecated; this project uses the current `/items` endpoint.
