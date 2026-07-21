from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GAMMA_BASE = "https://gamma-api.polymarket.com"


class PublicApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicMarket:
    event_title: str
    event_slug: str
    question: str
    slug: str
    end_date: str
    liquidity: float
    volume: float
    best_bid: float | None
    best_ask: float | None
    fees_enabled: bool


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_json(url: str, timeout: float = 20.0) -> Any:
    request = Request(url, headers={"User-Agent": "paper-lab/0.1 (read-only research)"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return json.load(response)
    except HTTPError as exc:
        raise PublicApiError(f"Polymarket API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, ssl.SSLError) as exc:
        raise PublicApiError(
            "Could not read the public Polymarket API. Check network and TLS certificates; "
            "do not disable certificate verification."
        ) from exc


def fetch_finance_markets(limit: int = 50, title_filter: str | None = None) -> list[PublicMarket]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    params = urlencode(
        {
            "limit": limit,
            "closed": "false",
            "tag_slug": "finance",
            "order": "volume_24hr",
            "ascending": "false",
        }
    )
    payload = _get_json(f"{GAMMA_BASE}/events/keyset?{params}")
    pattern = re.compile(title_filter, re.IGNORECASE) if title_filter else None
    results: list[PublicMarket] = []
    for event in payload.get("events", []):
        event_title = str(event.get("title") or "")
        event_slug = str(event.get("slug") or "")
        for market in event.get("markets") or []:
            question = str(market.get("question") or event_title)
            if pattern and not pattern.search(f"{event_title} {question}"):
                continue
            results.append(
                PublicMarket(
                    event_title=event_title,
                    event_slug=event_slug,
                    question=question,
                    slug=str(market.get("slug") or ""),
                    end_date=str(market.get("endDate") or event.get("endDate") or ""),
                    liquidity=_number(market.get("liquidityNum", market.get("liquidity"))),
                    volume=_number(market.get("volumeNum", market.get("volume"))),
                    best_bid=(
                        _number(market.get("bestBid")) if market.get("bestBid") is not None else None
                    ),
                    best_ask=(
                        _number(market.get("bestAsk")) if market.get("bestAsk") is not None else None
                    ),
                    fees_enabled=bool(
                        market.get("feesEnabled", market.get("fees_enabled", False))
                    ),
                )
            )
    return results
