"""Instrumental-first Spotify discovery. Seeds are leads, never proof of no vocals."""
from __future__ import annotations

import re

# Style-specific artists are discovery anchors, not an instrumental whitelist.
# Every returned Spotify recording still goes through track-level verification.
STYLE_SEEDS = {
    "heavy": (
        "Karma to Burn", "Belzebong", "Bongripper", "Clouds Taste Satanic",
        "Earth", "Grotto", "My Sleeping Karma", "Monkey3",
        "Yawning Man", "35007", "Causa Sui", "Tuber",
    ),
    "post": ("Russian Circles", "Pelican", "Toundra", "If These Trees Could Talk", "Caspian"),
    "electronic": ("Tycho", "Bonobo", "Boards of Canada"),
    "jazz": ("The Bad Plus", "Mammal Hands", "GoGo Penguin"),
}


def _search_queries(prompt):
    words = set(re.findall(r"[a-z]+", str(prompt).casefold()))
    heavy = bool(words & {"doom", "stoner", "sludge", "psychedelic", "psych", "metal", "riff"})
    post = bool(words & {"post", "math", "ambient", "cinematic"})
    electronic = bool(words & {"electronic", "downtempo", "trip", "chill", "synth"})
    jazz = "jazz" in words
    groups = [name for name, selected in
              (("heavy", heavy), ("post", post), ("electronic", electronic), ("jazz", jazz))
              if selected]
    artists = []
    for group in groups:
        artists.extend(STYLE_SEEDS[group])
    # Do not inject arbitrary genre anchors for unfamiliar instrumental styles.
    # Search directly using user-provided style words in that case.
    terms = [w for w in re.findall(r"[a-z]+", str(prompt).casefold())
             if w not in {"instrumental", "instrumentals", "no", "vocals", "vocal",
                          "only", "tracks", "songs", "playlist", "create", "a", "of",
                          "and", "absolutely", "for", "me", "the", "without"}]
    style = " ".join(dict.fromkeys(terms[:4]))
    queries = [f'artist:"{artist}"' for artist in dict.fromkeys(artists)]
    if style and not artists:
        # Generic full-text matching confuses words like "doom" with artist
        # names (e.g. MF DOOM); seeded genre requests do not need it.
        queries.append(style + " instrumental")
    return queries[:16]


def discover(token, spotify, prompt, excluded_uris=(), *, limit=100):
    """Collect genre-targeted Spotify recordings for later strict verification.

    Spotify search is discovery only. Its genre/artist signals are not evidence
    that a particular recording is free of vocals.
    """
    seen = set(excluded_uris)
    found = []
    queries = _search_queries(prompt)
    pools = []
    # Give every seed a chance before consuming the global limit.
    # One page per seed avoids exhausting the budget on the first bands.
    for query in queries:
        wanted_artist = query[len('artist:"'):-1].casefold() if query.startswith('artist:"') else None
        try:
            response = spotify.api_request(
                "GET", "/search", token,
                params={"q": query, "type": "track", "limit": 10, "offset": 0},
            )
            rows = response.json().get("tracks", {}).get("items", []) or []
        except Exception as exc:
            print(f"[Tune Raider] instrumental-first Spotify query failed ({query}): {exc}", flush=True)
            continue
        pool = []
        for track in rows:
            if not isinstance(track, dict) or not track.get("uri"):
                continue
            artists = track.get("artists") or []
            name = str((artists[0] if artists else {}).get("name") or "").casefold()
            if wanted_artist and name != wanted_artist:
                continue
            pool.append(track)
        if pool:
            pools.append(pool)

    # Interleave the pools, preserving per-artist order while diversifying
    # the set that will be checked against instrumental evidence.
    for index in range(max((len(pool) for pool in pools), default=0)):
        for pool in pools:
            if index >= len(pool):
                continue
            track = pool[index]
            uri = track["uri"]
            if uri in seen:
                continue
            seen.add(uri)
            found.append(track)
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    print(f"[Tune Raider] instrumental-first discovery: {len(found)} Spotify recordings "
          f"from {len(queries)} targeted queries (unverified)", flush=True)
    return found
