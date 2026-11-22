from .agency_imotisilvi import ImotiSilviScraper
from .agency_imotitomov import ImotiTomovScraper
from .alo_bg import AloBgScraper
from .base import BaseScraper, BlockedBySiteError
from .bazar_bg import BazarBgScraper
from .imot_bg import ImotBgScraper
from .imoti_net import ImotiNetScraper
from .olx_bg import OlxBgScraper

ALL_SCRAPERS = {
    "alo.bg": AloBgScraper,
    "imot.bg": ImotBgScraper,
    "olx.bg": OlxBgScraper,
    "bazar.bg": BazarBgScraper,
    "imoti.net": ImotiNetScraper,
    "imotisilvi.bg": ImotiSilviScraper,
    "imotitomov.com": ImotiTomovScraper,
}

__all__ = [
    "BaseScraper",
    "BlockedBySiteError",
    "AloBgScraper",
    "BazarBgScraper",
    "ImotBgScraper",
    "ImotiNetScraper",
    "OlxBgScraper",
    "ImotiSilviScraper",
    "ImotiTomovScraper",
    "ALL_SCRAPERS",
]
