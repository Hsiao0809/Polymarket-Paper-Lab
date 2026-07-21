"""期權鏈與標的行情擷取（yfinance）。

yfinance 是免費且延遲的資料源（約 15 分鐘）。
對「量測 gap 是否存在」這個研究目的足夠；對實盤報價則不夠。
若階段 1 證實 gap 存在，再考慮付費即時源（貼文作者即走此路）。

資料源以函式封裝，之後抽換不影響其他模組。
"""
from __future__ import annotations

from datetime import datetime, timezone

import config


def _require_yf():
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError(
            "缺少 yfinance。請執行： pip install yfinance"
        ) from e
    return yf


def fetch_spot_and_prev_close(symbol: str = config.UNDERLYING) -> dict:
    """取得現價與昨收。

    昨收即為市場的履約價 K。

    注意：Polymarket 以 **Pyth** 的收盤價結算，此處用的是 Yahoo 資料。
    兩者通常極接近但不保證相同。若要正式驗證結算，需改用 Pyth 資料源。
    """
    yf = _require_yf()
    t = yf.Ticker(symbol)
    hist = t.history(period="5d", interval="1d")
    if len(hist) < 2:
        raise RuntimeError(f"{symbol} 歷史資料不足，無法取得昨收")

    prev_close = float(hist["Close"].iloc[-2])
    spot = float(hist["Close"].iloc[-1])

    # 盤中優先使用即時報價
    try:
        fi = t.fast_info
        live = fi.get("last_price") if hasattr(fi, "get") else getattr(fi, "last_price", None)
        if live:
            spot = float(live)
    except Exception:
        pass

    return {"spot": spot, "prev_close": prev_close}


def fetch_0dte_calls(symbol: str = config.UNDERLYING) -> dict:
    """取得今日到期（0DTE）的買權鏈。

    若今日無到期合約（週末/假日），改取最近一個到期日，並在 note 中標示——
    此時到期日與市場結算時點不一致，導出的機率會有偏誤，分析時需排除。
    """
    yf = _require_yf()
    t = yf.Ticker(symbol)
    expirations = list(t.options)
    if not expirations:
        raise RuntimeError(f"{symbol} 無可用期權到期日")

    today = datetime.now(timezone.utc).date().isoformat()
    if today in expirations:
        expiry, note = today, "ok"
    else:
        expiry = expirations[0]
        note = f"今日無 0DTE，改用 {expiry}（到期日不匹配，機率有偏誤）"

    chain = t.option_chain(expiry)
    calls = []
    for _, row in chain.calls.iterrows():
        bid, ask = row.get("bid"), row.get("ask")
        if bid is None or ask is None:
            continue
        try:
            bid, ask = float(bid), float(ask)
        except (TypeError, ValueError):
            continue
        if ask <= 0:
            continue
        calls.append({"strike": float(row["strike"]), "bid": bid, "ask": ask})

    calls.sort(key=lambda c: c["strike"])
    return {"expiry": expiry, "calls": calls, "note": note}


def atm_iv(symbol: str, spot: float, expiry: str) -> float | None:
    """平價隱含波動率，僅作為紀錄與 BS 退路使用。"""
    yf = _require_yf()
    try:
        chain = yf.Ticker(symbol).option_chain(expiry)
        df = chain.calls
        idx = (df["strike"] - spot).abs().idxmin()
        iv = float(df.loc[idx, "impliedVolatility"])
        return iv if iv > 0 else None
    except Exception:
        return None
