"""集中設定。改這裡就好，不要去改其他檔案。"""

# ---- 目標市場 ----
# Polymarket 的每日 SPY 漲跌系列。collector 會自動抓「今天」那一場。
SERIES_SLUG = "spy-daily-up-or-down"
UNDERLYING = "SPY"

# ---- API 端點 ----
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# ---- 採樣 ----
POLL_SECONDS = 60          # 每次快照間隔
DB_PATH = "paperlab.db"

# ---- 市場規則（2026-07-21 實測值，會變，定期核對）----
TICK_SIZE = 0.01
ORDER_MIN_SIZE = 5         # 最小下單量（股）
REWARDS_MIN_SIZE = 200     # 要拿掛單獎勵的最小掛單量（股）
REWARDS_MAX_SPREAD = 4.5   # 要拿獎勵，需掛在中價 ±4.5¢ 內
REWARDS_DAILY_RATE = 1000  # 該市場每日獎勵池（USDC）

# ---- 手續費（finance_prices_fees）----
# Polymarket 費用公式：fee = rate * min(p, 1-p) * size
# 只有 taker 付費；maker 零費用，且分得 rebate_rate 比例的 taker 費。
FEE_RATE = 0.04
FEE_TAKER_ONLY = True
FEE_REBATE_RATE = 0.25


def taker_fee_per_share(price: float) -> float:
    """單股 taker 手續費（USDC）。在 p=0.5 最貴，往兩端遞減。"""
    return FEE_RATE * min(price, 1.0 - price)


# ---- 期權定價 ----
# 用 call spread 數值微分求數位選擇權機率時的半寬（美元）。
# 太小會被 tick 雜訊淹沒，太大則平滑掉真實曲率。SPY 建議 0.5~1.5。
DIGITAL_BUMP = 1.0

# 期權報價的最大可接受買賣價差（美元）。超過視為不可信，捨棄該履約價。
MAX_OPTION_SPREAD = 0.60
