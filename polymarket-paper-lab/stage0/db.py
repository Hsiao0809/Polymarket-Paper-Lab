"""SQLite schema 與寫入。

設計原則：只存原始觀測值，不存衍生計算結果。
分析階段隨時可以改公式重跑，不必重新採集資料。
"""
import sqlite3
from pathlib import Path

SCHEMA = """
-- 每次輪詢的 Polymarket 盤口快照
CREATE TABLE IF NOT EXISTS pm_snapshot (
    ts             INTEGER NOT NULL,   -- unix 秒（採集時間）
    market_slug    TEXT    NOT NULL,
    condition_id   TEXT,
    token_id_up    TEXT,
    book_ts        INTEGER,            -- CLOB 回傳的 timestamp（毫秒）
    best_bid       REAL,               -- 來自 CLOB book，非 Gamma
    best_ask       REAL,
    bid_size       REAL,
    ask_size       REAL,
    mid            REAL,
    spread         REAL,
    last_trade     REAL,
    -- Gamma 的欄位（會延遲，僅供對照）
    gamma_bid      REAL,
    gamma_ask      REAL,
    liquidity      REAL,
    volume_24h     REAL,
    rewards_daily  REAL,
    rewards_minsz  REAL,
    rewards_maxsp  REAL,
    PRIMARY KEY (ts, market_slug)
);

-- 完整訂單簿深度（供之後模擬成交用）
CREATE TABLE IF NOT EXISTS pm_book_level (
    ts          INTEGER NOT NULL,
    market_slug TEXT    NOT NULL,
    side        TEXT    NOT NULL,      -- 'bid' | 'ask'
    price       REAL    NOT NULL,
    size        REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_book_ts ON pm_book_level(ts, market_slug);

-- 標的與期權推導出的機率
CREATE TABLE IF NOT EXISTS opt_snapshot (
    ts            INTEGER NOT NULL,
    underlying    TEXT    NOT NULL,
    spot          REAL,               -- 現價
    prev_close    REAL,               -- 昨收 = 市場的履約價 K
    expiry        TEXT,               -- 使用的期權到期日 (YYYY-MM-DD)
    digital_prob  REAL,               -- P(收盤 > 昨收)，由 call spread 導出
    method        TEXT,               -- 'call_spread' | 'bs_fallback'
    iv_atm        REAL,               -- 參考用
    n_strikes     INTEGER,            -- 參與計算的履約價數
    quality       TEXT,               -- 'ok' | 警告訊息
    PRIMARY KEY (ts, underlying)
);

-- 採集過程的問題記錄。空的才代表資料可信。
CREATE TABLE IF NOT EXISTS collect_error (
    ts      INTEGER NOT NULL,
    source  TEXT,
    message TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_pm(conn, snap: dict, levels: list[dict]) -> None:
    cols = ", ".join(snap.keys())
    marks = ", ".join("?" * len(snap))
    conn.execute(
        f"INSERT OR REPLACE INTO pm_snapshot ({cols}) VALUES ({marks})",
        list(snap.values()),
    )
    if levels:
        conn.executemany(
            "INSERT INTO pm_book_level (ts, market_slug, side, price, size)"
            " VALUES (:ts, :market_slug, :side, :price, :size)",
            levels,
        )
    conn.commit()


def insert_opt(conn, snap: dict) -> None:
    cols = ", ".join(snap.keys())
    marks = ", ".join("?" * len(snap))
    conn.execute(
        f"INSERT OR REPLACE INTO opt_snapshot ({cols}) VALUES ({marks})",
        list(snap.values()),
    )
    conn.commit()


def log_error(conn, ts: int, source: str, message: str) -> None:
    conn.execute(
        "INSERT INTO collect_error (ts, source, message) VALUES (?, ?, ?)",
        (ts, source, str(message)[:500]),
    )
    conn.commit()
