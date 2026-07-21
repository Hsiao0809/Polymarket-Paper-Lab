"""定價邏輯的自我驗證。不需網路，直接執行： python test_pricing.py

用已知答案的合成期權鏈檢查數位機率導出是否正確。
若這些測試不過，採集到的資料再多也沒有意義。
"""
import math
import sys

import config
import pricing


def bs_call(S, K, sigma, T, r=0.0):
    if T <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * pricing._norm_cdf(d1) - K * math.exp(-r * T) * pricing._norm_cdf(d2)


def synthetic_chain(S, sigma, T, lo, hi, step=0.5):
    """由 BS 產生的合成買權鏈。真實答案為 N(d2)。"""
    calls = []
    k = lo
    while k <= hi:
        c = bs_call(S, k, sigma, T)
        calls.append({"strike": round(k, 2), "bid": c - 0.01, "ask": c + 0.01})
        k += step
    return calls


PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"  [{PASS if cond else FAIL}] {name}" + (f"  — {detail}" if detail else ""))


print("=" * 60)
print("定價邏輯驗證")
print("=" * 60)

# ---------------------------------------------------------------
print("\n1. 數位機率導出 vs Black-Scholes 解析解")
S, sigma, T = 640.0, 0.13, 6.5 / (252 * 6.5)   # 剩一個交易日
for K, label in [(638.0, "價內"), (640.0, "價平"), (642.5, "價外")]:
    chain = synthetic_chain(S, sigma, T, K - 12, K + 12)
    got = pricing.digital_from_chain(chain, K)
    d2 = (math.log(S / K) - 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    want = pricing._norm_cdf(d2)
    err = abs(got["prob"] - want)
    check(f"{label} K={K}", err < 0.02,
          f"導出 {got['prob']:.4f} vs 解析 {want:.4f}（誤差 {err:.4f}）")

# ---------------------------------------------------------------
print("\n2. 單調性：K 越高，P(S_T > K) 應越低")
chain = synthetic_chain(S, sigma, T, 620, 660)
probs = [pricing.digital_from_chain(chain, k)["prob"] for k in (632, 636, 640, 644, 648)]
check("機率隨履約價遞減", all(a > b for a, b in zip(probs, probs[1:])),
      " > ".join(f"{p:.3f}" for p in probs))

# ---------------------------------------------------------------
print("\n3. 資料品質防護")
check("履約價過少時回傳 None",
      pricing.digital_from_chain([{"strike": 640, "bid": 1, "ask": 1.1}], 640)["prob"] is None)

far = pricing.digital_from_chain(synthetic_chain(S, sigma, T, 630, 650), 700)
check("K 落在鏈外時回傳 None", far["prob"] is None, far["quality"][:50])

wide = [{"strike": k, "bid": 0.1, "ask": 5.0} for k in range(630, 651)]
check("報價過寬時被濾除", pricing.digital_from_chain(wide, 640)["prob"] is None)

# ---------------------------------------------------------------
print("\n4. 手續費公式")
f50 = config.taker_fee_per_share(0.50)
f90 = config.taker_fee_per_share(0.90)
check("p=0.5 時費用最高", f50 > f90, f"0.5→{f50:.4f}　0.9→{f90:.4f}")
check("p=0.5 費用 = rate/2", abs(f50 - config.FEE_RATE / 2) < 1e-9, f"{f50:.4f}")
check("對稱性 f(p)=f(1-p)",
      abs(config.taker_fee_per_share(0.23) - config.taker_fee_per_share(0.77)) < 1e-9)

# ---------------------------------------------------------------
print("\n5. 以今日實測盤口試算（2026-07-21 SPY）")
# CLOB book 實測：bid 0.76 / ask 0.77，中價 0.765
mid = 0.765
for model_p, desc in [(0.80, "模型高於市場"), (0.72, "模型低於市場"), (0.77, "幾乎一致")]:
    e_up = pricing.edge_after_taker_fee(model_p, mid, "up")
    e_dn = pricing.edge_after_taker_fee(model_p, mid, "down")
    best = max(e_up, e_dn)
    print(f"     模型={model_p:.2f} 中價={mid:.3f} → 買Up {e_up:+.4f} / 買Down {e_dn:+.4f}"
          f"  {'有優勢' if best > 0 else '無優勢'}  ({desc})")

gap_needed = config.taker_fee_per_share(mid)
check("吃單門檻計算正確", gap_needed > 0,
      f"在 mid={mid} 需 gap > {gap_needed:.4f} 才划算")

# ---------------------------------------------------------------
print("\n6. 門檻隨價格變化（重要：費用在兩端較便宜）")
# fee = rate * min(p, 1-p)，故在極端價位所需的 gap 門檻低很多。
# 這代表機會不是均勻分布的——越接近 0 或 1，越小的定價誤差就足以獲利。
thresholds = {p: config.taker_fee_per_share(p) for p in (0.50, 0.65, 0.765, 0.90, 0.95)}
for p, t in thresholds.items():
    print(f"     中價 {p:.3f} → 需 gap > {t:.4f}（{t*100:.2f}¢）")

check("門檻在 p=0.5 最高",
      thresholds[0.50] == max(thresholds.values()), f"{thresholds[0.50]:.4f}")
check("極端價位門檻遠低於價平",
      thresholds[0.95] < thresholds[0.50] / 4,
      f"0.95→{thresholds[0.95]:.4f} vs 0.50→{thresholds[0.50]:.4f}")

# 在今日 mid=0.765，1¢ gap 剛好越過 0.94¢ 的門檻
small = pricing.edge_after_taker_fee(0.775, mid, "up")
check("1¢ gap 在 mid=0.765 剛好可覆蓋費用", small > 0,
      f"淨優勢 {small:+.4f}（門檻僅 {gap_needed:.4f}）")

# 但同樣 1¢ gap 在價平就不夠
small_atm = pricing.edge_after_taker_fee(0.51, 0.50, "up")
check("同樣 1¢ gap 在 mid=0.50 不足", small_atm < 0, f"淨優勢 {small_atm:+.4f}")

# ---------------------------------------------------------------
print("\n" + "=" * 60)
n_pass, n_all = sum(results), len(results)
print(f"結果：{n_pass}/{n_all} 通過")
print("=" * 60)
sys.exit(0 if n_pass == n_all else 1)
