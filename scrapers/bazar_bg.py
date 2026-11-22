"""Scraper for bazar.bg real estate listings (oblast Shumen & oblast Varna)."""
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

TX_SLUGS: dict[str, str] = {
    "sale": "prodazhba-imoti",
    "rent": "naemi-imoti",
}


class BazarBgScraper(BaseScraper):
    source_name = "bazar.bg"
    encoding = "utf-8"

    def build_url(self, region: str, transaction_type: str, page: int) -> str:
        tx = TX_SLUGS[transaction_type]
        url = f"https://bazar.bg/obiavi/{tx}/{region}"
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
            cards = soup.select("div.listItemContainerV2, div.listItemContainer")
            if not cards:
                break

            page_added = 0
            for card in cards:
                link_el = card.select_one("a.listItemLink[href]")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                ext_id = link_el.get("data-id", "")
                if not ext_id:
                    m_id = re.search(r"obiava-(\d+)", href)
                    ext_id = m_id.group(1) if m_id else href
                if not ext_id or ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                title_el = card.select_one("div.title span.title")
                title = clean_ws(title_el.get_text(" ", strip=True)) if title_el else clean_ws(link_el.get("title", ""))

                loc_el = card.select_one("span.location")
                location_raw = clean_ws(loc_el.get_text(" ", strip=True)) if loc_el else ""
                city, neighborhood = split_location(location_raw, region)

                date_el = card.select_one("span.date")
                published_raw = clean_ws(date_el.get_text(" ", strip=True)) if date_el else ""

                price_el = card.select_one("span.price")
                price_raw = clean_ws(price_el.get_text(" ", strip=True)) if price_el else ""
                price_eur, currency_raw = parse_price_eur(price_raw)
                # Skip placeholder 1 EUR prices as negotiable
                if price_eur is not None and price_eur <= 10:
                    price_eur = None

                img_el = card.select_one("img.cover")
                img_src = (img_el.get("data-src") or img_el.get("src") or "") if img_el else ""
                if img_src.startswith("//"):
                    img_src = f"https:{img_src}"
                if any(bad in img_src.lower() for bad in ("nopic", "no_photo", "no-photo", "default")):
                    img_src = ""

                area_sqm = parse_area_sqm(title)
                yard_sqm = parse_yard_sqm(title)
                floor, total_floors = parse_floor_info(title)

                results.append(
                    RawListing(
                        source=self.source_name,
                        external_id=ext_id,
                        url=href,
                        region=region,
                        transaction_type=transaction_type,
                        title=title,
                        property_type=normalize_property_type(title),
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
                        construction_type=parse_construction(title),
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
