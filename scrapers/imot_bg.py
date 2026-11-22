"""Scraper for imot.bg real estate listings (oblast Shumen & oblast Varna)."""
from __future__ import annotations

from datetime import datetime, timezone
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
    parse_phone,
    parse_price_eur,
    parse_yard_sqm,
    parse_year_built,
    split_location,
)

logger = logging.getLogger(__name__)

REGION_SLUGS: dict[str, str] = {
    "varna": "oblast-varna",
    "shumen": "oblast-shumen",
}

TX_SLUGS: dict[str, str] = {
    "sale": "prodazhbi",
    "rent": "naemi",
}


class ImotBgScraper(BaseScraper):
    source_name = "imot.bg"
    encoding = "windows-1251"

    def build_url(self, region: str, transaction_type: str, page: int) -> str:
        tx = TX_SLUGS[transaction_type]
        reg = REGION_SLUGS[region]
        base = f"https://www.imot.bg/obiavi/{tx}/{reg}"
        if page > 1:
            return f"{base}/p-{page}"
        return base

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
            cards = soup.select("div.item[id^='ida']")
            if not cards:
                logger.info("[%s] No more cards on page %d", self.source_name, page)
                break

            page_added = 0
            for card in cards:
                ext_id = card.get("id", "").removeprefix("ida").strip()
                if not ext_id or ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)

                listing = self._parse_card(card, ext_id, region, transaction_type)
                if listing:
                    results.append(listing)
                    page_added += 1

            logger.info("[%s] Parsed %d listings from page %d", self.source_name, page_added, page)
            if page < max_pages:
                self._polite_sleep()

        return results

    def _parse_card(
        self,
        card,
        ext_id: str,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"],
    ) -> RawListing | None:
        title_link = card.select_one("div.zaglavie a.title")
        if not title_link:
            return None

        href = title_link.get("href", "")
        url = f"https:{href}" if href.startswith("//") else href

        loc_el = title_link.select_one("location")
        location_raw = clean_ws(loc_el.get_text(" ", strip=True)) if loc_el else ""
        # Title without <location> child text
        title_parts = [t.strip() for t in title_link.find_all(string=True, recursive=False) if t.strip()]
        title = clean_ws(" ".join(title_parts))
        city, neighborhood = split_location(location_raw, region)

        price_el = card.select_one("div.price")
        price_raw = clean_ws(price_el.get_text(" ", strip=True)) if price_el else ""
        price_eur, currency_raw = parse_price_eur(price_raw)

        info_el = card.select_one("div.info")
        info_text = clean_ws(info_el.get_text(" ", strip=True)) if info_el else ""

        seller_el = card.select_one("div.seller .name")
        agency = clean_ws(seller_el.get_text(" ", strip=True)) if seller_el else ""
        is_private: bool | None = None
        if agency:
            is_private = "частно лице" in agency.lower()
        elif "частно лице" in info_text.lower():
            is_private = True
            agency = "Частно лице"

        img_el = card.select_one("img.pic")
        img_src = img_el.get("src", "") if img_el else ""
        if any(bad in img_src.lower() for bad in ("nopic", "no_photo", "no-photo", "default")):
            img_src = ""
        image_url = f"https:{img_src}" if img_src.startswith("//") else img_src

        # Count photos (imot.bg shows e.g. "и 10 снимки" + small thumbs)
        card_text = card.get_text(" ", strip=True)
        m_ph = re.search(r"и\s+(\d+)\s+снимк", card_text, re.I)
        if m_ph:
            photos_count = int(m_ph.group(1)) + 1
        elif image_url:
            photos_count = max(1, len(card.select("div.photo img")))
        else:
            photos_count = 0

        area_sqm = parse_area_sqm(info_text)
        yard_sqm = parse_yard_sqm(info_text)
        floor, total_floors = parse_floor_info(info_text)
        construction_type = parse_construction(info_text)
        year_built = parse_year_built(info_text)
        phone = parse_phone(info_text)
        property_type = normalize_property_type(f"{title} {info_text[:120]}")

        published_raw = ""
        m_ts = re.match(r"^[0-9a-z]{2}(\d{10})", ext_id, re.I)
        if m_ts:
            try:
                ts = int(m_ts.group(1))
                if 1262304000 <= ts <= 2000000000:
                    published_raw = datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y")
            except (ValueError, OSError):
                pass

        return RawListing(
            source=self.source_name,
            external_id=ext_id,
            url=url,
            region=region,
            transaction_type=transaction_type,
            title=f"{title}, {location_raw}".strip(", "),
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
            description=info_text[:500],
            image_url=image_url,
            photos_count=photos_count,
            published_raw=published_raw,
        )
