"""Polymarket 資料存取。

重點：報價一律取自 CLOB order book。
Gamma API 的 bestBid/bestAsk 有明顯延遲——2026-07-21 實測，Gamma 顯示
0.76/0.79（3¢），同一時刻 CLOB book 實際為 0.76/0.77（1¢）。
用 Gamma 報價做研究會系統性高估價差、高估獲利空間。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

import config

_session = requests.Session()
_session.headers.update({"User-Agent": "paperlab/0.1"})


def _get(url: str, params: dict | None = None, timeout: int = 15):
    r = _session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def find_today_market(series_slug: str = config.SERIES_SLUG) -> dict | None:
    """找出該系列中今天正在交易的那一場。

    以 endDateIso == 今天(UTC) 且 closed == False 為準。
    """
    today = datetime.now(timezone.utc).date().isoformat()
    events = _get(
        f"{config.GAMMA_BASE}/events",
        {"series_slug": series_slug, "closed": "false", "limit": 30},
    )
    for ev in events:
        for m in ev.get("markets", []):
            if m.get("endDateIso") == today and not m.get("closed"):
                return _ensure_rewards(m)
    # 退路：直接查 markets
    markets = _get(
        f"{config.GAMMA_BASE}/markets",
        {"closed": "false", "limit": 100, "series_slug": series_slug},
    )
    for m in markets:
        if m.get("endDateIso") == today and not m.get("closed"):
            return _ensure_rewards(m)
    return None


def _ensure_rewards(market: dict) -> dict:
    """補上 clobRewards。

    /events 端點回傳的巢狀 market 物件不含 clobRewards（實測 2026-07-21，
    導致 rewards_daily 記成 null）。改用 slug 直接查 /markets 補齊——
    掛單獎勵金額是做市側分析的核心欄位，不能漏。
    """
    if market.get("clobRewards"):
        return market
    slug = market.get("slug")
    if not slug:
        return market
    try:
        full = _get(f"{config.GAMMA_BASE}/markets", {"slug": slug})
        if full and isinstance(full, list):
            merged = dict(market)
            for key in ("clobRewards", "rewardsMinSize", "rewardsMaxSpread",
                        "clobTokenIds", "outcomes", "feeSchedule"):
                if full[0].get(key) is not None:
                    merged[key] = full[0][key]
            return merged
    except Exception:
        pass  # 補不到就照原樣回傳，errors 欄位不會被污染
    return market


def _parse_json_field(raw, default):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def up_token_id(market: dict) -> str | None:
    """取「Up」那一邊的 CLOB token id。

    outcomes 與 clobTokenIds 同序，所以用 outcomes 定位而非假設索引 0。
    """
    outcomes = _parse_json_field(market.get("outcomes"), [])
    tokens = _parse_json_field(market.get("clobTokenIds"), [])
    if not tokens:
        return None
    for i, o in enumerate(outcomes):
        if str(o).strip().lower() in ("up", "yes") and i < len(tokens):
            return tokens[i]
    return tokens[0]


def fetch_book(token_id: str) -> dict:
    """取訂單簿。回傳已排序的 bids(高→低) 與 asks(低→高)。

    ⚠ last_trade_price 不可用於分析。
    實測 2026-07-21，同一欄位的計價基準不一致：
      13:47Z 查 UP  (盤口 0.76/0.77)  → 回傳 0.230，是 DOWN 側的價格
      17:35Z 查 DOWN(盤口 0.001/0.009) → 回傳 0.001，是自己的價格
    同時 Gamma 對同一筆記為 lastTradePrice 0.8（UP 視角），三者互不一致。
    成交價似乎記在成交方向的那一側，API 未正規化。
    此處照原樣保留作為原始觀測，但任何模型計算都只能用 bid/ask/mid。
    """
    raw = _get(f"{config.CLOB_BASE}/book", {"token_id": token_id})
    bids = [
        {"price": float(x["price"]), "size": float(x["size"])}
        for x in raw.get("bids", [])
    ]
    asks = [
        {"price": float(x["price"]), "size": float(x["size"])}
        for x in raw.get("asks", [])
    ]
    bids.sort(key=lambda x: -x["price"])
    asks.sort(key=lambda x: x["price"])
    return {
        "bids": bids,
        "asks": asks,
        "timestamp": int(raw.get("timestamp") or 0),
        "last_trade_price": float(raw.get("last_trade_price") or 0) or None,
        "tick_size": float(raw.get("tick_size") or config.TICK_SIZE),
    }


def build_snapshot(ts: int, market: dict, token_id: str, book: dict) -> tuple[dict, list]:
    bids, asks = book["bids"], book["asks"]
    bb = bids[0]["price"] if bids else None
    ba = asks[0]["price"] if asks else None
    mid = (bb + ba) / 2 if (bb is not None and ba is not None) else None

    rewards = (market.get("clobRewards") or [{}])[0]
    slug = market.get("slug")

    snap = {
        "ts": ts,
        "market_slug": slug,
        "condition_id": market.get("conditionId"),
        "token_id_up": token_id,
        "book_ts": book["timestamp"],
        "best_bid": bb,
        "best_ask": ba,
        "bid_size": bids[0]["size"] if bids else None,
        "ask_size": asks[0]["size"] if asks else None,
        "mid": mid,
        "spread": (ba - bb) if (bb is not None and ba is not None) else None,
        "last_trade": book["last_trade_price"],
        "gamma_bid": market.get("bestBid"),
        "gamma_ask": market.get("bestAsk"),
        "liquidity": market.get("liquidityNum"),
        "volume_24h": market.get("volume24hr"),
        "rewards_daily": rewards.get("rewardsDailyRate"),
        "rewards_minsz": market.get("rewardsMinSize"),
        "rewards_maxsp": market.get("rewardsMaxSpread"),
    }

    levels = [
        {"ts": ts, "market_slug": slug, "side": side, "price": lv["price"], "size": lv["size"]}
        for side, book_side in (("bid", bids), ("ask", asks))
        for lv in book_side
    ]
    return snap, levels
"""Polymarket 資料存取。

重點：報價一律取自 CLOB order book。
Gamma API 的 bestBid/bestAsk 有明顯延遲——2026-07-21 實測，Gamma 顯示
0.76/0.79（3¢），同一時刻 CLOB book 實際為 0.76/0.77（1¢）。
用 Gamma 報價做研究會系統性高估價差、高估獲利空間。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

import config

_session = requests.Session()
_session.headers.update({"User-Agent": "paperlab/0.1"})


def _get(url: str, params: dict | None = None, timeout: int = 15):
    r = _session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def find_today_market(series_slug: str = config.SERIES_SLUG) -> dict | None:
    """找出該系列中今天正在交易的那一場。

    以 endDateIso == 今天(UTC) 且 closed == False 為準。
    """
    today = datetime.now(timezone.utc).date().isoformat()
    events = _get(
        f"{config.GAMMA_BASE}/events",
        {"series_slug": series_slug, "closed": "false", "limit": 30},
    )
    for ev in events:
        for m in ev.get("markets", []):
            if m.get("endDateIso") == today and not m.get("closed"):
                return _ensure_rewards(m)
    # 退路：直接查 markets
    markets = _get(
        f"{config.GAMMA_BASE}/markets",
        {"closed": "false", "limit": 100, "series_slug": series_slug},
    )
    for m in markets:
        if m.get("endDateIso") == today and not m.get("closed"):
            return _ensure_rewards(m)
    return None


def _ensure_rewards(market: dict) -> dict:
    """補上 clobRewards。

    /events 端點回傳的巢狀 market 物件不含 clobRewards（實測 2026-07-21，
    導致 rewards_daily 記成 null）。改用 slug 直接查 /markets 補齊——
    掛單獎勵金額是做市側分析的核心欄位，不能漏。
    """
    if market.get("clobRewards"):
        return market
    slug = market.get("slug")
    if not slug:
        return market
    try:
        full = _get(f"{config.GAMMA_BASE}/markets", {"slug": slug})
        if full and isinstance(full, list):
            merged = dict(market)
            for key in ("clobRewards", "rewardsMinSize", "rewardsMaxSpread",
                        "clobTokenIds", "outcomes", "feeSchedule"):
                if full[0].get(key) is not None:
                    merged[key] = full[0][key]
            return merged
    except Exception:
        pass  # 補不到就照原樣回傳，errors 欄位不會被污染
    return market


def _parse_json_field(raw, default):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def up_token_id(market: dict) -> str | None:
    """取「Up」那一邊的 CLOB token id。

    outcomes 與 clobTokenIds 同序，所以用 outcomes 定位而非假設索引 0。
    """
    outcomes = _parse_json_field(market.get("outcomes"), [])
    tokens = _parse_json_field(market.get("clobTokenIds"), [])
    if not tokens:
        return None
    for i, o in enumerate(outcomes):
        if str(o).strip().lower() in ("up", "yes") and i < len(tokens):
            return tokens[i]
    return tokens[0]


def fetch_book(token_id: str) -> dict:
    """取訂單簿。回傳已排序的 bids(高→低) 與 asks(低→高)。"""
    raw = _get(f"{config.CLOB_BASE}/book", {"token_id": token_id})
    bids = [
        {"price": float(x["price"]), "size": float(x["size"])}
        for x in raw.get("bids", [])
    ]
    asks = [
        {"price": float(x["price"]), "size": float(x["size"])}
        for x in raw.get("asks", [])
    ]
    bids.sort(key=lambda x: -x["price"])
    asks.sort(key=lambda x: x["price"])
    return {
        "bids": bids,
        "asks": asks,
        "timestamp": int(raw.get("timestamp") or 0),
        "last_trade_price": float(raw.get("last_trade_price") or 0) or None,
        "tick_size": float(raw.get("tick_size") or config.TICK_SIZE),
    }


def build_snapshot(ts: int, market: dict, token_id: str, book: dict) -> tuple[dict, list]:
    bids, asks = book["bids"], book["asks"]
    bb = bids[0]["price"] if bids else None
    ba = asks[0]["price"] if asks else None
    mid = (bb + ba) / 2 if (bb is not None and ba is not None) else None

    rewards = (market.get("clobRewards") or [{}])[0]
    slug = market.get("slug")

    snap = {
        "ts": ts,
        "market_slug": slug,
        "condition_id": market.get("conditionId"),
        "token_id_up": token_id,
        "book_ts": book["timestamp"],
        "best_bid": bb,
        "best_ask": ba,
        "bid_size": bids[0]["size"] if bids else None,
        "ask_size": asks[0]["size"] if asks else None,
        "mid": mid,
        "spread": (ba - bb) if (bb is not None and ba is not None) else None,
        "last_trade": book["last_trade_price"],
        "gamma_bid": market.get("bestBid"),
        "gamma_ask": market.get("bestAsk"),
        "liquidity": market.get("liquidityNum"),
        "volume_24h": market.get("volume24hr"),
        "rewards_daily": rewards.get("rewardsDailyRate"),
        "rewards_minsz": market.get("rewardsMinSize"),
        "rewards_maxsp": market.get("rewardsMaxSpread"),
    }

    levels = [
        {"ts": ts, "market_slug": slug, "side": side, "price": lv["price"], "size": lv["size"]}
        for side, book_side in (("bid", bids), ("ask", asks))
        for lv in book_side
    ]
    return snap, levels
