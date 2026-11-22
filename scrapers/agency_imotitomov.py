"""Scraper for Imoti Tomov (imotitomov.com) — Shumen real estate agency."""
from __future__ import annotations

import logging
import re
from typing import Literal

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
BASE_URL = "https://imotitomov.com"


class ImotiTomovScraper(BaseScraper):
    source_name = "imotitomov.com"
    encoding = "utf-8"

    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 2,
    ) -> list[RawListing]:
        if region != "shumen":
            return []

        status_slug = "for-sale" if transaction_type == "sale" else "for-rent"
        results: list[RawListing] = []
        seen_ids: set[str] = set()

        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}/status/{status_slug}/" + (f"page/{page}/" if page > 1 else "")
            logger.info("[%s] Fetching %s (%s) page %d", self.source_name, region, transaction_type, page)
            html = self.fetch_html(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div.item-listing-wrap")
            if not cards:
                break

            page_added = 0
            for card in cards:
                link_el = card.select_one("h2.item-title a, a[href*='/property/']")
                if not link_el:
                    continue
                full_url = link_el.get("href", "")
                slug = full_url.rstrip("/").split("/")[-1]
                ext_id = slug or full_url
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                title = clean_ws(link_el.get_text(" ", strip=True))
                text = clean_ws(card.get_text(" | ", strip=True))
                price_eur, currency_raw = parse_price_eur(text)

                addr_el = card.select_one("address.item-address, .item-address")
                loc_raw = clean_ws(addr_el.get_text(" ", strip=True)) if addr_el else title
                city, neighborhood = split_location(loc_raw, "shumen")

                # Houzez theme uses data-lazy-src / data-src for real images
                image_url = ""
                for img_el in card.select("img"):
                    for attr in ("data-lazy-src", "data-src", "src"):
                        cand = img_el.get(attr, "")
                        if cand and not cand.startswith("data:") and "logo" not in cand.lower():
                            image_url = cand
                            break
                    if image_url:
                        break

                area_sqm = parse_area_sqm(text)
                yard_sqm = parse_yard_sqm(text)
                floor, total_floors = parse_floor_info(text)

                results.append(
                    RawListing(
                        source=self.source_name,
                        external_id=ext_id,
                        url=full_url,
                        region="shumen",
                        transaction_type=transaction_type,
                        title=title,
                        property_type=normalize_property_type(f"{title} {text[:200]}"),
                        city=city or "Шумен",
                        neighborhood=neighborhood,
                        location_raw=loc_raw,
                        price_eur=price_eur,
                        price_raw=f"{int(price_eur)} €" if price_eur else "",
                        currency_raw=currency_raw,
                        area_sqm=area_sqm,
                        yard_sqm=yard_sqm,
                        floor=floor,
                        total_floors=total_floors,
                        construction_type=parse_construction(text),
                        agency="Имоти Томов",
                        is_private=False,
                        description=text[:400],
                        image_url=image_url,
                        photos_count=1 if image_url else 0,
                    )
                )
                page_added += 1

            logger.info("[%s] Parsed %d listings from page %d", self.source_name, page_added, page)
            if page_added == 0:
                break
            if page < max_pages:
                self._polite_sleep()

        return results
