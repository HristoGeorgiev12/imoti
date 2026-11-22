"""CLI entrypoint for the local Bulgarian Real Estate Aggregator (Shumen & Varna)."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from config import (
    DEFAULT_MAX_PAGES,
    DEFAULT_REGIONS,
    DEFAULT_TRANSACTIONS,
    OUTPUT_JSON_PATH,
    RAW_JSON_PATH,
)
from dedup import merge_listings
from models import RawListing
from scrapers import ALL_SCRAPERS, BlockedBySiteError
from storage import load_raw_listings, save_canonical_properties, save_raw_listings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("imoti-aggregator")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Локален агрегатор за имоти (област Шумен и област Варна) с обединяване на дублирани обяви в JSON."
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        choices=["shumen", "varna"],
        default=DEFAULT_REGIONS,
        help="Области за скрейпване (по подразбиране: shumen varna)",
    )
    parser.add_argument(
        "--transactions",
        nargs="+",
        choices=["sale", "rent"],
        default=DEFAULT_TRANSACTIONS,
        help="Тип сделки (по подразбиране: sale rent)",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=list(ALL_SCRAPERS.keys()),
        default=list(ALL_SCRAPERS.keys()),
        help="Източници за скрейпване",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Брой страници на източник/област/сделка (по подразбиране: 2)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Добави към вече събраните raw обяви вместо да ги презапишеш",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_JSON_PATH,
        help=f"Път до крайния JSON файл (по подразбиране: {OUTPUT_JSON_PATH})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    all_raw: list[RawListing] = load_raw_listings(RAW_JSON_PATH) if args.append else []
    if args.append and all_raw:
        logger.info("Loaded %d existing raw listings from %s", len(all_raw), RAW_JSON_PATH)

    for source_name in args.sources:
        scraper_cls = ALL_SCRAPERS[source_name]
        with scraper_cls() as scraper:
            for region in args.regions:
                for tx in args.transactions:
                    try:
                        scraped = scraper.scrape(
                            region=region,
                            transaction_type=tx,
                            max_pages=args.pages,
                        )
                        all_raw.extend(scraped)
                    except BlockedBySiteError as exc:
                        logger.warning("%s", exc)
                        break

    save_raw_listings(RAW_JSON_PATH, all_raw)
    canonical = merge_listings(all_raw)
    save_canonical_properties(args.output, canonical, total_raw=len(all_raw))

    merged_count = sum(1 for p in canonical if p.is_merged)
    cross_site = sum(1 for p in canonical if len(p.sources) > 1)
    multi_agency = sum(1 for p in canonical if len(p.agencies) > 1)

    logger.info("========================================")
    logger.info("Готово! Записано в: %s", args.output)
    logger.info("Сурови обяви:       %d", len(all_raw))
    logger.info("Уникални имоти:     %d", len(canonical))
    logger.info("Сляти дубликати:    %d (между сайтове: %d, между агенции: %d)", merged_count, cross_site, multi_agency)
    logger.info("========================================")


if __name__ == "__main__":
    main()
