"""Pydantic data models for raw listings and deduplicated canonical properties."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RawListing(BaseModel):
    """Single scraped listing from one website / agency."""

    source: str = Field(..., description="Source portal or agency slug, e.g. 'alo.bg', 'imot.bg', 'imoti.net'")
    external_id: str = Field(..., description="Listing ID on the source website")
    url: str = Field(..., description="Direct link to the listing")
    region: Literal["shumen", "varna"] = Field(..., description="Target region")
    transaction_type: Literal["sale", "rent"] = Field(..., description="Sale or rent")

    title: str = ""
    property_type: str = "other"  # e.g. 1-стаен, 2-стаен, 3-стаен, многостаен, къща, парцел, офис, гараж
    municipality: str = ""
    city: str = ""
    neighborhood: str = ""
    location_raw: str = ""

    price_eur: Optional[float] = None
    price_raw: str = ""
    currency_raw: str = ""

    area_sqm: Optional[float] = None
    yard_sqm: Optional[float] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    construction_type: str = ""   # тухла, панел, ЕПК, etc.
    year_built: Optional[int] = None

    agency: str = ""
    is_private: Optional[bool] = None
    phone: str = ""
    description: str = ""
    image_url: str = ""
    photos_count: int = 0
    published_raw: str = ""
    scraped_at: str = Field(default_factory=utc_now_iso)


class OfferRef(BaseModel):
    """Reference to one external listing/agency offer merged into a CanonicalProperty."""

    source: str
    external_id: str
    url: str
    agency: str = ""
    is_private: Optional[bool] = None
    phone: str = ""
    title: str = ""
    price_eur: Optional[float] = None
    price_raw: str = ""
    area_sqm: Optional[float] = None
    yard_sqm: Optional[float] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    construction_type: str = ""
    year_built: Optional[int] = None
    description: str = ""
    image_url: str = ""
    photos_count: int = 0
    published_raw: str = ""
    scraped_at: str = ""


class CanonicalProperty(BaseModel):
    """Unified property combining duplicate listings across sites and multiple agencies."""

    property_id: str = Field(..., description="Stable canonical property ID")
    region: Literal["shumen", "varna"]
    transaction_type: Literal["sale", "rent"]
    property_type: str

    title: str
    municipality: str = ""
    city: str = ""
    neighborhood: str = ""
    location_raw: str = ""

    price_eur_min: Optional[float] = None
    price_eur_max: Optional[float] = None
    area_sqm: Optional[float] = None
    yard_sqm: Optional[float] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    construction_type: str = ""
    year_built: Optional[int] = None

    description: str = ""
    images: list[str] = Field(default_factory=list)

    # All linked listings across sites & agencies
    offers_count: int = 1
    sources: list[str] = Field(default_factory=list)
    agencies: list[str] = Field(default_factory=list)
    external_links: list[OfferRef] = Field(default_factory=list)

    # Transparency for how duplicates were merged
    is_merged: bool = False
    merge_reasons: list[str] = Field(default_factory=list)
    first_seen_at: str = Field(default_factory=utc_now_iso)
    last_updated_at: str = Field(default_factory=utc_now_iso)
