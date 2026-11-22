"""Local JSON file storage (no database required)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from models import CanonicalProperty, RawListing
from scrapers.locations_bg import CITY_NEIGHBORHOODS


def _atomic_write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def load_raw_listings(path: Path) -> list[RawListing]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    raw_items = data.get("listings", data) if isinstance(data, dict) else data
    return [RawListing.model_validate(item) for item in raw_items]


def save_raw_listings(path: Path, listings: list[RawListing]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_raw_listings": len(listings),
        "listings": [item.model_dump() for item in listings],
    }
    _atomic_write_json(path, payload)


def save_canonical_properties(
    path: Path,
    properties: list[CanonicalProperty],
    total_raw: int,
) -> None:
    merged_groups = [p for p in properties if p.is_merged]
    cross_site_merged = [p for p in merged_groups if len(p.sources) > 1]
    multi_agency_merged = [p for p in merged_groups if len(p.agencies) > 1]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_raw_listings": total_raw,
            "unique_properties": len(properties),
            "merged_properties_count": len(merged_groups),
            "cross_site_merged_count": len(cross_site_merged),
            "multi_agency_merged_count": len(multi_agency_merged),
            "by_region": {
                "shumen": sum(1 for p in properties if p.region == "shumen"),
                "varna": sum(1 for p in properties if p.region == "varna"),
            },
        },
        "reference_neighborhoods": CITY_NEIGHBORHOODS,
        "properties": [p.model_dump() for p in properties],
    }
    _atomic_write_json(path, payload)
