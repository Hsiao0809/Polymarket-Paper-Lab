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

# ---- 市場規則 ----
TICK_SIZE = 0.01           # 注意：實測有市場用 0.001，以 book 回傳的 tick_size 為準
ORDER_MIN_SIZE = 5         # 最小下單量（股）

# ⚠ 以下獎勵參數「不是常數」，僅作為預設值與健全性檢查基準。
#   真實值必須逐筆從 pm_snapshot.rewards_* 讀取。
#
#   2026-07-21 實測，同一個 SPY 每日系列在不同市場/時點差異極大：
#     7/21 13:47Z  rewardsDailyRate=1000  rewardsMinSize=200
#     7/21 17:50Z  clobRewards 欄位整個消失（接近結算時被撤除）
#     7/22 開盤    rewardsDailyRate=1     rewardsMinSize=20
#
#   1000 與 1 相差三個數量級。任何「以 $1,000/天獎勵池」為前提的
#   收益推估都是錯的，除非你已用實際資料確認該市場當下的獎勵率。
#   收集器每次輪詢都會記錄，跑幾天即可看出變化規律。
REWARDS_MIN_SIZE_DEFAULT = 200
REWARDS_MAX_SPREAD_DEFAULT = 4.5   # 需掛在中價 ±4.5¢ 內才算合格
REWARDS_DAILY_RATE_DEFAULT = None  # 蓄意設為 None：不提供假的預設值

# 向後相容（舊程式碼引用）
REWARDS_MIN_SIZE = REWARDS_MIN_SIZE_DEFAULT
REWARDS_MAX_SPREAD = REWARDS_MAX_SPREAD_DEFAULT

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
