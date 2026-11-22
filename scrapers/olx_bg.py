"""Scraper for olx.bg real estate listings (oblast Shumen & oblast Varna)."""
from __future__ import annotations

import logging
import re
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from models import RawListing
from scrapers.base import BaseScraper
from scrapers.utils import (
    clean_ws,
    normalize_property_type,
    parse_area_sqm,
    parse_construction,
    parse_floor_info,
    parse_price_eur,
    parse_yard_sqm,
    split_location,
)

logger = logging.getLogger(__name__)
BASE_URL = "https://www.olx.bg"

REGION_SLUGS: dict[str, str] = {
    "shumen": "oblast-shumen",
    "varna": "oblast-varna",
}

TX_SLUGS: dict[str, str] = {
    "sale": "prodazhbi",
    "rent": "naemi",
}


class OlxBgScraper(BaseScraper):
    source_name = "olx.bg"
    encoding = "utf-8"

    def build_url(self, region: str, transaction_type: str, page: int) -> str:
        tx = TX_SLUGS[transaction_type]
        reg = REGION_SLUGS[region]
        url = f"{BASE_URL}/nedvizhimi-imoti/{tx}/{reg}/"
        if page > 1:
            url += f"?page={page}"
        return url

    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 2,
    ) -> list[RawListing]:
        results: list[RawListing] = []
        seen_ids: set[str] = set()

        for page in range(1, max_pages + 1):
            url = self.build_url(region, transaction_type, page)
            logger.info("[%s] Fetching %s (%s) page %d", self.source_name, region, transaction_type, page)
            html = self.fetch_html(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div[data-cy='l-card']")
            if not cards:
                break

            page_added = 0
            for card in cards:
                link_el = card.select_one("a[href*='/d/ad/']")
                if not link_el:
                    continue
                raw_href = link_el.get("href", "")
                full = urljoin(BASE_URL, raw_href)
                parts = urlsplit(full)
                clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

                m_id = re.search(r"ID([A-Za-z0-9]+)\.html", parts.path)
                ext_id = m_id.group(1) if m_id else (card.get("id") or parts.path.strip("/"))
                if not ext_id or ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                title_el = card.select_one("h4, h6")
                title = clean_ws(title_el.get_text(" ", strip=True)) if title_el else ""

                price_el = card.select_one("p[data-testid='ad-price']")
                price_raw = clean_ws(price_el.get_text(" ", strip=True)) if price_el else ""
                price_eur, currency_raw = parse_price_eur(price_raw)
                if price_eur is not None and price_eur <= 10:
                    price_eur = None

                loc_date_el = card.select_one("p[data-testid='location-date']")
                loc_date = clean_ws(loc_date_el.get_text(" ", strip=True)) if loc_date_el else ""
                location_raw, published_raw = loc_date, ""
                if " - " in loc_date:
                    location_raw, published_raw = [p.strip() for p in loc_date.split(" - ", 1)]
                    published_raw = re.sub(r"^Обновено на\s+", "", published_raw, flags=re.I).strip()
                city, neighborhood = split_location(location_raw, region)

                full_text = clean_ws(card.get_text(" | ", strip=True))

                img_el = card.select_one("img")
                img_src = (img_el.get("src") or "") if img_el else ""
                if "no_thumbnail" in img_src or img_src.startswith("data:"):
                    img_src = ""
                else:
                    # Upgrade small thumbnail size to crisp medium photo
                    img_src = re.sub(r"s=\d+x\d+;q=\d+", "s=640x480;q=75", img_src)

                area_sqm = parse_area_sqm(full_text)
                yard_sqm = parse_yard_sqm(full_text)
                floor, total_floors = parse_floor_info(full_text)

                results.append(
                    RawListing(
                        source=self.source_name,
                        external_id=ext_id,
                        url=clean_url,
                        region=region,
                        transaction_type=transaction_type,
                        title=title,
                        property_type=normalize_property_type(f"{title} {full_text[:200]}"),
                        city=city,
                        neighborhood=neighborhood,
                        location_raw=location_raw,
                        price_eur=price_eur,
                        price_raw=price_raw,
                        currency_raw=currency_raw,
                        area_sqm=area_sqm,
                        yard_sqm=yard_sqm,
                        floor=floor,
                        total_floors=total_floors,
                        construction_type=parse_construction(full_text),
                        image_url=img_src,
                        photos_count=1 if img_src else 0,
                        published_raw=published_raw,
                    )
                )
                page_added += 1

            logger.info("[%s] Parsed %d listings from page %d", self.source_name, page_added, page)
            if page_added == 0:
                break
            if page < max_pages:
                self._polite_sleep()

        return results
