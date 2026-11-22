"""Starter template for adding a custom real estate agency website or XML feed.

How to add a new agency:
1. Copy this file to `scrapers/agency_<name>.py`.
2. Implement `scrape()` returning `list[RawListing]`.
3. Register the scraper in `scrapers/__init__.py` (`ALL_SCRAPERS["agency-slug"] = ...`).
"""
from __future__ import annotations

from typing import Literal

from bs4 import BeautifulSoup

from models import RawListing
from scrapers.base import BaseScraper
from scrapers.utils import (
    clean_ws,
    normalize_property_type,
    parse_area_sqm,
    parse_floor_info,
    parse_price_eur,
    split_location,
)


class ExampleAgencyScraper(BaseScraper):
    source_name = "example-agency.bg"
    encoding = "utf-8"

    def scrape(
        self,
        region: Literal["shumen", "varna"],
        transaction_type: Literal["sale", "rent"] = "sale",
        max_pages: int = 1,
    ) -> list[RawListing]:
        # Replace with the agency's real search URL or XML feed URL
        url = f"https://example-agency.bg/imoti/{transaction_type}/{region}"
        html = self.fetch_html(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        listings: list[RawListing] = []

        for card in soup.select(".property-card"):
            ext_id = card.get("data-id", "")
            title = clean_ws(card.select_one("h2").get_text()) if card.select_one("h2") else ""
            href = card.select_one("a")["href"] if card.select_one("a") else url
            loc = clean_ws(card.select_one(".location").get_text()) if card.select_one(".location") else ""
            price_raw = clean_ws(card.select_one(".price").get_text()) if card.select_one(".price") else ""
            price_eur, curr = parse_price_eur(price_raw)
            city, neighborhood = split_location(loc, region)
            text = clean_ws(card.get_text(" ", strip=True))
            floor, total_floors = parse_floor_info(text)

            listings.append(
                RawListing(
                    source=self.source_name,
                    external_id=ext_id or href,
                    url=href,
                    region=region,
                    transaction_type=transaction_type,
                    title=title,
                    property_type=normalize_property_type(title),
                    city=city,
                    neighborhood=neighborhood,
                    location_raw=loc,
                    price_eur=price_eur,
                    price_raw=price_raw,
                    currency_raw=curr,
                    area_sqm=parse_area_sqm(text),
                    floor=floor,
                    total_floors=total_floors,
                    agency="Example Agency",
                    is_private=False,
                )
            )
        return listings
