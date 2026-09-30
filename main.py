"""
Run: python main.py

For every release that's Approved, past its release date, and still
missing at least one enabled store link, this searches only the
platforms that release doesn't already have a confirmed link for,
verifies each match with fuzzy confidence scoring, and writes confirmed
links straight into Firestore's smartLink.stores.* — the same fields
your admin panel's manual entry writes to.

Platforms already confirmed for a release are never re-searched, so
runs get faster over time as more releases fill in completely.

Spotify is handled per config.SPOTIFY_METHOD: "scraper" (default — the
public Spotify web search page via the browser, accepted only when the
artist AND a 60%+ title match, see scrapers.search_spotify) or "api"
(Spotify Web API, UPC first; needs a Premium developer-app owner). The
browser is only started when a Spotify search actually needs it. Every
Spotify decision is printed.

Each release is processed in its own try/except: if something
unexpected blows up partway through one release, that release is logged
as failed and the run moves on to the next one instead of dying entirely.

Nothing below CONFIDENCE_THRESHOLD gets written (Spotify uses its own
stricter rules instead). Those get printed in the end-of-run report so
you know what still needs a manual look.
"""
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import quote

import config
import firestore_sync
from api_searchers import search_deezer, search_apple_music, search_youtube
from api_searchers import search_spotify as search_spotify_api
import scrapers

# Deezer/Apple/YouTube were firing back-to-back with zero pacing across
# every release — fine at small batch sizes, but iTunes' Search API in
# particular silently rate-limits (returns an empty result set, not an
# error) once you're hammering it across 30-40+ releases in one run.
# Falls back to 1s if you haven't added API_DELAY_SECONDS to config.py.
API_DELAY_SECONDS = getattr(config, "API_DELAY_SECONDS", 1)

# Overridden here per manual verification across a real run: every match
# at 55% and above (YouTube, Deezer, Apple/iTunes) was checked by hand
# and confirmed correct. This intentionally overrides
# config.CONFIDENCE_THRESHOLD for this script rather than editing
# config.py, since that value may be relied on elsewhere.
# NOTE: Spotify no longer uses this — it has its own rules (config.SPOTIFY_*).
CONFIDENCE_THRESHOLD = 55.0

# Tidal's page rendered completely blank under Selenium no matter what
# was tried, and Audiomack's DOM made confident per-track extraction too
# noisy to trust. Per direct confirmation that both platforms' own
# search-results pages reliably surface the correct song at the top,
# these two are handled as a deterministic constructed link instead —
# no browser, no scraping, no confidence check. Every release gets one
# of these written automatically. Tradeoff worth knowing: this points to
# a search-results page, not a guaranteed-permanent deep link to that
# exact song — reliable for what's been checked so far, but not the
# same guarantee as an exact track URL.
SEARCH_LINK_PLATFORMS = {
    "tidal": "https://tidal.com/search?q={query}",
    "audiomack": "https://audiomack.com/search?q={query}",
}


def run():
    releases = firestore_sync.get_releases_needing_smartlinks()
    print(f"Found {len(releases)} release(s) needing store links.\n")

    if not releases:
        return

    flagged = []   # (release_label, field, reason)
    crashed = []   # (release_label, error)
    browser = {"driver": None}

    def get_driver():
        # Started only when a Spotify scraper search actually needs it.
        if browser["driver"] is None:
            from browser import make_driver
            browser["driver"] = make_driver()
        return browser["driver"]

    try:
        _process(releases, flagged, crashed, get_driver)
    finally:
        if browser["driver"] is not None:
            browser["driver"].quit()

    _print_report(flagged, crashed)


def _process(releases, flagged, crashed, get_driver):
    for i, release in enumerate(releases, 1):
        artist, title = release["artist"], release["title"]
        label = f"{artist} — {title}"
        missing = set(release.get("missing", []))
        recheck_only = release.get("recheck_only", False)
        print(f"[{i}/{len(releases)}] {label}  (missing: {', '.join(sorted(missing)) or 'none'})"
              + ("  [Spotify-only pass]" if recheck_only else ""))

        try:
            found = {}
            spotify_meta = None

            # ── Spotify (method set by config.SPOTIFY_METHOD) ───────
            if "spotify" in missing:
                result = None
                if config.SPOTIFY_METHOD == "api":
                    result = search_spotify_api(
                        artist, title,
                        upc=release.get("upc", ""),
                        release_date=release.get("releaseDate", ""),
                        previously_released=release.get("previouslyReleased", ""),
                    )
                else:
                    for attempt in range(config.RETRIES_PER_PLATFORM + 1):
                        try:
                            result = scrapers.search_spotify(get_driver(), artist, title)
                            break
                        except Exception as e:
                            if attempt < config.RETRIES_PER_PLATFORM:
                                time.sleep(2)
                                continue
                            print(f"    spotify      ERROR — {e}")
                if result and result["url"] != release.get("spotifyUrl", ""):
                    found["spotify"] = result["url"]
                    spotify_meta = {
                        "method": result["method"],
                        "score": result["confidence"],
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                    action = "replaced" if release.get("spotifyUrl") else "found"
                    print(f"    spotify      {result['confidence']:>5.1f}%  OK ({result['method']}, {action})")
                elif result:
                    print("    spotify      same link as before — unchanged")
                else:
                    if release.get("recheck"):
                        print("    spotify      no better match — existing link left as is")
                    else:
                        flagged.append((label, "spotify", "no confirmed match — left blank"))
                        print("    spotify      no confirmed match — left blank")
                time.sleep(config.SEARCH_DELAY_SECONDS if config.SPOTIFY_METHOD != "api" else API_DELAY_SECONDS)

            # ── Other API-based platforms (reliable) ────────────────
            if "deezer" in missing:
                result = search_deezer(artist, title)
                _record(found, flagged, label, "deezer", result)
                time.sleep(API_DELAY_SECONDS)

            wants_apple = "appleMusic" in missing
            wants_itunes = "itunes" in missing
            if wants_apple or wants_itunes:
                result = search_apple_music(artist, title)
                if result and result["confidence"] >= CONFIDENCE_THRESHOLD:
                    if wants_apple:
                        found["appleMusic"] = result["url"]
                    if wants_itunes:
                        found["itunes"] = result["url"]
                    print(f"    apple music/itunes  {result['confidence']:>5.1f}%  OK")
                else:
                    conf = result["confidence"] if result else 0
                    flagged.append((label, "appleMusic/itunes", f"confidence {conf:.1f}%"))
                    print(f"    apple music/itunes  {conf:>5.1f}%  low confidence — skipped")
                time.sleep(API_DELAY_SECONDS)

            if "youtube" in missing:
                result = search_youtube(artist, title)
                _record(found, flagged, label, "youtube", result)
                time.sleep(API_DELAY_SECONDS)

            # ── Search-link platforms (deterministic, no browser) ───
            for platform, url_template in SEARCH_LINK_PLATFORMS.items():
                if platform not in missing:
                    continue
                query = quote(f"{artist} {title}")
                found[platform] = url_template.format(query=query)
                print(f"    {platform:<12} search link written — OK (not a verified per-track match)")

            if found:
                firestore_sync.write_store_links(release["id"], found, spotify_meta)
                if not recheck_only:
                    firestore_sync.record_attempt(release["id"], made_progress=True)
                print(f"    → wrote {len(found)} link(s) to Firestore\n")
            elif recheck_only:
                print("    → Spotify-only pass: nothing to change\n")
            else:
                firestore_sync.record_attempt(release["id"], made_progress=False)
                new_attempts = release.get("attempts", 0) + 1
                print(f"    → nothing confirmed, all flagged for manual review "
                      f"(failed attempt {new_attempts}/{firestore_sync.STALL_THRESHOLD_RUNS})")
                if new_attempts >= firestore_sync.STALL_THRESHOLD_RUNS:
                    print(f"    ⚠ giving up on this release — will be skipped in future runs\n")
                else:
                    print()

        except Exception as e:
            # Whatever this was — unexpected API response, anything —
            # this release is logged as failed and the batch keeps
            # going instead of dying.
            print(f"    ✗ release crashed, skipping — {e}\n")
            crashed.append((label, str(e)))
            continue


def _record(found: dict, flagged: list, label: str, platform: str, result):
    if result and result["confidence"] >= CONFIDENCE_THRESHOLD:
        found[platform] = result["url"]
        print(f"    {platform:<12} {result['confidence']:>5.1f}%  OK")
    else:
        conf = result["confidence"] if result else 0
        flagged.append((label, platform, f"confidence {conf:.1f}%" if result else "no match found"))
        print(f"    {platform:<12} {conf:>5.1f}%  low confidence — skipped")


def _print_report(flagged: list, crashed: list):
    print("\n" + "=" * 60)
    if not flagged and not crashed:
        print("Every field on every release was confirmed. Nothing to review.")
        return
    if flagged:
        print(f"{len(flagged)} field(s) need manual entry:\n")
        for label, platform, reason in flagged:
            print(f"  - {label}: {platform} ({reason})")
    if crashed:
        print(f"\n{len(crashed)} release(s) crashed mid-run and need a re-run or manual check:\n")
        for label, err in crashed:
            print(f"  - {label}: {err}")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        print("\nFatal error:")
        traceback.print_exc()
