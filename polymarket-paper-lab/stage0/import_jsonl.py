"""把雲端採集的 JSONL 匯入 SQLite，讓 analyze.py 可以直接使用。

用法：
    python import_jsonl.py data/snapshots.jsonl
    python analyze.py --plot gap.png

可重複執行，不會產生重複資料（以 ts 為主鍵覆寫）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
import db

PM_FIELDS = ["ts", "market_slug", "condition_id", "token_id_up", "best_bid", "best_ask",
             "bid_size", "ask_size", "mid", "spread", "last_trade", "gamma_bid",
             "gamma_ask", "liquidity", "volume_24h", "rewards_daily",
             "rewards_minsz", "rewards_maxsp"]

OPT_FIELDS = ["ts", "underlying", "spot", "prev_close", "expiry", "digital_prob",
              "method", "iv_atm", "n_strikes", "quality"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="?", default="data/snapshots.jsonl")
    ap.add_argument("--db", default=config.DB_PATH)
    args = ap.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        raise SystemExit(f"找不到檔案：{path}")

    conn = db.connect(args.db)
    n_pm = n_opt = n_err = n_bad = 0

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            n_bad += 1
            continue

        ts = row.get("ts")
        if ts is None:
            n_bad += 1
            continue

        if row.get("mid") is not None:
            db.insert_pm(conn, {k: row.get(k) for k in PM_FIELDS}, [])
            n_pm += 1

            # 還原訂單簿前 5 檔
            levels = [
                {"ts": ts, "market_slug": row.get("market_slug"), "side": side,
                 "price": lv["price"], "size": lv["size"]}
                for side, key in (("bid", "bids_top5"), ("ask", "asks_top5"))
                for lv in (row.get(key) or [])
            ]
            if levels:
                conn.executemany(
                    "INSERT INTO pm_book_level (ts, market_slug, side, price, size)"
                    " VALUES (:ts, :market_slug, :side, :price, :size)", levels)

        if row.get("digital_prob") is not None:
            db.insert_opt(conn, {k: row.get(k) for k in OPT_FIELDS})
            n_opt += 1

        for msg in row.get("errors") or []:
            src = msg.split(":", 1)[0]
            db.log_error(conn, ts, src, msg)
            n_err += 1

    conn.commit()
    print(f"匯入完成 → {args.db}")
    print(f"  Polymarket 快照 {n_pm}")
    print(f"  期權快照       {n_opt}")
    print(f"  採集錯誤       {n_err}")
    if n_bad:
        print(f"  ⚠ 無法解析的行 {n_bad}")
    print("\n接著執行： python analyze.py --plot gap.png")
    conn.close()


if __name__ == "__main__":
    main()
