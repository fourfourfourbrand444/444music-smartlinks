"""Shared headless-Chrome setup for the scraping-based platform searchers."""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config


def make_driver():
    options = Options()

    # Don't wait for the browser's full "load" event — sites like
    # Spotify's web player keep persistent WebSocket/streaming
    # connections open indefinitely, so that event may never fire.
    # "eager" considers the page ready once the DOM is parsed, which
    # is all we need since every searcher does its own explicit
    # WebDriverWait for the specific elements it's looking for.
    options.page_load_strategy = "eager"

    if config.HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    # A realistic UA lowers (doesn't eliminate) the odds of being served
    # a bot-detection page instead of real results.
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Tidal was rendering a completely blank page under automation —
    # empty body, title never updating — even after the full page-load
    # timeout. These stack with the per-page navigator.webdriver CDP
    # override in scrapers.py's search_tidal to reduce the automation
    # fingerprint further. Not guaranteed to be the actual cause (could
    # also be a missing WebGL/media-capability API under headless on a
    # DRM-heavy streaming site), but these are standard, low-risk, and
    # worth having regardless.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    return driver
