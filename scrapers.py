"""
Browser-automation searcher for platforms with no free public search
API: Spotify.

Why this exists again: Spotify's Web API now requires an active Premium
subscription on the developer app's owner account (HTTP 403 otherwise),
so Spotify goes back to the public web search page. What changed from the
old version is how a match is accepted. The old scraper only had one blob
of row text, no artist, and accepted anything scoring 55%+, which is how
a wrong song got through. Now every result row is read as a title plus
its artist names, and a result is accepted ONLY if BOTH pass:
  - the release's main artist is one of the artists on the result
  - title similarity >= config.SPOTIFY_TITLE_MIN (60)
A release-date check is not possible from the search page, so it isn't
used here. If rows can't be read, nothing is accepted and Spotify stays
blank — it never guesses.

Tidal and Audiomack are handled in main.py as constructed search links
(no browser involved).

Returns {"url":..., "confidence":..., "method": "scraper"} or None. None
means "couldn't confirm a match" — the caller leaves that field blank and
logs it as needing manual entry.
"""
import re
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from matchers import title_similarity, artist_matches
import config


def _wait_for_any_link(driver, url_pattern, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(
                url_pattern.search(a.get_attribute("href") or "")
                for a in d.find_elements(By.TAG_NAME, "a")
            )
        )
    except TimeoutException:
        pass  # let the caller's extraction attempt run anyway — may still find something
    except WebDriverException:
        # session/browser-level failure (crashed tab, dead session, etc.) —
        # not a "no match" case, but also not ours to recover from here.
        # Let it propagate; the caller's retry loop decides what to do.
        raise


def _text(el) -> str:
    return (el.text or el.get_attribute("textContent") or "").strip()


def _read_track_rows(driver) -> list:
    """Each result row -> {"title", "artists", "url"}."""
    candidates, seen = [], set()
    try:
        rows = driver.find_elements(
            By.CSS_SELECTOR, '[data-testid="tracklist-row"], div[role="row"]'
        )
    except Exception:
        rows = []
    for row in rows[:10]:
        try:
            link_el = row.find_element(By.CSS_SELECTOR, 'a[href*="/track/"]')
            href = (link_el.get_attribute("href") or "").split("?")[0]
            if not href or href in seen:
                continue
            artists = []
            for a in row.find_elements(By.CSS_SELECTOR, 'a[href*="/artist/"]'):
                name = _text(a)
                if name and name not in artists:
                    artists.append(name)
            seen.add(href)
            candidates.append({"title": _text(link_el), "artists": artists, "url": href})
        except Exception:
            continue
    return candidates


def search_spotify(driver, artist: str, title: str):
    query = quote(f"{artist} {title}")
    driver.get(f"https://open.spotify.com/search/{query}/tracks")

    track_pattern = re.compile(r"open\.spotify\.com/track/")
    _wait_for_any_link(driver, track_pattern, timeout=config.PAGE_LOAD_TIMEOUT)

    candidates = _read_track_rows(driver)
    print(f"    [spotify] read {len(candidates)} result row(s) from the search page")

    passing = []
    for c in candidates:
        t_score = title_similarity(title, c["title"])
        a_ok = artist_matches(artist, c["artists"])
        t_ok = t_score >= config.SPOTIFY_TITLE_MIN
        failed = []
        if not a_ok:
            failed.append("artist")
        if not t_ok:
            failed.append("title")
        verdict = "ACCEPT" if not failed else "reject (" + ", ".join(failed) + ")"
        print(f"    [spotify] {c['artists']} - {c['title']!r} | title {t_score:.0f}% | {verdict}")
        if not failed:
            passing.append((t_score, c))

    if not passing:
        return None
    best_score, best = max(passing, key=lambda p: p[0])
    return {"url": best["url"], "confidence": round(best_score, 1), "method": "scraper"}


SCRAPER_FUNCTIONS = {
    "spotify": search_spotify,
}
