"""Base scraper with polite rate limiting and graceful block detection."""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Literal, Optional

import httpx

from config import MAX_DELAY_SEC, MIN_DELAY_SEC, REQUEST_TIMEOUT_SEC, USER_AGENT
from models import RawListing

logger = logging.getLogger(__name__)


class BlockedBySiteError(RuntimeError):
    """Raised when a target site returns a CAPTCHA / anti-bot challenge or 403 block."""


class BaseScraper(ABC):
    source_name: str = "unknown"
    encoding: str = "utf-8"

    def __init__(self, min_delay: float = MIN_DELAY_SEC, max_delay: float = MAX_DELAY_SEC):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_SEC,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _polite_sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def fetch_html(self, url: str) -> Optional[str]:
        """Fetch HTML politely; detect and report blocks without bypassing them."""
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("[%s] HTTP error fetching %s: %s", self.source_name, url, exc)
            return None

        if resp.status_code in (403, 429):
            raise BlockedBySiteError(
                f"[{self.source_name}] Received HTTP {resp.status_code} on {url}. Stopping politely."
            )
        if resp.status_code != 200:
            logger.warning("[%s] HTTP %s for %s", self.source_name, resp.status_code, url)
            return None

        html = resp.content.decode(self.encoding, errors="replace")

        # Detect CAPTCHA / Cloudflare challenge markers
        lower_head = html[:4000].lower()
        if any(m in lower_head for m in ("cf-turnstile", "g-recaptcha", "hcaptcha", "just a moment...")):
            raise BlockedBySiteError(
                f"[{self.source_name}] Anti-bot / CAPTCHA challenge detected on {url}. Stopping politely."
            )

        return html

    @abstractmethod
    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 2,
    ) -> list[RawListing]:
        """Scrape listings for a given region and transaction type."""
        raise NotImplementedError
