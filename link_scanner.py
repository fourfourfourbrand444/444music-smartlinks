"""
Instead of hand-picking CSS classes/data-testids per site (which break
the moment a platform redesigns), this scans every link on the loaded
search page for one matching that platform's known track-URL shape, and
pulls whatever text is near it as a rough label to fuzzy-match against.

Less precise than a hand-tuned selector, more resistant to markup churn.
If a platform's selectors are stable and known, prefer a direct selector
first and fall back to this.
"""
from selenium.webdriver.common.by import By


def extract_candidate_links(driver, url_pattern, max_candidates=10):
    candidates = []
    seen_urls = set()
    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
    except Exception:
        return candidates

    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if not href or href in seen_urls or not url_pattern.search(href):
            continue
        seen_urls.add(href)

        label = ""
        try:
            label = (a.text or "").strip()
        except Exception:
            pass
        if not label:
            try:
                parent = a.find_element(By.XPATH, "..")
                label = (parent.text or "").strip()
            except Exception:
                pass

        candidates.append({"artist": "", "title": label, "url": href})
        if len(candidates) >= max_candidates:
            break
    return candidates
