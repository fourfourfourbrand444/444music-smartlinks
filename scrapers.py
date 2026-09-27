"""
Browser-automation searcher for platforms with no free public search
API: Spotify.

Tidal and Audiomack used to be scraped for an exact per-track link, but
proved unreliable in this environment: Tidal's page rendered completely
blank under Selenium (empty body, title never updating) even after
extensive attempts at automation-fingerprint fixes, and Audiomack's DOM
made confident title/artist extraction too noisy to trust consistently.
Per direct confirmation that both platforms' search-results pages
reliably surface the correct song at the top for a real search, they're
now handled as a deterministic constructed search-URL in main.py instead
— no browser involved for either, so there's nothing left to fix here.

Reliability of what remains:
  - Spotify: search page is public and JS-rendered but generally stable;
    the biggest risk is CAPTCHA/bot-detection under heavy request volume,
    which SEARCH_DELAY_SECONDS in config.py exists to reduce.

Returns {"url":..., "confidence":...} or None. None means "couldn't
confirm a match" — the caller leaves that field blank and logs it as
needing manual entry. It never guesses.
"""
import re
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from link_scanner import extract_candidate_links
from matchers import best_match
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


def search_spotify(driver, artist: str, title: str):
    query = quote(f"{artist} {title}")
    driver.get(f"https://open.spotify.com/search/{query}/tracks")

    track_pattern = re.compile(r"open\.spotify\.com/track/")
    _wait_for_any_link(driver, track_pattern, timeout=config.PAGE_LOAD_TIMEOUT)

    # Preferred: Spotify's web player marks track rows with this testid.
    candidates = []
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tracklist-row"]')
        for row in rows[:8]:
            try:
                link_el = row.find_element(By.CSS_SELECTOR, 'a[href*="/track/"]')
                href = link_el.get_attribute("href")
                label = row.text.strip()
                candidates.append({"artist": "", "title": label, "url": href})
            except Exception:
                continue
    except Exception:
        pass

    if not candidates:
        candidates = extract_candidate_links(driver, track_pattern)

    match, confidence = best_match("", f"{artist} {title}", candidates)
    if match:
        # normalize away query params Spotify sometimes appends
        clean_url = match["url"].split("?")[0]
        return {"url": clean_url, "confidence": confidence}
    return None


SCRAPER_FUNCTIONS = {
    "spotify": search_spotify,
}
