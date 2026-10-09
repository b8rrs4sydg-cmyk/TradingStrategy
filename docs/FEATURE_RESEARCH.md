# 指標數據研究：價格行為、諧波形態、技術指標、市場情緒

> 問題：加入更多資訊（價格行為、諧波交易、技術指標、市場情緒）能否找到**穩健、可交易**的預測力，
> 用來輔助多空策略？
>
> 結論：**480 個檢定中，沒有任何特徵能同時通過「多重檢定校正 + 跨時間 + 跨幣池重現 + 扣成本後可交易」。**
> 唯一穩定的效應（短期反轉 / 彩票效應 / 低波動異象）在排名上顯著，但做成多空組合會因為右尾暴漲而虧損。

## 1. 資料

| 類別 | 來源 | 內容 |
|---|---|---|
| 價格 | Binance USDT-M 永續 1d、現貨 1h（重取樣成 4h） | OHLCV |
| 資金費率 | Binance 永續 | 每 8h（2025 後部分 4h）結算費率 |
| 情緒 metrics | Binance `futures/um/daily/metrics`（每 5 分鐘，2021-12 起），彙整為日資料 | 持倉量 OI、大戶多空比（帳戶 / 持倉）、全市場多空比、主動買賣量比 |
| 基差 | Binance `premiumIndexKlines` 1d | 永續相對指數的溢價 |
| 恐懼貪婪 | alternative.me / CoinGlass / Glassnode 被網路政策封鎖 | 改以自建 proxy：30 日動能、−波動、資金費率、OI 變化、市場寬度的 z-score 平均 |

下載：`scripts/download_binance_metrics.py`（情緒），`scripts/download_binance_data.py --market futures`（價格/費率）。

## 2. 方法（事先固定，`research/feature_lab.py`）

| 集合 | 幣池 | 期間 |
|---|---|---|
| D（發現） | A∪B，100 個永續 | 2020-06 → 2023-12（情緒特徵 2021-12 起） |
| V1（時間） | A∪B | 2024-01 → 2026-09 |
| V2（幣池） | C，236 個永續 | 2020-06 → 2026-09 |

- 收盤 t 決策，t → t+k 的報酬（k = 1/3/7 日；4h 測試 k = 1/6/18 根），扣除等權市場報酬（只看幣種相對強弱）。
- **離散訊號**（K 線形態、諧波、價格行為事件）：事件研究，方向調整後的超額報酬，以日期為單位的 Newey-West t 值。
- **連續特徵**：前 20% 減後 20% 的**平均報酬價差**（實際可交易），同時列出排名 IC。
- **通過標準**：D 內 Benjamini-Hochberg FDR 10% 顯著，**且** V1 與 V2 同方向 p < 0.05。
- **諧波無前視**：X、A、B、C 必須是訊號出現前已「確認」的 ZigZag 轉折（價格反向超過門檻才算確認），
  在價格首次觸及 XABC 推算出的 D 點（PRZ）時進場；D 本身不需確認。

## 3. 結果總表

| 家族 | 特徵 | 檢定數 | D 顯著（BH） | 跨期跨幣池重現 |
|---|---|---|---|---|
| K 線形態（日線） | TA-Lib 全部 61 種 | 126 | 4 | **0** |
| 價格行為（日線） | 結構高低點、結構突破、20 日極值 pin bar、inside bar 突破、NR7 突破、距 50 日高低點、20 日區間位置、收盤位置 | 30 | 3 | **0** |
| 諧波形態（日線） | Gartley、Bat、Butterfly、Crab、任一；ZigZag 5% / 10% | 30 | 0 | **0** |
| 技術指標（日線） | RSI(2/14)、Stoch、CCI、Williams %R、MFI、ADX×方向、MACD、%B、ATR%、OBV 斜率、量能突增、1/7/30 日報酬、30 日偏態、30 日最大單日漲幅、距 EMA200 | 54 | 28 | **0** |
| K 線形態 + 諧波（4h） | 61 種 K 線 + 10 種諧波 | 144 | 9 | 3（見下） |
| 橫截面情緒 | 資金費率（1/7 日、z-score）、OI 變化、OI vs 價格、OI/成交量、大戶多空比、全市場多空比、聰明錢 vs 散戶、主動買賣比、基差 | 45 | 1 | **0** |
| 市場層級情緒（擇時） | 全市場資金費率、BTC 資金費率、總 OI 變化、多空比、主動買賣比、BTC 基差、市場寬度、30 日動能/波動、**恐懼貪婪 proxy**、極端值 | 72 | 0 | **0** |

### 3.1 4h 唯一重現的效應不可交易

長實體 K 線（marubozu / long line / closing marubozu）之後下一根 4h 平均反轉 **−4 ～ −11 bp**，
小於一次來回手續費（約 20 bp）。

### 3.2 排名顯著 ≠ 可交易（最重要的教訓）

第一輪以「排名 IC」為檢定時，41 個檢定通過重現（短期反轉、彩票效應 MAX、低波動異象、量能突增、OBV），
|t| 高達 10–16。但做成「做多後 20%、做空前 20%」的組合後，**扣成本前就已虧損**（綜合因子毛 Sharpe：
D −1.22、V1 0.15、V2 1.05）。原因：這些幣「多數時候」表現較差（排名輸），但偶爾暴漲 100%，
平均報酬由右尾主導 —— 放空它們等於賣彩票。因此主檢定改為平均報酬價差，結果 0 個重現。
（`research/results/factor_portfolios.csv`）

### 3.3 方向會翻轉的「特徵」

- 資金費率（橫截面）：2022–23 年資金費率高（多頭擁擠）的幣繼續強（t = +3.2），2024–26 年轉為落後（t = −3.4）。
- RSI / %B / CCI 等「超買」指標：D 中呈動能（超買續強），V2（小幣）呈反轉，V1 接近 0。

這類「某段時間顯著、換時間/幣池就反向」的結果，正是過擬合策略的來源。

### 3.4 市場擇時

恐懼貪婪 proxy 與各項全市場情緒對未來 1–7 日 BTC / 市場報酬皆無顯著預測力（|t| < 2.5，BH 後 0 個）。
唯一一致為正的是市場動能與寬度（站上 EMA50 的幣種比例），但這就是趨勢效應，已由趨勢策略涵蓋。

## 4. 對策略的意義

1. 在本研究的資料與期間內，**價格行為與諧波形態沒有可驗證的預測力**；K 線形態最多只有小於手續費的 4h 反轉。
2. 情緒數據（資金費率、OI、多空比、主動買賣比、基差、恐懼貪婪 proxy）**沒有穩定方向**，不適合作為進出場或擇時濾網。
3. 唯一經得起所有檢驗的仍是**結構性收益**（FundingCarry 的資金費率套利），以及溫和的趨勢效應。
4. 若未來要使用這些特徵，建議只作為**風險控管**（例如極端資金費率時降低槓桿），而非預測訊號，並以 2026-10 之後的前瞻 dry-run 驗證。

## 5. 重現

```bash
python scripts/download_binance_metrics.py --pairs-file configs/pairs_ab_futures.json
python research/feature_lab.py --families price harmonic indicators --out research/results/feature_lab_price_harm_ind.csv
python research/feature_lab.py --families sentiment --d-start 2021-12-01 --out research/results/feature_lab_sentiment_d_v1.csv
python -c "import sys; sys.path.insert(0,'research'); import feature_lab as f; f.intraday_report(); f.market_sentiment_report(); f.factor_report()"
```
