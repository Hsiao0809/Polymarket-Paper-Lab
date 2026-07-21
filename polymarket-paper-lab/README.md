# Polymarket Paper Lab（唯讀／模擬盤）

這是從零開始驗證「美股事件機率是否被預測市場錯價」的最小研究工具。

建議先讀 [12 週路線](ROADMAP.md)，再執行下面的工具。

多策略邏輯與失效條件整理在 [多策略研究手冊](STRATEGIES.md)。

它刻意不包含錢包、私鑰、API 金鑰或下單功能。Polymarket 官方目前把台灣列為 `close-only`；本專案只能讀取公開市場資料、計算模型價格與記錄模擬決策，不能用來規避地區限制。

## 它會做什麼

- 用簡化的 lognormal／binary-option 機率模型估算「到期價高於門檻」的機率。
- 分開輸入日盤與隔夜年化波動率，並用可校準權重合成有效波動率。
- 把 taker fee、預估滑價、bid/ask spread 納入交易成本。
- 同時比較 YES 與 NO，只有通過 edge、ROI、流動性、點差及風控門檻才產生模擬訊號。
- 使用 fractional Kelly，但再受每筆最大資金比例限制。
- 可讀取 Polymarket Gamma 公開 API 來列出 Finance 市場；不需要登入。

## 先執行測試

在此資料夾開啟 PowerShell 或命令提示字元。`run.cmd` 會先找 Python 3.12，找不到時自動使用可用的 `python`：

```powershell
run.cmd test
```

預期看到所有測試為 `OK`。

## 官方 SDK

專案已在 `.venv` 安裝 Polymarket 官方文件列出的 Python CLOB V2 SDK：

```text
py-clob-client-v2==1.0.1
```

版本已鎖定在 [requirements-sdk.txt](requirements-sdk.txt)，避免日後自動升級造成介面突然改變。確認安裝：

```powershell
run.cmd sdk-check
```

重新建立或安裝：

```powershell
install-sdk.cmd
```

`sdk-check` 只建立不含驗證資訊的 `ClobClient`，不會讀取私鑰、不會登入，也不會下單。

## 跑一個估值範例

以下假設：現價與門檻都是 210、美股下一交易日、日盤波動率 32%、隔夜波動率 45%、YES ask 48¢、NO ask 55¢。

```powershell
run.cmd score --question "NVDA tomorrow above 210?" --spot 210 --threshold 210 --days 1 --session-vol 0.32 --overnight-vol 0.45 --yes-bid 0.46 --yes-ask 0.48 --no-bid 0.53 --no-ask 0.55 --liquidity 5000 --bankroll 300
```

你會看到模型機率、費用後成本、edge、ROI、建議模擬金額，以及 `TRADE` 或 `NO_TRADE`。這只是模型輸出，不是投資建議或實盤指令。

## 掃描多策略候選

內建三種結構性掃描：同市場 YES+NO 完整組合、邏輯包含／價格門檻單調性，以及互斥完備的多結果分割。

```powershell
run.cmd scan-strategies --input examples\strategy_snapshot.example.json
```

範例只使用合成 orderbook 數字，用來驗證計算，並不是即時賺錢機會。每個候選都已納入 ask、官方 fee 公式、滑價及可成交深度；所有腿未完整成交時，輸出的最低支付關係不成立。

## 列出公開 Finance 市場

```powershell
run.cmd discover --limit 20
```

只找股票日／週事件：

```powershell
run.cmd discover --limit 100 --title-filter "up or down|finish week|close"
```

若公司網路或 Windows 憑證鏈擋住 HTTPS，程式會停止並顯示錯誤；不要用關閉 TLS 驗證的方式處理。

## 預設風控

- 最低淨 edge：4 個百分點
- 最低預期 ROI：8%
- 最大 YES/NO 點差：10 個百分點
- 最低市場流動性：1,000 USDC
- 每筆最大投入：模擬本金 1%
- Kelly：四分之一 Kelly，仍受 1% 上限限制
- 無足夠 edge 時必須是 `NO_TRADE`

這些值不是最佳化結果，只是防止新手一開始過度交易的保守起點。

## 進入下一階段前的硬門檻

不要因為幾天賺錢就換成實盤。至少完成：

1. 連續 90 個交易日的 out-of-sample 模擬，不重寫舊訊號。
2. 至少 200 筆「可成交」樣本，必須使用當時的 bid/ask，而非事後 midpoint。
3. 費用與滑價後為正，且報告最大回撤、Brier score、校準曲線與按市場類型分組的 P&L。
4. 把 maker rebate 單獨列出；策略本體若扣掉獎勵就虧損，不算穩健 edge。
5. 用 walk-forward 或時間切割，禁止隨機切割造成未來資料洩漏。
6. 實際交易場域在你的所在地合法可用；不可使用 VPN 規避。

## 目錄

```text
src/paperlab/model.py       機率與有效波動率
src/paperlab/decision.py    費用、edge、Kelly 與風控
src/paperlab/strategies.py  結構性多策略掃描器
src/paperlab/polymarket.py  官方公開 API（唯讀）
src/paperlab/cli.py         命令列介面
examples/                   合成市場快照
tests/                      單元測試
```

## 模型限制

這個模型是研究基線，不是成品。它沒有處理跳空厚尾、波動率微笑、財報日事件跳躍、股息、盤中路徑、交易暫停、解析規則差異與掛單成交機率。下一版應接入「有時間戳的完整期權鏈」，由 strike-by-strike 的風險中性分布建模，並另做真實世界機率校準。
