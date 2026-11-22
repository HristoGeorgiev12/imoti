"""Configuration for the local real estate aggregator (Shumen & Varna)."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_JSON_PATH = DATA_DIR / "listings.json"
RAW_JSON_PATH = DATA_DIR / "raw_listings.json"

# Target regions (област Шумен и област Варна)
DEFAULT_REGIONS = ["shumen", "varna"]
DEFAULT_TRANSACTIONS = ["sale", "rent"]

# Polite scraping defaults
REQUEST_TIMEOUT_SEC = 20.0
MIN_DELAY_SEC = 1.2
MAX_DELAY_SEC = 2.5
DEFAULT_MAX_PAGES = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# Currency conversion (fixed BGN/EUR peg)
BGN_PER_EUR = 1.95583

# Deduplication / multi-agency merge thresholds
AREA_TOLERANCE_PCT = 0.04      # ±4% (or ±2 sq.m minimum)
AREA_TOLERANCE_MIN_SQM = 2.5
PRICE_TOLERANCE_PCT = 0.08     # ±8% (agencies often vary price slightly or include commission)
TITLE_SIMILARITY_BONUS = 0.45
