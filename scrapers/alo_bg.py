"""Scraper for alo.bg real estate listings (oblast Shumen & oblast Varna)."""
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
    parse_phone,
    parse_price_eur,
    parse_yard_sqm,
    parse_year_built,
    split_location,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alo.bg"

REGION_IDS: dict[str, int] = {
    "varna": 3,
    "shumen": 26,
}

CATEGORY_PATHS: dict[str, list[str]] = {
    "sale": [
        "/obiavi/imoti-prodajbi/apartamenti-stai/",
        "/obiavi/imoti-prodajbi/kashti-vili/",
    ],
    "rent": [
        "/obiavi/imoti-naemi/apartamenti-stai/",
        "/obiavi/imoti-naemi/kashti-vili/",
    ],
}


class AloBgScraper(BaseScraper):
    source_name = "alo.bg"
    encoding = "utf-8"

    def build_url(self, region: str, path: str, page: int) -> str:
        rid = REGION_IDS[region]
        url = f"{BASE_URL}{path}?region_id={rid}"
        if page > 1:
            url += f"&page={page}"
        return url

    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 2,
    ) -> list[RawListing]:
        results: list[RawListing] = []
        seen_ids: set[str] = set()

        for path in CATEGORY_PATHS[transaction_type]:
            for page in range(1, max_pages + 1):
                url = self.build_url(region, path, page)
                logger.info("[%s] Fetching %s (%s) %s page %d", self.source_name, region, transaction_type, path.strip("/").split("/")[-1], page)
                html = self.fetch_html(url)
                if not html:
                    break

                soup = BeautifulSoup(html, "lxml")
                cards = soup.select("div[id^='adrows_']")
                if not cards:
                    logger.info("[%s] No more cards on page %d", self.source_name, page)
                    break

                page_added = 0
                for card in cards:
                    card_id = card.get("id", "")
                    m_id = re.search(r"adrows_(\d+)", card_id)
                    if not m_id:
                        continue
                    ext_id = m_id.group(1)
                    if ext_id in seen_ids:
                        continue
                    seen_ids.add(ext_id)

                    listing = self._parse_card(card, ext_id, region, transaction_type)
                    if listing:
                        results.append(listing)
                        page_added += 1

                logger.info("[%s] Parsed %d listings from page %d", self.source_name, page_added, page)
                self._polite_sleep()

        return results

    def _parse_card(
        self,
        card,
        ext_id: str,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"],
    ) -> RawListing | None:
        title_el = card.select_one("h3.listtop-item-title, h3.listvip-item-title, h3")
        title = clean_ws(title_el.get_text(" ", strip=True)) if title_el else ""

        link_el = card.select_one("a[href]")
        href = link_el.get("href", "") if link_el else f"/{ext_id}"
        url = urljoin(BASE_URL, href)

        addr_el = card.select_one(".listtop-item-address, .listvip-item-address")
        location_raw = clean_ws(addr_el.get_text(" ", strip=True)) if addr_el else ""
        city, neighborhood = split_location(location_raw, region)

        full_text = clean_ws(card.get_text(" | ", strip=True))

        # Price
        price_el = card.select_one(".ads-params-price, .listtop-item-price, .listvip-item-price")
        price_text = clean_ws(price_el.get_text(" ", strip=True)) if price_el else full_text
        price_eur, currency_raw = parse_price_eur(price_text)

        # Description
        desc_el = card.select_one(".listtop-desc, .listvip-desc, .listtop-item-desc")
        description = clean_ws(desc_el.get_text(" ", strip=True)) if desc_el else ""

        # Published date
        pub_el = card.select_one(".listtop-publisher, .listvip-publisher")
        published_raw = clean_ws(pub_el.get_text(" ", strip=True)) if pub_el else ""

        # Image (explicitly pick listing photo, never agency avatar/logo)
        img_el = card.select_one("img.listtop-image-img, img.listvip-image-img")
        if not img_el:
            for cand in card.select("img"):
                cls = " ".join(cand.get("class") or [])
                src_cand = cand.get("data-src") or cand.get("src") or ""
                if "logo" in cls or "_avatar" in src_cand:
                    continue
                img_el = cand
                break
        img_src = (img_el.get("data-src") or img_el.get("src") or "") if img_el else ""
        if any(bad in img_src.lower() for bad in ("nopic", "no_photo", "no-photo", "default", "_avatar")):
            img_src = ""
        image_url = urljoin(BASE_URL + "/", img_src) if img_src and not img_src.startswith("data:") else ""

        m_cnt = re.search(r"\b(\d+)\s*(?:снимк|фото)", full_text, re.I)
        photos_count = int(m_cnt.group(1)) if m_cnt else (1 if image_url else 0)

        # Private vs agency heuristic
        is_private: bool | None = None
        agency = ""
        if re.search(r"частно лице", full_text, re.I):
            is_private = True
            agency = "Частно лице"
        else:
            agency_el = card.select_one(".listtop-firm, .listvip-firm, .firm-name")
            logo_el = card.select_one("img.listvip-logo, img.listtop-logo")
            if agency_el:
                agency = clean_ws(agency_el.get_text(" ", strip=True))
                is_private = False
            elif logo_el and (logo_el.get("alt") or logo_el.get("title")):
                agency = clean_ws(logo_el.get("alt") or logo_el.get("title"))
                is_private = False

        area_sqm = parse_area_sqm(full_text)
        yard_sqm = parse_yard_sqm(full_text)
        floor, total_floors = parse_floor_info(full_text)
        construction_type = parse_construction(full_text)
        year_built = parse_year_built(full_text)
        phone = parse_phone(full_text)
        property_type = normalize_property_type(f"{title} {full_text[:250]}")

        return RawListing(
            source=self.source_name,
            external_id=ext_id,
            url=url,
            region=region,
            transaction_type=transaction_type,
            title=title or f"{property_type} - {location_raw}",
            property_type=property_type,
            city=city,
            neighborhood=neighborhood,
            location_raw=location_raw,
            price_eur=price_eur,
            price_raw=price_text[:60] if price_el else "",
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
            photos_count=photos_count,
            published_raw=published_raw,
        )
