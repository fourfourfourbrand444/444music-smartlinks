"""
Searchers for platforms that have a free public API — no Selenium, no
login, no anti-bot fights. These are the most reliable part of the whole
pipeline; if a platform is here, trust it more than the scrapers.
"""
import time
import requests
from matchers import (
    best_match, best_match_noisy,
    title_similarity, artist_matches, dates_close,
)
import config


def search_deezer(artist: str, title: str):
    """Deezer's public search API. No key required.

    Uses a plain-text query (not the artist:"..." track:"..." exact-
    phrase syntax) so Deezer returns a broader candidate list — real
    fuzzy matching via best_match() does the filtering, same as every
    other searcher in this file. The quoted exact-match syntax was
    silently returning zero results for anything that wasn't a
    character-for-character match (featuring artists, punctuation,
    minor spelling differences all broke it)."""
    try:
        resp = requests.get(
            "https://api.deezer.com/search",
            params={"q": f"{artist} {title}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = [
            {
                "artist": item["artist"]["name"],
                "title": item["title"],
                "url": item["link"],
            }
            for item in data.get("data", [])[:5]
        ]
        match, confidence = best_match(artist, title, candidates)
        if match:
            return {"url": match["url"], "confidence": confidence}
    except Exception as e:
        print(f"  [deezer] search failed: {e}")
    return None


def search_apple_music(artist: str, title: str):
    """iTunes Search API. Returns a music.apple.com link (trackViewUrl)
    which doubles as both the 'Apple Music' and legacy 'iTunes' link in
    your admin — current API responses point trackViewUrl at
    music.apple.com, not the old itunes.apple.com format."""
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": f"{artist} {title}", "entity": "song", "limit": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = [
            {
                "artist": item.get("artistName", ""),
                "title": item.get("trackName", ""),
                "url": item.get("trackViewUrl", ""),
            }
            for item in data.get("results", [])
            if item.get("trackViewUrl")
        ]
        match, confidence = best_match(artist, title, candidates)
        if match:
            return {"url": match["url"], "confidence": confidence}
    except Exception as e:
        print(f"  [apple_music] search failed: {e}")
    return None


def search_youtube(artist: str, title: str):
    """YouTube Data API v3 search.list. Costs 100 quota units per call —
    same key your broadcast backend already uses. Set YOUTUBE_API_KEY.

    Video titles are messy in a way Deezer/iTunes results aren't —
    "Artist - Song (Official Music Video) ft. X [Prod. by Y]" carries a
    lot of padding around the actual title/artist. That padding drags
    down a plain token_sort_ratio comparison the same way noisy
    Audiomack labels did, so this is scored with best_match_noisy
    (token_set_ratio) instead of best_match — it isn't punished for
    extra unrelated words as long as the real title/artist text is
    present somewhere in the video title."""
    if not config.YOUTUBE_API_KEY:
        print("  [youtube] skipped — no YOUTUBE_API_KEY set")
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": f"{artist} {title}",
                "type": "video",
                "maxResults": 5,
                "key": config.YOUTUBE_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            print(f"  [youtube] API error: {data['error'].get('message')}")
            return None
        candidates = [
            {
                # Topic-channel uploads (official auto-generated audio)
                # put the artist name in channelTitle as "Artist - Topic",
                # not in the video title itself — snippet.title is often
                # just the bare song name. Ignoring channelTitle meant
                # even the correct, first-result official upload could
                # only ever match on title tokens, tanking the score.
                "artist": item["snippet"].get("channelTitle", "").replace(" - Topic", "").strip(),
                "title": item["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            }
            for item in data.get("items", [])
        ]
        match, confidence = best_match_noisy(artist, title, candidates)
        if candidates:
            # Debug: show what the top candidate actually was, regardless
            # of whether it passed CONFIDENCE_THRESHOLD — this is the only
            # way to tell "genuinely similar match, conservative score"
            # apart from "wrong video, coincidentally scored this way."
            top = max(candidates, key=lambda c: best_match_noisy(artist, title, [c])[1])
            print(f"    [youtube debug] top candidate: {top['artist']!r} - {top['title']!r} ({top['url']})")
        if match:
            return {"url": match["url"], "confidence": confidence}
    except Exception as e:
        print(f"  [youtube] search failed: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════
# Spotify Web API (Client Credentials)
#
# Order of attack:
#   1. UPC lookup (q=upc:<code>, type=album). Exact release or nothing.
#      If the release isn't on Spotify yet this returns nothing and we
#      fall through — we never guess from a UPC.
#   2. Name search fallback, accepted ONLY if ALL of these pass:
#        - the release's main artist is one of the artists on the result
#        - title similarity >= config.SPOTIFY_TITLE_MIN
#        - for new releases (previouslyReleased "No"): Spotify's release
#          date is within config.SPOTIFY_DATE_TOLERANCE_DAYS of ours
#
# Every candidate and decision is printed so a wrong link can be traced
# to the exact check that let it through.
# ═══════════════════════════════════════════════════════════════════════

_spotify_token = {"value": None, "expires": 0.0}


def _raise_for_spotify(resp):
    """Like resp.raise_for_status(), but includes Spotify's own error
    message in the log (a bare '403 Forbidden' doesn't say why)."""
    if resp.status_code >= 400:
        where = resp.url.split("?")[0]
        raise RuntimeError(f"HTTP {resp.status_code} from {where} — {resp.text[:300]}")


def _get_spotify_token():
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        return None
    if _spotify_token["value"] and time.time() < _spotify_token["expires"] - 60:
        return _spotify_token["value"]
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    _raise_for_spotify(resp)
    data = resp.json()
    _spotify_token["value"] = data["access_token"]
    _spotify_token["expires"] = time.time() + int(data.get("expires_in", 3600))
    return _spotify_token["value"]


def _spotify_get(path: str, params: dict):
    token = _get_spotify_token()
    if not token:
        return None
    resp = requests.get(
        f"https://api.spotify.com/v1{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    _raise_for_spotify(resp)
    return resp.json()


def _spotify_by_upc(upc: str, title: str):
    for market in config.SPOTIFY_MARKETS:
        params = {"q": f"upc:{upc}", "type": "album", "limit": 1}
        if market:
            params["market"] = market
        data = _spotify_get("/search", params)
        items = ((data or {}).get("albums") or {}).get("items") or []
        if not items:
            continue

        album = items[0]
        album_artists = [a.get("name", "") for a in album.get("artists", [])]
        print(f"    [spotify] UPC {upc} → album {album.get('name')!r} by {album_artists} "
              f"(released {album.get('release_date')}, market {market or 'none'})")

        # Turn the album into the specific track link (that's what the
        # smart link stores). Singles have one track; for multi-track
        # releases pick the best title match, else fall back to the album.
        tparams = {"limit": 50}
        if market:
            tparams["market"] = market
        tdata = _spotify_get(f"/albums/{album['id']}/tracks", tparams)
        tracks = (tdata or {}).get("items") or []
        best, best_score = None, -1.0
        for t in tracks:
            score = title_similarity(title, t.get("name", ""))
            if score > best_score:
                best, best_score = t, score

        if best and (len(tracks) == 1 or best_score >= config.SPOTIFY_TITLE_MIN):
            url = best["external_urls"]["spotify"]
        else:
            url = album["external_urls"]["spotify"]
        return {"url": url.split("?")[0], "confidence": 100.0, "method": "upc"}

    print(f"    [spotify] UPC {upc}: no album found (not on Spotify yet, or not available in the tried markets)")
    return None


def _spotify_by_name(artist: str, title: str, release_date: str, previously_released: str):
    data = _spotify_get("/search", {"q": f"{title} {artist}", "type": "track", "limit": 10})
    items = ((data or {}).get("tracks") or {}).get("items") or []
    is_new = str(previously_released).strip().lower() == "no"
    if not is_new:
        print("    [spotify] not a new release — release-date check skipped (artist + title still required)")

    passing = []
    for item in items:
        c_artists = [a.get("name", "") for a in item.get("artists", [])]
        c_title = item.get("name", "")
        c_date = (item.get("album") or {}).get("release_date", "")
        t_score = title_similarity(title, c_title)

        a_ok = artist_matches(artist, c_artists)
        t_ok = t_score >= config.SPOTIFY_TITLE_MIN
        d_ok = dates_close(release_date, c_date, config.SPOTIFY_DATE_TOLERANCE_DAYS) if is_new else True

        failed = []
        if not a_ok:
            failed.append("artist")
        if not t_ok:
            failed.append("title")
        if not d_ok:
            failed.append("date")
        verdict = "ACCEPT" if not failed else "reject (" + ", ".join(failed) + ")"
        print(f"    [spotify] {c_artists} - {c_title!r} | title {t_score:.0f}% | "
              f"released {c_date or '?'} | {verdict}")

        if not failed:
            passing.append((t_score, item))

    if not passing:
        return None
    best_score, best_item = max(passing, key=lambda p: p[0])
    return {
        "url": best_item["external_urls"]["spotify"].split("?")[0],
        "confidence": round(best_score, 1),
        "method": "name",
    }


def search_spotify(artist: str, title: str, upc: str = "",
                   release_date: str = "", previously_released: str = ""):
    """Returns {"url", "confidence", "method"} for a confirmed match, or
    None. None means 'nothing trustworthy found' — the caller leaves the
    field blank."""
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        print("  [spotify] skipped — SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set")
        return None
    try:
        if config.SPOTIFY_USE_UPC and str(upc).strip():
            result = _spotify_by_upc(str(upc).strip(), title)
            if result:
                return result
        return _spotify_by_name(artist, title, release_date, previously_released)
    except Exception as e:
        print(f"  [spotify] search failed: {e}")
    return None
