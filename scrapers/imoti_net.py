"""Scraper for imoti.net real estate listings (oblast Shumen & oblast Varna)."""
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
    parse_phone,
    parse_price_eur,
    parse_yard_sqm,
    parse_year_built,
    split_location,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.imoti.net"

TX_SLUGS: dict[str, str] = {
    "sale": "prodava",
    "rent": "pod-naem",
}


class ImotiNetScraper(BaseScraper):
    source_name = "imoti.net"
    encoding = "utf-8"

    def build_url(self, region: str, transaction_type: str, page: int) -> str:
        tx = TX_SLUGS[transaction_type]
        url = f"{BASE_URL}/bg/obiavi/r/{tx}/{region}"
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
            cards = soup.select("ul.list-view > li.clearfix")
            if not cards:
                logger.info("[%s] No more cards on page %d", self.source_name, page)
                break

            page_added = 0
            for card in cards:
                listing = self._parse_card(card, region, transaction_type)
                if not listing or listing.external_id in seen_ids:
                    continue
                seen_ids.add(listing.external_id)
                results.append(listing)
                page_added += 1

            logger.info("[%s] Parsed %d listings from page %d", self.source_name, page_added, page)
            if page < max_pages:
                self._polite_sleep()

        return results

    def _parse_card(
        self,
        card,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"],
    ) -> RawListing | None:
        link_el = card.select_one("a[href*='/bg/obiava/']")
        if not link_el:
            return None

        raw_href = link_el.get("href", "")
        full_url = urljoin(BASE_URL, raw_href)
        # Strip transient ?sid=... query string for stable canonical URL
        parts = urlsplit(full_url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

        m_id = re.search(r"/(\d+)/?$", parts.path)
        ext_id = m_id.group(1) if m_id else parts.path.strip("/")

        h3_el = card.select_one("header h3")
        title = clean_ws(h3_el.get_text(" ", strip=True)) if h3_el else ""

        loc_el = card.select_one("header span.location")
        location_raw = clean_ws(loc_el.get_text(" ", strip=True)) if loc_el else ""
        city, neighborhood = split_location(location_raw, region)

        price_el = card.select_one("header strong.price")
        price_raw = clean_ws(price_el.get_text(" ", strip=True)) if price_el else ""
        price_eur, currency_raw = parse_price_eur(price_raw)

        text_box = card.select_one("div.real-estate-text")
        box_text = clean_ws(text_box.get_text(" | ", strip=True)) if text_box else ""

        # Agency extraction ("публикувана от : Матена")
        agency = ""
        is_private: bool | None = None
        m_ag = re.search(r"публикувана от\s*:\s*([^|]+)", box_text, re.I)
        if m_ag:
            agency = clean_ws(m_ag.group(1))
            is_private = "частно лице" in agency.lower()

        desc_el = card.select_one("div.real-estate-text p")
        description = clean_ws(desc_el.get_text(" ", strip=True)) if desc_el else ""

        img_el = card.select_one("figure img")
        img_src = img_el.get("src", "") if img_el else ""
        image_url = urljoin(BASE_URL, img_src) if img_src else ""

        area_sqm = parse_area_sqm(f"{title} {box_text}")
        yard_sqm = parse_yard_sqm(box_text)
        floor, total_floors = parse_floor_info(box_text)
        construction_type = parse_construction(box_text)
        year_built = parse_year_built(box_text)
        phone = parse_phone(box_text)
        property_type = normalize_property_type(title)

        return RawListing(
            source=self.source_name,
            external_id=ext_id,
            url=clean_url,
            region=region,
            transaction_type=transaction_type,
            title=title,
            property_type=property_type,
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
            construction_type=construction_type,
            year_built=year_built,
            agency=agency,
            is_private=is_private,
            phone=phone,
            description=description[:500],
            image_url=image_url,
        )
