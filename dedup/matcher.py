"""Cross-site & multi-agency property deduplication and grouping engine.

Merges:
- Same property listed on multiple portals (e.g. alo.bg + imot.bg + imoti.net)
- Same property listed by multiple agencies (e.g. 5 agencies posting the same apartment)

Produces CanonicalProperty objects containing all external links and agency offers.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import re

from config import AREA_TOLERANCE_MIN_SQM, AREA_TOLERANCE_PCT, PRICE_TOLERANCE_PCT
from models import CanonicalProperty, OfferRef, RawListing
from scrapers.locations_bg import resolve_municipality, resolve_neighborhood

STOP_WORDS = {
    "продава", "под", "наем", "апартамент", "къща", "парцел", "имот", "имоти",
    "агенция", "предлага", "продажба", "град", "област", "шумен", "варна",
    "кв", "жк", "ул", "бул", "етаж", "от", "за", "на", "в", "с", "и", "по",
    "до", "при", "или", "като", "със", "без", "нов", "нова", "ново", "нови",
    "цена", "евро", "лв", "bgn", "eur", "квм", "тел", "оферта", "код",
}


def _norm_place(text: str) -> str:
    s = (text or "").lower().strip()
    s = re.sub(r"\b(?:гр|град|с|село|кв|ж\.?к|м-т|местност|обл|област)\.?\s*", "", s)
    s = re.sub(r"[^а-яa-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokenize(text: str) -> set[str]:
    s = (text or "").lower()
    tokens = re.findall(r"[а-яa-z0-9]{3,}", s)
    return {t for t in tokens if t not in STOP_WORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _property_type_compatible(t1: str, t2: str) -> bool:
    if t1 == t2:
        return True
    # Generic "апартамент" can match specific apartment room counts
    apt_types = {"1-стаен", "2-стаен", "3-стаен", "4-стаен", "многостаен", "апартамент"}
    if t1 in apt_types and t2 in apt_types and ("апартамент" in (t1, t2)):
        return True
    return False


def _compare_pair(a: RawListing, b: RawListing) -> tuple[bool, list[str]]:
    """Return (is_same_property, reasons) for two RawListing items."""
    if a.region != b.region or a.transaction_type != b.transaction_type:
        return False, []
    if not _property_type_compatible(a.property_type, b.property_type):
        return False, []

    # City check
    city_a, city_b = _norm_place(a.city), _norm_place(b.city)
    if city_a and city_b and city_a != city_b:
        return False, []

    # Neighborhood check
    nb_a, nb_b = _norm_place(a.neighborhood), _norm_place(b.neighborhood)
    same_neighborhood = False
    if nb_a and nb_b:
        if nb_a == nb_b or nb_a in nb_b or nb_b in nb_a:
            same_neighborhood = True
        else:
            return False, []

    # Price compatibility (required for all attribute merges)
    if a.price_eur is None or b.price_eur is None:
        return False, []
    min_price = max(min(a.price_eur, b.price_eur), 1.0)
    price_diff_pct = abs(a.price_eur - b.price_eur) / min_price
    if price_diff_pct > PRICE_TOLERANCE_PCT:
        return False, []

    # Floor compatibility (strict for apartments; houses often mix up 1 vs 2 stories / semi-basement)
    same_floor = False
    if a.floor is not None and b.floor is not None:
        if a.property_type != "къща" and a.floor != b.floor:
            return False, []
        if a.floor == b.floor:
            same_floor = True

    # Construction compatibility
    if a.construction_type and b.construction_type and a.construction_type != b.construction_type:
        return False, []

    tok_a = _tokenize(f"{a.title} {a.description}")
    tok_b = _tokenize(f"{b.title} {b.description}")
    shared_tokens = tok_a & tok_b
    sim = _jaccard(tok_a, tok_b)

    # House-specific rule: agencies agree on exact yard_sqm from the deed (скица),
    # even when they estimate built-up area (РЗП) differently (e.g. 160 vs 170 vs 200 sq.m)
    if (
        a.property_type == "къща"
        and b.property_type == "къща"
        and same_neighborhood
        and a.yard_sqm is not None
        and b.yard_sqm is not None
        and price_diff_pct <= 0.06
    ):
        yard_diff_pct = abs(a.yard_sqm - b.yard_sqm) / max(min(a.yard_sqm, b.yard_sqm), 1.0)
        area_ok = True
        if a.area_sqm is not None and b.area_sqm is not None:
            area_diff_pct = abs(a.area_sqm - b.area_sqm) / max(min(a.area_sqm, b.area_sqm), 1.0)
            area_ok = area_diff_pct <= 0.28
        if yard_diff_pct <= 0.03 and area_ok:
            return True, [
                "same_city",
                "same_neighborhood",
                f"same_yard_{int(round(a.yard_sqm))}sqm",
                f"price_diff_{price_diff_pct*100:.1f}%",
            ]

    # Fallback when one listing lacks area_sqm (e.g. bazar.bg / olx.bg search cards)
    if a.area_sqm is None or b.area_sqm is None:
        if not same_neighborhood or a.property_type == "other" or a.property_type != b.property_type:
            return False, []
        # Require exact price match (within 1 EUR) when area is missing to prevent chaining different properties
        if abs(a.price_eur - b.price_eur) >= 1.0:
            return False, []
        is_exact_non_round_price = (int(round(a.price_eur)) % 1000 != 0)
        # Containment similarity (short bazar title vs long alo/imot description)
        min_tok_len = min(len(tok_a), len(tok_b))
        containment = (len(shared_tokens) / min_tok_len) if min_tok_len > 0 else 0.0
        if (
            (a.phone and b.phone and a.phone == b.phone)
            or (len(shared_tokens) >= 2 and containment >= 0.45)
            or is_exact_non_round_price
        ):
            reasons = ["same_city", "same_neighborhood", "exact_price_match"]
            if len(shared_tokens) >= 2:
                reasons.append(f"title_overlap_{len(shared_tokens)}tok")
            if is_exact_non_round_price:
                reasons.append("unique_exact_price")
            return True, reasons
        return False, []

    area_diff = abs(a.area_sqm - b.area_sqm)
    max_area_diff = max(AREA_TOLERANCE_MIN_SQM, min(a.area_sqm, b.area_sqm) * AREA_TOLERANCE_PCT)
    if area_diff > max_area_diff:
        return False, []

    # Yard compatibility for houses/plots
    same_yard = False
    if a.yard_sqm is not None and b.yard_sqm is not None:
        yard_diff_pct = abs(a.yard_sqm - b.yard_sqm) / max(min(a.yard_sqm, b.yard_sqm), 1.0)
        if yard_diff_pct > 0.12:
            return False, []
        same_yard = True

    # Corroborating signals
    reasons = ["same_city", f"area_diff_{area_diff:.1f}sqm", f"price_diff_{price_diff_pct*100:.1f}%"]
    if same_neighborhood:
        reasons.append("same_neighborhood")

    corroborated = False

    if a.phone and b.phone and a.phone == b.phone:
        reasons.append("same_phone")
        corroborated = True

    if same_floor:
        reasons.append(f"same_floor_{a.floor}")
        corroborated = True

    if same_yard:
        reasons.append("same_yard")
        corroborated = True

    # Exact/near-exact area + tight price + matching neighborhood (classic multi-agency copy)
    if same_neighborhood and area_diff <= 1.0 and price_diff_pct <= 0.03:
        reasons.append("exact_area_and_price")
        corroborated = True

    if sim >= 0.32:
        reasons.append(f"text_similarity_{sim:.2f}")
        corroborated = True

    return corroborated, reasons


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[ry] = rx


def _has_real_photo(item: RawListing) -> bool:
    u = (item.image_url or "").lower()
    if not u:
        return False
    return not any(bad in u for bad in ("nopic", "no_photo", "no-photo", "default", "_avatar", "logo"))


def _photo_rank(item: RawListing) -> tuple[int, int, int]:
    """Higher tuple = better primary photo/listing."""
    has_img = 1 if _has_real_photo(item) else 0
    prefer_imot = 1 if (has_img and item.source == "imot.bg") else 0
    return (has_img, item.photos_count, prefer_imot)


def _clean_published(item: RawListing) -> str:
    raw = (item.published_raw or "").strip()
    if item.source == "imot.bg" and not raw:
        m_ts = re.match(r"^[0-9a-z]{2}(\d{10})", item.external_id, re.I)
        if m_ts:
            try:
                ts = int(m_ts.group(1))
                if 1262304000 <= ts <= 2000000000:
                    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y")
            except (ValueError, OSError):
                pass
    if item.source == "alo.bg" and raw:
        m = re.search(r"(от\s+днес|днес|вчера|преди\s+\d+\+?\s*(?:дни|ден|час[а]?|мин[а-я]*))", raw, re.I)
        if m:
            return m.group(1).strip()
    return raw


def _stable_property_id(items: list[RawListing]) -> str:
    keys = sorted(f"{it.source}:{it.external_id}" for it in items)
    digest = hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:12]
    return f"prop_{digest}"


def merge_listings(raw_listings: list[RawListing]) -> list[CanonicalProperty]:
    """Deduplicate exact listings and merge cross-site / multi-agency duplicates."""
    # 1. Deduplicate identical (source, external_id) keeping the latest
    unique_map: dict[tuple[str, str], RawListing] = {}
    for item in raw_listings:
        unique_map[(item.source, item.external_id)] = item
    items = list(unique_map.values())
    if not items:
        return []

    # 2. Bucket by (region, transaction_type) for fast pairwise checks
    uf = _UnionFind(len(items))
    group_reasons: dict[int, set[str]] = defaultdict(set)

    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, it in enumerate(items):
        buckets[(it.region, it.transaction_type)].append(idx)

    for indices in buckets.values():
        m = len(indices)
        for i in range(m):
            idx_a = indices[i]
            for j in range(i + 1, m):
                idx_b = indices[j]
                if uf.find(idx_a) == uf.find(idx_b):
                    continue
                matched, reasons = _compare_pair(items[idx_a], items[idx_b])
                if matched:
                    uf.union(idx_a, idx_b)
                    root = uf.find(idx_a)
                    group_reasons[root].update(reasons)

    # 3. Collect clusters
    clusters: dict[int, list[RawListing]] = defaultdict(list)
    cluster_reasons: dict[int, set[str]] = defaultdict(set)
    for idx, it in enumerate(items):
        root = uf.find(idx)
        clusters[root].append(it)
    for idx, rset in group_reasons.items():
        cluster_reasons[uf.find(idx)].update(rset)

    # 4. Build CanonicalProperty per cluster
    canonical: list[CanonicalProperty] = []
    for root, cluster in clusters.items():
        # Always prefer listings WITH real photos (and most photos) as primary representative
        rep = max(
            cluster,
            key=lambda x: (
                *_photo_rank(x),
                int(x.price_eur is not None)
                + int(x.area_sqm is not None)
                + int(bool(x.neighborhood))
                + int(x.floor is not None),
                len(x.description),
            ),
        )

        prices = [x.price_eur for x in cluster if x.price_eur is not None]
        sources = sorted({x.source for x in cluster})
        agencies = sorted({x.agency for x in cluster if x.agency})

        # Order images by photo rank so the best real property photo is always first
        by_photo = sorted(cluster, key=_photo_rank, reverse=True)
        images = list(dict.fromkeys(x.image_url for x in by_photo if _has_real_photo(x)))

        # Sort external links: best photo rank (has photo, most photos, imot.bg tiebreak) first, then cheapest price
        sorted_cluster = sorted(
            cluster,
            key=lambda x: (
                -_photo_rank(x)[0],
                -_photo_rank(x)[1],
                -_photo_rank(x)[2],
                x.price_eur is None,
                x.price_eur or 0.0,
                x.source,
            ),
        )
        offer_refs = [
            OfferRef(
                source=x.source,
                external_id=x.external_id,
                url=x.url,
                agency=x.agency,
                is_private=x.is_private,
                phone=x.phone,
                title=x.title,
                price_eur=x.price_eur,
                price_raw=x.price_raw,
                area_sqm=x.area_sqm,
                yard_sqm=x.yard_sqm,
                floor=x.floor,
                total_floors=x.total_floors,
                construction_type=x.construction_type,
                year_built=x.year_built,
                description=x.description,
                image_url=x.image_url,
                photos_count=x.photos_count,
                published_raw=_clean_published(x),
                scraped_at=x.scraped_at,
            )
            for x in sorted_cluster
        ]

        # Best available metadata across the cluster
        best_floor = next((x.floor for x in cluster if x.floor is not None), None)
        best_total_floors = next((x.total_floors for x in cluster if x.total_floors is not None), None)
        best_construction = next((x.construction_type for x in cluster if x.construction_type), "")
        best_year = next((x.year_built for x in cluster if x.year_built is not None), None)
        best_yard = next((x.yard_sqm for x in cluster if x.yard_sqm is not None), None)
        best_prop_type = next(
            (x.property_type for x in cluster if x.property_type not in ("other", "апартамент")),
            rep.property_type,
        )

        raw_nb = rep.neighborhood or next((x.neighborhood for x in cluster if x.neighborhood), "")
        clean_city = re.sub(r"^(?:гр\.?|град)\s+", "", rep.city or "", flags=re.I).strip()
        best_neighborhood = resolve_neighborhood(
            clean_city, raw_nb, rep.location_raw, rep.title, rep.description
        )
        municipality = rep.municipality or resolve_municipality(
            clean_city, best_neighborhood, rep.location_raw, rep.region
        )

        canonical.append(
            CanonicalProperty(
                property_id=_stable_property_id(cluster),
                region=rep.region,
                transaction_type=rep.transaction_type,
                property_type=best_prop_type,
                title=rep.title,
                municipality=municipality,
                city=clean_city,
                neighborhood=best_neighborhood,
                location_raw=rep.location_raw,
                price_eur_min=min(prices) if prices else None,
                price_eur_max=max(prices) if prices else None,
                area_sqm=rep.area_sqm,
                yard_sqm=best_yard,
                floor=best_floor,
                total_floors=best_total_floors,
                construction_type=best_construction,
                year_built=best_year,
                description=rep.description,
                images=images,
                offers_count=len(offer_refs),
                sources=sources,
                agencies=agencies,
                external_links=offer_refs,
                is_merged=len(offer_refs) > 1,
                merge_reasons=sorted(cluster_reasons.get(root, set())) if len(offer_refs) > 1 else [],
            )
        )

    # Sort merged properties first, then by region & price
    canonical.sort(
        key=lambda p: (
            not p.is_merged,
            -p.offers_count,
            p.region,
            p.price_eur_min is None,
            p.price_eur_min or 0.0,
        )
    )
    return canonical
