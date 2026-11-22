"""Scraper for Imoti Silvi (imotisilvi.bg) — Shumen real estate agency."""
from __future__ import annotations

import logging
import re
from typing import Literal
from urllib.parse import urljoin

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
BASE_URL = "https://imotisilvi.bg/"


class ImotiSilviScraper(BaseScraper):
    source_name = "imotisilvi.bg"
    encoding = "utf-8"

    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 2,
    ) -> list[RawListing]:
        if region != "shumen":
            return []

        results: list[RawListing] = []
        seen_ids: set[str] = set()

        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}properties.php?type={transaction_type}&page={page}"
            logger.info("[%s] Fetching %s (%s) page %d", self.source_name, region, transaction_type, page)
            html = self.fetch_html(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div.property-card-rounded, div.property-card")
            if not cards:
                # Fallback: collect unique parent containers of property.php?id= links
                seen_cards = set()
                for a in soup.select("a[href*='property.php?id=']"):
                    parent = a.find_parent("div", class_=re.compile(r"rounded|card|border"))
                    if parent and id(parent) not in seen_cards:
                        seen_cards.add(id(parent))
                        cards.append(parent)
            if not cards:
                break

            page_added = 0
            for card in cards:
                link_el = card.select_one("a[href*='property.php?id=']")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                m_id = re.search(r"id=(\d+)", href)
                ext_id = m_id.group(1) if m_id else href
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                full_url = urljoin(BASE_URL, href)
                text = clean_ws(card.get_text(" | ", strip=True))
                price_eur, currency_raw = parse_price_eur(text)

                h_el = card.select_one("h2, h3, h4, .font-bold")
                title = clean_ws(h_el.get_text(" ", strip=True)) if h_el else text[:100]

                # Location usually has "Шумен" or "с."
                loc_raw = ""
                for part in text.split(" | "):
                    if any(k in part.lower() for k in ("шумен", "нови пазар", "преслав", "с.", "кв.")):
                        if len(part) < 80 and "eur" not in part.lower():
                            loc_raw = part
                            break
                city, neighborhood = split_location(loc_raw, "shumen")

                img_el = card.select_one("img")
                img_src = (img_el.get("data-src") or img_el.get("src") or "") if img_el else ""
                image_url = urljoin(BASE_URL, img_src) if img_src and not img_src.startswith("data:") else ""

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
                        city=city,
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
                        agency="Недвижими имоти Силви",
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
