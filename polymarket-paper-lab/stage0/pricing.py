"""從期權鏈導出「今日收盤 > 昨收」的機率。

核心觀念
--------
Polymarket 的 SPY 每日漲跌盤結算條件是：今日收盤價 > 昨日收盤價。
昨收 K 是**已知的固定數字**，而市場只在正常交易時段（13:30–20:00 UTC）交易。
因此隔夜跳空在開盤時就已經實現完畢——不存在「日盤/夜盤波動率如何混合」的問題。

這使得該合約等價於一個到期日為今日收盤的**數位（二元）買權**，履約價 K = 昨收。

數位買權價格 = 買權價格對履約價的負斜率：

    P(S_T > K) = -∂C/∂K  ≈  [C(K-h) - C(K+h)] / (2h)

SPY 每個交易日都有 0DTE 期權，到期時點與本市場完全一致。
所以可以**直接讀出市場隱含機率，完全不需要估計波動率參數**。

這比先估波動率再套 Black-Scholes 穩健得多：
  - 不必選用哪一段的波動率
  - 不必處理波動率微笑/偏斜（call spread 自動吸收）
  - 少一個可以出錯的自由參數

Black-Scholes 僅作為期權資料不可用時的退路。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import config


# --------------------------------------------------------------------------
# 主方法：由 call spread 導出數位機率
# --------------------------------------------------------------------------

def digital_from_chain(calls: list[dict], K: float, bump: float | None = None) -> dict:
    """由買權鏈導出 P(S_T > K)。

    calls: [{'strike': float, 'bid': float, 'ask': float}, ...]
    K:     履約價（= 昨收）

    回傳 dict，含 prob / method / n_strikes / quality。
    prob 為 None 表示無法可靠計算。
    """
    bump = bump if bump is not None else config.DIGITAL_BUMP

    usable = []
    for c in calls:
        bid, ask = c.get("bid"), c.get("ask")
        if bid is None or ask is None:
            continue
        if ask <= 0 or bid < 0 or ask < bid:
            continue
        if (ask - bid) > config.MAX_OPTION_SPREAD:
            continue  # 報價太寬，不可信
        usable.append({"strike": float(c["strike"]), "mid": (bid + ask) / 2})

    if len(usable) < 4:
        return {"prob": None, "method": "call_spread", "n_strikes": len(usable),
                "quality": "履約價樣本不足（<4）"}

    usable.sort(key=lambda x: x["strike"])
    strikes = [u["strike"] for u in usable]

    lo, hi = K - bump, K + bump
    if lo < strikes[0] or hi > strikes[-1]:
        return {"prob": None, "method": "call_spread", "n_strikes": len(usable),
                "quality": f"K={K:.2f} 落在履約價範圍 [{strikes[0]}, {strikes[-1]}] 邊界外"}

    c_lo = _interp(usable, lo)
    c_hi = _interp(usable, hi)
    prob = (c_lo - c_hi) / (2 * bump)

    quality = "ok"
    if not (0.0 <= prob <= 1.0):
        quality = f"機率超出 [0,1]（原始值 {prob:.4f}），已截斷；可能是報價雜訊或套利違反"
    prob = min(max(prob, 0.0), 1.0)

    return {"prob": prob, "method": "call_spread", "n_strikes": len(usable),
            "quality": quality}


def _interp(points: list[dict], x: float) -> float:
    """在履約價格點之間線性內插買權中價。points 需已依 strike 升冪排序。"""
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        if a["strike"] <= x <= b["strike"]:
            if b["strike"] == a["strike"]:
                return a["mid"]
            w = (x - a["strike"]) / (b["strike"] - a["strike"])
            return a["mid"] + w * (b["mid"] - a["mid"])
    return points[-1]["mid"] if x > points[-1]["strike"] else points[0]["mid"]


# --------------------------------------------------------------------------
# 退路：Black-Scholes（僅在期權鏈不可用時使用）
# --------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def digital_from_bs(spot: float, K: float, sigma: float, T_years: float,
                    r: float = 0.0) -> dict:
    """BS 下的數位買權機率 = N(d2)。

    T_years 極小時（接近收盤）d2 會爆炸，結果趨近 0 或 1，屬正常。
    但此時模型誤差最大——臨收盤前的輸出不應被信任。
    """
    if T_years <= 0 or sigma <= 0 or spot <= 0 or K <= 0:
        return {"prob": None, "method": "bs_fallback", "n_strikes": 0,
                "quality": "參數無效（T/sigma/價格需為正）"}
    d2 = (math.log(spot / K) + (r - 0.5 * sigma ** 2) * T_years) / (sigma * math.sqrt(T_years))
    prob = _norm_cdf(d2)
    quality = "ok"
    if T_years < 15 / (252 * 6.5 * 60):  # 剩不到約 15 分鐘
        quality = "距收盤過近，BS 輸出不可靠"
    return {"prob": prob, "method": "bs_fallback", "n_strikes": 0, "quality": quality}


def year_fraction_to_close(now: datetime | None = None) -> float:
    """距今日 20:00 UTC（美股收盤）的年化時間，僅計交易時段。"""
    now = now or datetime.now(timezone.utc)
    close = now.replace(hour=20, minute=0, second=0, microsecond=0)
    seconds = (close - now).total_seconds()
    if seconds <= 0:
        return 0.0
    trading_seconds_per_year = 252 * 6.5 * 3600
    return seconds / trading_seconds_per_year


# --------------------------------------------------------------------------
# 交易成本
# --------------------------------------------------------------------------

def edge_after_taker_fee(model_prob: float, market_price: float, side: str) -> float:
    """主動吃單後的每股淨優勢（USDC）。

    side='up'  : 以 market_price 買進 Up
    side='down': 以 (1-market_price) 買進 Down

    回傳為正才代表扣費後仍有優勢。這是判斷「吃單腿是否還活著」的關鍵指標。
    """
    if side == "up":
        gross = model_prob - market_price
        price_paid = market_price
    else:
        gross = (1.0 - model_prob) - (1.0 - market_price)
        price_paid = 1.0 - market_price
    return gross - config.taker_fee_per_share(price_paid)
