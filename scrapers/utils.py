"""Shared Bulgarian real-estate text normalization & parsing utilities."""
from __future__ import annotations

import re
from typing import Optional

from config import BGN_PER_EUR


PROPERTY_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"едностаен|1[-\s]?стаен|бокс|гарсониера|студио", "1-стаен"),
    (r"двустаен|2[-\s]?стаен", "2-стаен"),
    (r"тристаен|3[-\s]?стаен", "3-стаен"),
    (r"четиристаен|4[-\s]?стаен", "4-стаен"),
    (r"многостаен|мезонет|ателие|таван|етаж от къща", "многостаен"),
    (r"къща|вила|къщи", "къща"),
    (r"парцел|земя|упи|нива|земеделск", "парцел"),
    (r"гараж|паркомясто", "гараж"),
    (r"офис|магазин|заведение|склад|търговск|промишлен|хотел", "бизнес-имот"),
    (r"апартамент|стая", "апартамент"),
]

CONSTRUCTION_PATTERNS: list[tuple[str, str]] = [
    (r"тухла", "тухла"),
    (r"панел", "панел"),
    (r"епк", "ЕПК"),
    (r"пк\b", "ПК"),
    (r"гредоред", "гредоред"),
    (r"сглобяем", "сглобяема"),
]


def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_property_type(text: str) -> str:
    low = (text or "").lower()
    for pattern, label in PROPERTY_TYPE_PATTERNS:
        if re.search(pattern, low):
            return label
    return "other"


def parse_price_eur(text: str) -> tuple[Optional[float], str]:
    """Extract price and convert to EUR. Returns (price_eur, currency_raw)."""
    if not text:
        return None, ""
    cleaned = clean_ws(text)
    # Prefer EUR price if both EUR and BGN are shown (e.g. "159 000 € / 310 977 BGN")
    eur_match = re.search(r"(\d[\d\s\.,]*)\s*(?:€|eur|евро)", cleaned, re.I)
    if eur_match:
        val = _parse_number(eur_match.group(1))
        if val is not None and val > 0:
            return round(val, 2), "EUR"

    bgn_match = re.search(r"(\d[\d\s\.,]*)\s*(?:лв\.?|bgn)", cleaned, re.I)
    if bgn_match:
        val = _parse_number(bgn_match.group(1))
        if val is not None and val > 0:
            return round(val / BGN_PER_EUR, 2), "BGN"

    return None, ""


def _parse_number(num_str: str) -> Optional[float]:
    s = num_str.replace("\xa0", "").replace(" ", "").strip()
    if not s:
        return None
    # Handle European thousands separators vs decimal comma
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts[-1]) == 3 and len(parts[0]) <= 3:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_area_sqm(text: str) -> Optional[float]:
    if not text:
        return None
    # Avoid matching yard ("двор 500 кв.м") when extracting main built area
    without_yard = re.sub(r"двор\s*\d[\d\s\.,]*\s*(?:кв\.?\s*м|м2|m2)", "", text, flags=re.I)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м\s*2|m\s*2|м²)", without_yard, re.I)
    if m:
        return _parse_number(m.group(1))
    return None


def parse_yard_sqm(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"двор\s*[:\-]?\s*(\d[\d\s\.,]*)\s*(?:кв\.?\s*м|м\s*2|m\s*2|м²)", text, re.I)
    if m:
        return _parse_number(m.group(1))
    return None


def parse_floor_info(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (floor, total_floors) from Bulgarian listing strings."""
    if not text:
        return None, None
    low = text.lower()

    # e.g. "Етаж: 3 от 5", "3-ти ет. от 5", "ет. 4/8"
    m = re.search(r"(?:етаж|ет\.?)\s*[:\-]?\s*(\d{1,2})\s*(?:-?[твг][иа])?\s*(?:от|/)\s*(\d{1,2})", low)
    if m:
        return int(m.group(1)), int(m.group(2))

    # e.g. "3-ти от 5", "3 етаж"
    m2 = re.search(r"(\d{1,2})\s*(?:-?[твг][иа])?\s*(?:етаж|ет\.?)\s*(?:от\s*(\d{1,2}))?", low)
    if m2:
        fl = int(m2.group(1))
        tot = int(m2.group(2)) if m2.group(2) else None
        return fl, tot

    if "партер" in low:
        return 0, None

    return None, None


def parse_construction(text: str) -> str:
    low = (text or "").lower()
    for pat, label in CONSTRUCTION_PATTERNS:
        if re.search(pat, low):
            return label
    return ""


def parse_year_built(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\b(19\d{2}|20[0-3]\d)\s*г\.?", text)
    if m:
        return int(m.group(1))
    return None


def parse_phone(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(?:\+359|0)\s*8[7-9]\d[\s\-]?\d{3}[\s\-]?\d{3}", text)
    if m:
        return re.sub(r"[\s\-]", "", m.group(0))
    return ""


def split_location(location_raw: str, region: str) -> tuple[str, str]:
    """Split Bulgarian location strings into (city, neighborhood)."""
    raw = clean_ws(location_raw)
    if not raw:
        return ("Шумен" if region == "shumen" else "Варна"), ""

    # Remove "област Шумен" / "област Варна" suffix noise
    cleaned = re.sub(r",?\s*област\s+(?:Шумен|Варна)", "", raw, flags=re.I).strip(" ,")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    if len(parts) == 1:
        return parts[0], ""

    # In alo.bg format is often "Куршун чешма, Шумен" (neighborhood, city)
    # In imot.bg / imoti.net format is often "гр. Варна, Левски" or "Шумен, Широк център" (city, neighborhood)
    first_low = parts[0].lower()
    last_low = parts[-1].lower()
    region_city = "шумен" if region == "shumen" else "варна"

    if last_low in (region_city, f"гр. {region_city}", f"град {region_city}"):
        city = re.sub(r"^(?:гр\.|град)\s*", "", parts[-1], flags=re.I).strip()
        neighborhood = ", ".join(parts[:-1])
        return city, neighborhood

    if first_low.startswith(("гр.", "град ", "с.", "село ", region_city)):
        city = re.sub(r"^(?:гр\.|град)\s*", "", parts[0], flags=re.I).strip()
        neighborhood = ", ".join(parts[1:])
        return city, neighborhood

    return parts[0], ", ".join(parts[1:])
