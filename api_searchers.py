"""
Searchers for platforms that have a free public API — no Selenium, no
login, no anti-bot fights. These are the most reliable part of the whole
pipeline; if a platform is here, trust it more than the scrapers.
"""
import requests
from matchers import best_match, best_match_noisy
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
