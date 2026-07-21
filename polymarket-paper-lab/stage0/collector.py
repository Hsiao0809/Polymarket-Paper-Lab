"""採集主程式。

用法：
    python collector.py            # 持續採集，Ctrl+C 停止
    python collector.py --once     # 只跑一次（用來測試接線是否正常）

設計：單邊失敗不中斷。Polymarket 掛了照樣記期權，反之亦然，
錯誤寫進 collect_error 表。分析前務必檢查該表是否為空。
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import config
import db
import options
import polymarket as pm
import pricing


def collect_polymarket(conn, ts: int) -> dict | None:
    try:
        market = pm.find_today_market()
        if not market:
            db.log_error(conn, ts, "polymarket", "找不到今日市場（可能非交易日或系列已下架）")
            return None

        token_id = pm.up_token_id(market)
        if not token_id:
            db.log_error(conn, ts, "polymarket", "market 缺少 clobTokenIds")
            return None

        book = pm.fetch_book(token_id)
        snap, levels = pm.build_snapshot(ts, market, token_id, book)
        db.insert_pm(conn, snap, levels)
        return snap
    except Exception as e:
        db.log_error(conn, ts, "polymarket", e)
        return None


def collect_options(conn, ts: int) -> dict | None:
    try:
        spot_info = options.fetch_spot_and_prev_close()
        spot = spot_info["spot"]
        K = spot_info["prev_close"]

        chain = options.fetch_0dte_calls()
        result = pricing.digital_from_chain(chain["calls"], K)

        # 期權鏈不可用時退回 BS
        if result["prob"] is None:
            iv = options.atm_iv(config.UNDERLYING, spot, chain["expiry"])
            if iv:
                T = pricing.year_fraction_to_close()
                bs = pricing.digital_from_bs(spot, K, iv, T)
                bs["quality"] = f"{result['quality']} → 退回 BS：{bs['quality']}"
                result = bs

        note = chain["note"]
        quality = result["quality"] if note == "ok" else f"{note}；{result['quality']}"

        snap = {
            "ts": ts,
            "underlying": config.UNDERLYING,
            "spot": spot,
            "prev_close": K,
            "expiry": chain["expiry"],
            "digital_prob": result["prob"],
            "method": result["method"],
            "iv_atm": options.atm_iv(config.UNDERLYING, spot, chain["expiry"]),
            "n_strikes": result["n_strikes"],
            "quality": quality,
        }
        db.insert_opt(conn, snap)
        return snap
    except Exception as e:
        db.log_error(conn, ts, "options", e)
        return None


def _fmt(x, nd=4):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "—"


def tick(conn) -> None:
    ts = int(time.time())
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")

    p = collect_polymarket(conn, ts)
    o = collect_options(conn, ts)

    parts = [f"[{stamp}Z]"]
    if p:
        parts.append(f"PM {_fmt(p['best_bid'],2)}/{_fmt(p['best_ask'],2)}"
                     f" mid={_fmt(p['mid'],3)}")
    else:
        parts.append("PM ✗")

    if o and o["digital_prob"] is not None:
        parts.append(f"模型={_fmt(o['digital_prob'],3)} ({o['method']})")
        if p and p["mid"] is not None:
            gap = o["digital_prob"] - p["mid"]
            fee = config.taker_fee_per_share(p["mid"])
            parts.append(f"gap={gap:+.3f} 費用={fee:.3f}")
            if abs(gap) > fee:
                parts.append("← 扣費後仍有優勢")
    else:
        parts.append("模型 ✗")

    print("  ".join(parts), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只採集一次後結束")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--interval", type=int, default=config.POLL_SECONDS)
    args = ap.parse_args()

    conn = db.connect(args.db)
    print(f"資料庫：{args.db}　間隔：{args.interval}s")

    if args.once:
        tick(conn)
        return

    print("持續採集中，Ctrl+C 停止。\n")
    try:
        while True:
            tick(conn)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
