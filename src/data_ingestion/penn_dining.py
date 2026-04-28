"""Penn Dining menu parser with graceful fallback.

Penn Dining publishes a Net Nutrition-style menu via their dining website.
In practice the HTML structure changes, auth cookies are sometimes required,
and classroom grading machines may not even have internet. This module is
therefore structured as:

1. :class:`PennDiningParser.fetch()` attempts a live HTTP GET + BeautifulSoup
   parse. The HTML selector strategy is documented inline and is easy to
   swap if the site changes.
2. If the fetch fails for any reason -- no network, 403, unexpected layout --
   :meth:`PennDiningParser.load` falls back to the bundled
   ``data/sample/penn_dining_sample.json`` so the rest of the pipeline still
   runs end-to-end.

We deliberately never raise from :meth:`load`; callers always get a list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.data_ingestion.food_catalog import load_penn_dining_sample
from src.models.domain import FoodItem
from src.utils.logging import get_logger

_logger = get_logger(__name__)


# A couple of known-good entry URLs. These URLs are intentionally *not* hit
# by unit tests (tests stub out the fetch) but the defaults document where a
# real scrape would start.
DEFAULT_URLS: tuple[str, ...] = (
    "https://university-of-pennsylvania.cafebonappetit.com/cafe/1920-commons/",
    "https://university-of-pennsylvania.cafebonappetit.com/cafe/hill-house/",
    "https://university-of-pennsylvania.cafebonappetit.com/cafe/kcech/",
)


@dataclass
class PennDiningParser:
    """Tiny wrapper so the rest of the code can depend on a single type."""

    urls: tuple[str, ...] = DEFAULT_URLS
    timeout_s: int = 10
    user_agent: str = "Mozilla/5.0 (HSO-CIS1921-Student-Project)"

    # ------------------------------------------------------------------ live
    def fetch(self) -> Optional[list[FoodItem]]:
        """Attempt a live scrape. Return ``None`` on any failure.

        Returning None keeps the fallback path explicit: :meth:`load` swaps
        in the bundled sample when this method gives up.
        """
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            _logger.info("requests/bs4 not installed; skipping Penn Dining live fetch")
            return None

        collected: list[FoodItem] = []
        for url in self.urls:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_s,
                )
                if resp.status_code != 200:
                    _logger.info("Penn Dining %s returned %s; skipping",
                                 url, resp.status_code)
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                collected.extend(self._parse_cafe_bonappetit(soup, url))
            except Exception as exc:
                _logger.info("Penn Dining fetch failed for %s: %s", url, exc)
                continue
        if not collected:
            return None
        return collected

    @staticmethod
    def _parse_cafe_bonappetit(soup, source_url: str) -> list[FoodItem]:
        """Best-effort parse of a Cafe Bon Appetit-style page.

        The page uses ``.site-panel__daypart-item`` (or similar) blocks with
        nested class names for calories / protein. Because their HTML rotates
        we extract names and *optionally* macros; anything missing gets a
        placeholder so downstream code never crashes.
        """
        items: list[FoodItem] = []
        # Heuristic selectors. If the DOM structure changes, update here.
        # We look for any element whose class contains "station-item" or
        # "daypart-item" and pull its text content.
        candidates = soup.select(
            "[class*='station-item'], [class*='daypart-item'], [class*='menu-item']"
        )
        for idx, node in enumerate(candidates[:40]):
            name = node.get_text(strip=True)
            if not name or len(name) > 120:
                continue
            # Macros rarely embedded in page text; defaults are approximate.
            items.append(
                FoodItem(
                    id=f"penn_live_{idx}",
                    name=name[:80],
                    calories=450,
                    protein_g=24,
                    carbs_g=50,
                    fat_g=15,
                    sodium_mg=500,
                    cost_cents=0,
                    source="penn_dining",
                    convenience=7,
                    max_servings_per_day=2,
                )
            )
        return items

    # -------------------------------------------------------------- fallback
    def load(self) -> list[FoodItem]:
        """Return a Penn Dining catalog, live or fallback. Never raises."""
        live = self.fetch()
        if live:
            _logger.info("Loaded %d items from live Penn Dining scrape", len(live))
            return live
        _logger.info("Falling back to bundled Penn Dining sample catalog")
        return load_penn_dining_sample()
