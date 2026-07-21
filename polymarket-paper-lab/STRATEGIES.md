# 多策略研究手冊

以下策略只產生 `PAPER_CANDIDATE`，不會送單。程式裡的「locked profit」是指：在所有腿都以輸入價格完整成交、合約邏輯與解析規則完全正確的前提下，終值的最低支付減去費用後成本。它不代表現實中無風險，因為多腿通常不是原子成交。

## 1. YES + NO Complete Set

同一個二元市場中，YES 與 NO 必有一方支付 1。

```text
最低支付 = 1
總成本 = YES ask + NO ask + 兩邊 fee + 兩邊 slippage
```

只有總成本低於 1 且超過最低安全邊際才列為候選。不能拿畫面 midpoint 計算，因為真正立即買入支付的是 ask。

主要失效風險：第二腿價格先跑掉、其中一腿只有很少深度、輸入的 token 其實不是同一市場的互補結果。

## 2. Logical Containment／門檻單調性

若事件 A 必然導致事件 B，則 A 是 B 的子集合。例如在相同收盤時間及相同解析來源下：

```text
NVDA > 230  一定導致  NVDA > 220
```

組合為：

```text
BUY NO(A) + BUY YES(B)
```

三種終局的總支付至少為 1；在 220–230 之間時兩腿都贏、支付為 2。

同樣邏輯可用於「在較早日期前曾經碰到 X」包含於「在較晚日期前曾經碰到 X」。但不能用在兩個不同日期的普通收盤價，因為早期收高不代表晚期仍收高。

主要失效風險：市場使用不同時區、regular session 與 extended hours 定義不同、`>` 與 `>=` 不同、資料來源不同、股票分割規則不同。

## 3. Exhaustive Partition／多結果完整分割

對一組互斥且完備、最終恰好一個結果會贏的市場，買下所有 outcome 的 YES：

```text
最低支付 = 1
總成本 = 所有 YES ask + fee + slippage
```

這與 Polymarket negative-risk 多結果機制相關，但程式不會自動假設所有 neg-risk event 都安全。若存在尚未命名的 placeholder、會變動定義的 Other，或漏掉任何結果，`exhaustive` 必須設為 `false`。

主要失效風險：結果集合不完整、augmented negative-risk placeholder、其中一腿無深度、解析爭議。

## 4. Option-Implied Probability

既有 `score` 指令比較模型機率與單一市場的費用後 ask。這不是結構性套利，需要承擔模型錯誤；下一階段應以完整期權鏈建立 strike-by-strike 分布，取代單一 flat volatility。

主要失效風險：財報跳空、厚尾、volatility smile、實際世界與風險中性機率差異、期權及 Polymarket 的時間／解析定義不一致。

## 暫不視為策略的訊號

- Maker rebate：應單獨列為獎勵收益，不能遮掩交易 alpha 為負。
- 畫面價格落後：必須用可成交 orderbook 與 timestamp 證明，不能只比 last trade。
- 高成交量／價格暴漲：只是觀察，不自動構成進場。
- 回測最好的參數：若不是 walk-forward out-of-sample，只是研究候選。

## 執行範例

```powershell
run.cmd scan-strategies --input examples\strategy_snapshot.example.json
```

要求 JSON 輸出：

```powershell
run.cmd scan-strategies --input examples\strategy_snapshot.example.json --json
```

提高安全邊際，例如要求每組至少 2¢：

```powershell
run.cmd scan-strategies --input examples\strategy_snapshot.example.json --min-profit-per-set 0.02
```

範例數字完全是合成資料，不是目前市場機會。
