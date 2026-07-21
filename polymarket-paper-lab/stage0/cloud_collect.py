"""雲端用的單次採集：跑一次、附加一行 JSONL、結束。

為什麼不用 SQLite：
GitHub Actions 每次都是全新容器，SQLite 二進位檔要 commit 回 repo 會產生
衝突且無法 diff。JSONL 是純文字、只追加、天生無衝突，用 git 管理剛好。

分析時用 import_jsonl.py 轉回 SQLite 即可，analyze.py 完全不用改。

用法：
    python cloud_collect.py                      # 附加到 data/snapshots.jsonl
    python cloud_collect.py --out other.jsonl
    python cloud_collect.py --dry-run            # 只印出不寫檔
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import options
import polymarket as pm
import pricing


def snapshot() -> dict:
    """採集一筆完整觀測。任一邊失敗都記錄在 errors 欄位，不拋出例外。

    回傳的 dict 就是要寫進 JSONL 的那一行。
    """
    ts = int(time.time())
    row: dict = {
        "ts": ts,
        "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "errors": [],
    }

    # ---- Polymarket ----
    try:
        market = pm.find_today_market()
        if not market:
            row["errors"].append("polymarket: 找不到今日市場（非交易日或系列下架）")
        else:
            token_id = pm.up_token_id(market)
            book = pm.fetch_book(token_id)
            snap, _levels = pm.build_snapshot(ts, market, token_id, book)
            for k in ("market_slug", "best_bid", "best_ask", "bid_size", "ask_size",
                      "mid", "spread", "last_trade", "gamma_bid", "gamma_ask",
                      "liquidity", "volume_24h", "rewards_daily",
                      "rewards_minsz", "rewards_maxsp", "condition_id", "token_id_up"):
                row[k] = snap.get(k)
            # 訂單簿前 5 檔，供之後估算成交深度
            row["bids_top5"] = book["bids"][:5]
            row["asks_top5"] = book["asks"][:5]
    except Exception as e:
        row["errors"].append(f"polymarket: {e}")

    # ---- 期權 ----
    try:
        info = options.fetch_spot_and_prev_close()
        spot, K = info["spot"], info["prev_close"]
        chain = options.fetch_0dte_calls()
        res = pricing.digital_from_chain(chain["calls"], K)

        if res["prob"] is None:
            iv = options.atm_iv(config.UNDERLYING, spot, chain["expiry"])
            if iv:
                bs = pricing.digital_from_bs(spot, K, iv, pricing.year_fraction_to_close())
                bs["quality"] = f"{res['quality']} → 退回 BS：{bs['quality']}"
                res = bs

        row.update({
            "underlying": config.UNDERLYING,
            "spot": spot,
            "prev_close": K,
            "expiry": chain["expiry"],
            "digital_prob": res["prob"],
            "method": res["method"],
            "n_strikes": res["n_strikes"],
            "quality": res["quality"] if chain["note"] == "ok"
                       else f"{chain['note']}；{res['quality']}",
            "iv_atm": options.atm_iv(config.UNDERLYING, spot, chain["expiry"]),
        })
    except Exception as e:
        row["errors"].append(f"options: {e}")

    # ---- 衍生欄位（方便快速檢視，分析時會重算）----
    if row.get("digital_prob") is not None and row.get("mid") is not None:
        row["gap"] = row["digital_prob"] - row["mid"]
        row["taker_fee"] = config.taker_fee_per_share(row["mid"])
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/snapshots.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    row = snapshot()

    bid, ask = row.get("best_bid"), row.get("best_ask")
    parts = [row["iso"]]
    parts.append(f"PM {bid}/{ask}" if bid is not None else "PM ✗")
    if row.get("digital_prob") is not None:
        parts.append(f"模型={row['digital_prob']:.3f}")
    if row.get("gap") is not None:
        flag = " ←扣費後有優勢" if abs(row["gap"]) > row["taker_fee"] else ""
        parts.append(f"gap={row['gap']:+.4f} 費用={row['taker_fee']:.4f}{flag}")
    if row["errors"]:
        parts.append(f"錯誤={row['errors']}")
    print("  ".join(parts))

    if args.dry_run:
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"已附加至 {out}")


if __name__ == "__main__":
    main()
