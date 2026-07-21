"""階段 1：量測 gap，判斷 edge 是否存在。

用法：
    python analyze.py                 # 文字報告
    python analyze.py --plot out.png  # 另存分布圖

這支程式的目的是**把策略殺掉**。
若 gap 中位數小於 taker 手續費，吃單那條腿就沒有意義——這是好結果，
代表你在投入時間與金錢之前就知道了。
"""
from __future__ import annotations

import argparse
import statistics as st

import config
import db

QUERY = """
SELECT p.ts, p.best_bid, p.best_ask, p.mid, p.spread,
       p.bid_size, p.ask_size, p.rewards_daily,
       o.digital_prob, o.method, o.quality, o.spot, o.prev_close
FROM pm_snapshot p
JOIN opt_snapshot o ON o.ts = p.ts
WHERE p.mid IS NOT NULL AND o.digital_prob IS NOT NULL
ORDER BY p.ts
"""


def load(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(QUERY)]


def describe(name: str, xs: list[float], unit: str = "") -> str:
    if not xs:
        return f"{name}: 無資料"
    xs = sorted(xs)
    n = len(xs)
    return (
        f"{name}\n"
        f"  樣本數    {n}\n"
        f"  平均      {st.mean(xs):+.4f}{unit}\n"
        f"  中位數    {st.median(xs):+.4f}{unit}\n"
        f"  標準差    {st.pstdev(xs):.4f}{unit}\n"
        f"  5%/95%    {xs[int(0.05*n)]:+.4f} / {xs[int(0.95*n)]:+.4f}{unit}\n"
        f"  最小/最大 {xs[0]:+.4f} / {xs[-1]:+.4f}{unit}"
    )


def report(rows: list[dict]) -> str:
    if not rows:
        return ("沒有可用資料。\n"
                "請先執行 collector.py 採集，並確認 collect_error 表為空。")

    out: list[str] = []
    out.append("=" * 62)
    out.append("階段 1：Gap 量測報告")
    out.append("=" * 62)

    ok = [r for r in rows if r["quality"] == "ok"]
    excluded = len(rows) - len(ok)
    out.append(f"\n總快照 {len(rows)} 筆，品質正常 {len(ok)} 筆，排除 {excluded} 筆")
    if excluded:
        reasons: dict[str, int] = {}
        for r in rows:
            if r["quality"] != "ok":
                reasons[r["quality"]] = reasons.get(r["quality"], 0) + 1
        out.append("  排除原因：")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
            out.append(f"    {v:>5}×  {k[:70]}")

    if not ok:
        out.append("\n沒有任何品質正常的樣本，無法下結論。")
        return "\n".join(out)

    gaps = [r["digital_prob"] - r["mid"] for r in ok]
    abs_gaps = [abs(g) for g in gaps]
    fees = [config.taker_fee_per_share(r["mid"]) for r in ok]
    spreads = [r["spread"] for r in ok if r["spread"] is not None]

    out.append("\n" + "-" * 62)
    out.append(describe("Gap（模型機率 − Polymarket 中價）", gaps))
    out.append("")
    out.append(describe("Gap 絕對值", abs_gaps))
    out.append("")
    out.append(describe("Polymarket 買賣價差", spreads))
    out.append("")
    out.append(describe("Taker 手續費（每股）", fees))

    # ---- 核心判斷 ----
    out.append("\n" + "=" * 62)
    out.append("核心判斷：吃單腿是否存活")
    out.append("=" * 62)

    med_abs = st.median(abs_gaps)
    med_fee = st.median(fees)
    profitable = [
        r for r, g, f in zip(ok, abs_gaps, fees)
        if g > f + (r["spread"] or 0) / 2
    ]
    pct = 100 * len(profitable) / len(ok)

    out.append(f"\nGap 絕對值中位數      {med_abs:.4f}")
    out.append(f"Taker 費用中位數      {med_fee:.4f}")
    out.append(f"半價差中位數          {st.median(spreads)/2 if spreads else 0:.4f}")
    out.append(f"\n扣除費用與半價差後仍有優勢的時點：{len(profitable)}/{len(ok)}（{pct:.1f}%）")

    if pct < 5:
        verdict = ("結論：吃單腿基本上死了。\n"
                   "  優勢極少超過交易成本。不要在這條路上投入資金。\n"
                   "  → 若要繼續，只能走做市（maker）方向：零手續費 + 獎勵池。")
    elif pct < 20:
        verdict = ("結論：吃單腿邊際可行，但脆弱。\n"
                   "  機會存在但稀少，且未計入延遲與滑價（實際會更差）。\n"
                   "  → 做市仍是較穩健的主線，吃單只能當機會性補充。")
    else:
        verdict = ("結論：吃單腿看似存活——但請先懷疑資料。\n"
                   "  優先檢查：期權資料是否延遲？到期日是否匹配？\n"
                   "  yfinance 有約 15 分鐘延遲，會製造虛假的 gap。\n"
                   "  → 換成即時報價源重測後才可採信。")
    out.append("\n" + verdict)

    # ---- 做市側 ----
    out.append("\n" + "=" * 62)
    out.append("做市側參考")
    out.append("=" * 62)
    rd = ok[-1]["rewards_daily"]
    if rd:
        out.append(f"\n每日獎勵池           ${rd:,.0f}")
        out.append(f"獎勵最小掛單量       {config.REWARDS_MIN_SIZE} 股")
        out.append(f"獎勵最大偏離         {config.REWARDS_MAX_SPREAD}¢")
        out.append(f"Maker 手續費         0（僅 taker 付費）")
        out.append(f"Taker 費回饋 maker   {config.FEE_REBATE_RATE:.0%}")
        out.append("\n注意：獎勵池由所有合格 maker 按比例分配。"
                   "\n      你的份額 ≈ 你的合格掛單量 / 全體合格掛單量。"
                   "\n      這無法從公開盤口精確反推，需實際掛單後觀察。")

    out.append("\n" + "=" * 62)
    out.append("提醒：以上僅為觀測統計，不構成投資建議。")
    out.append("尚未計入逆選擇成本——那是做市的主要風險，需在階段 2 模擬。")
    out.append("=" * 62)
    return "\n".join(out)


def plot(rows: list[dict], path: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安裝 matplotlib，略過繪圖： pip install matplotlib")
        return

    ok = [r for r in rows if r["quality"] == "ok"]
    if not ok:
        print("無可繪製資料")
        return

    gaps = [r["digital_prob"] - r["mid"] for r in ok]
    fees = [config.taker_fee_per_share(r["mid"]) for r in ok]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8))

    ax1.hist(gaps, bins=50, color="#4a7ebb", edgecolor="white", linewidth=0.5)
    mf = st.median(fees)
    ax1.axvline(0, color="black", lw=1)
    ax1.axvline(mf, color="crimson", ls="--", lw=1.4, label=f"taker 費用中位數 ±{mf:.3f}")
    ax1.axvline(-mf, color="crimson", ls="--", lw=1.4)
    ax1.set_title("Gap 分布：模型機率 − Polymarket 中價")
    ax1.set_xlabel("gap")
    ax1.set_ylabel("次數")
    ax1.legend()

    ts0 = ok[0]["ts"]
    hrs = [(r["ts"] - ts0) / 3600 for r in ok]
    ax2.plot(hrs, [r["digital_prob"] for r in ok], label="期權隱含機率", lw=1.3)
    ax2.plot(hrs, [r["mid"] for r in ok], label="Polymarket 中價", lw=1.3)
    ax2.set_title("兩者走勢對照")
    ax2.set_xlabel("採集起始後小時數")
    ax2.set_ylabel("機率")
    ax2.legend()
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    print(f"圖已存至 {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--plot", help="輸出圖檔路徑，例如 gap.png")
    args = ap.parse_args()

    conn = db.connect(args.db)

    errs = conn.execute("SELECT COUNT(*) c FROM collect_error").fetchone()["c"]
    if errs:
        print(f"⚠ collect_error 表有 {errs} 筆錯誤，資料可能不完整。")
        for r in conn.execute(
            "SELECT source, message, COUNT(*) c FROM collect_error"
            " GROUP BY source, message ORDER BY c DESC LIMIT 5"
        ):
            print(f"   {r['c']:>4}× [{r['source']}] {r['message'][:80]}")
        print()

    rows = load(conn)
    print(report(rows))
    if args.plot:
        plot(rows, args.plot)
    conn.close()


if __name__ == "__main__":
    main()
