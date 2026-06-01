# 提升天氣圖判讀能力：深度研究報告

> 研究日期：2026-06-01
> 方法：fan-out 網路搜尋 → 抓取來源 → 對抗式驗證主張 → 綜合
> 範圍：5 個搜尋角度 → 抓取 24 個 primary 來源 → 抽取 103 個主張 → 驗證 25 個 → **23 通過、2 駁回**

---

## 研究問題

如何大幅提升「自動判讀氣象天氣圖」的能力，應用於目前以 **Claude Agent SDK vision（讀取 GIF/PNG 影像）** 判讀天氣圖的系統。

需判讀圖種：500/700/850hPa 高度場與等值線/填色圖、850hPa 水氣通量、雷達回波、衛星雲圖、MJO 相位圖、地面天氣圖、CWA Skew-T/Log-P 探空 GIF。資料源：CWA、NCDR、ECMWF。

評估三條改善路線：(1) 強化 LLM 視覺判讀、(2) 改用數值資料源、(3) 專用 CV / 微調模型。

---

## 核心結論（TL;DR）

最強的證據指向一個違反直覺的結論：**「強化讀圖」不是最佳投資，「不讀圖」才是。**

目前系統完全靠 Claude vision 讀 GIF/PNG，但有同儕審查的反面證據顯示這條路有結構性天花板。建議改採**混合架構**：

| 圖種 | 建議路線 | 理由 |
|------|---------|------|
| **Skew-T 探空** | 🟢 改數值計算 | 最高信心：MetPy 可完全取代讀圖 |
| **500/700/850hPa 高度場、水氣通量** | 🟢 改數值計算 | ECMWF/CWA 數值場直接取得 gh/t/u/v/q |
| **雷達回波、衛星雲圖、MJO、鋒面符號** | 🟡 維持讀圖 + 結構化提示 | 無對應數值場，但需加驗證機制 |

**優先級**：路線(2) ≫ 路線(1) ＞ 路線(3)。

---

## 路線 (2)：改用數值資料源 — 最高優先、信心最高

> 本路線 **10 個主張全數 3-0 通過**，全來自 Unidata / CWA / ECMWF 官方文件，是整份研究最扎實的部分。

### 2.1 Skew-T → MetPy 完全取代讀圖

目前用「兩階段讀圖（提取 JSON → 對照閾值）」處理 Skew-T，等於把**確定性計算**交給容易幻覺的視覺模型。改用數值計算：

```python
from siphon.simplewebservice.wyoming import WyomingUpperAir
import metpy.calc as mpcalc

# Siphon 回傳 DataFrame：pressure/height/temperature/dewpoint/u_wind/v_wind/pw
df = WyomingUpperAir.request_data(date, station_id)

# MetPy v1.7 確認可算（官方文件驗證）：
#   lcl / lfc / el / ccl                    → 關鍵層高度
#   cape_cin / surface_based_cape_cin
#   mixed_layer_cape_cin / most_unstable_cape_cin
#   parcel_profile                          → 抬升曲線
#   k_index / lifted_index
#   showalter_index / total_totals_index
```

目前 prompt 中那一大段 Skew-T 數值提取（站號、LCL、CCL、K指數、LI、SI、TT、SWEAT、風標讀法）**幾乎全可由 MetPy 精確算出**，省掉讀圖幻覺風險。這也直接完成 `PROGRESS.md`「下一步」列的「整合 CWA OpenData 計算 CAPE/CIN/PW」。

**注意事項**
- ⚠️ 被駁回主張（1-2）：`skew.shade_cape()` / `skew.shade_cin()` 只是**視覺化輔助，不是數值來源**。CAPE/CIN 數值必須用 `mpcalc.cape_cin` 系列。
- ⚠️ Siphon 預設抓 University of Wyoming 探空（不含台灣全部即時站）。**CWA 探空須透過 CWA OpenData 取得**，拿到 pressure/temp/dewpoint/wind 後一樣餵進 MetPy。

### 2.2 等高度場 / 水氣通量 → 數值預報場

- **ECMWF**：`ecmwf-opendata` 套件（官方），MARS 風格 `client.retrieve(date/time/step/param/target)` 下載 GRIB2。文件明列壓力層 `1000/925/850/700/500/300/250/200/50 hPa` 與參數 `gh`(位勢高度)/`t`/`u`/`v`/`q`/`r`/`vo`，**完整涵蓋 500/700/850hPa 高度場 + 水氣所需變數**。850hPa 水氣通量可由 `q × 風速` 自行計算。
- **CWA OpenData**：REST `/api/v1/rest/datastore/{datasetId}` 與 `/fileapi/v1/opendataapi/{datasetId}`（可下 GRIB/GIF/CAP）。**所有請求需 Authorization key**，缺 key 回 HTTP 401 `Authorization key is not correct.`。

⚠️ 目前程式碼**尚未接任何 API，全靠影像**。導入需新建一條資料管線（xarray 讀 GRIB → MetPy 計算 → 結構化數據）。一次建好即消除這幾類圖的讀圖誤差。

**來源**
- https://unidata.github.io/MetPy/latest/tutorials/upperair_soundings.html
- https://unidata.github.io/siphon/latest/examples/upperair/Wyoming_Request.html
- https://unidata.github.io/MetPy/latest/api/generated/metpy.calc.html
- https://opendata.cwa.gov.tw/dist/opendata-swagger.html
- https://github.com/ecmwf/ecmwf-opendata

---

## 路線 (1)：強化 LLM 視覺判讀 — 真實但有天花板

### 1.1 已知限制（風險最高，務必知道）

> 3-0 通過，來自 AMS 同儕審查期刊《Pixels and Predictions》(AIES-D-24-0029.1) + ClimateIQA。

- **GPT-4V 會幻覺天氣圖上不存在的特徵**：在無降水區捏造降水/雷雨、把冷鋒位置標錯、混淆 NAM 與 GFS 的 300hPa 風速極大值。
- **SciFIBench**（NeurIPS 2024）：最強模型（GPT-4o、Gemini-1.5-Pro）在科學圖表僅 **72–76% 準確度**，低於人類 78–86%，且**特別在細粒度視覺細節上出錯**——正是讀等值線數值、風標旗幟數這類任務。

→ 含義：目前讓 vision 直接讀數值、鋒面位置、Skew-T 讀數，**有顯著且已被證實的幻覺風險**，這解釋了「能力不夠強」的感受。

### 1.2 有效技術：結構化抽取提示（零成本、可立即套用）

> 皆不需微調，且有 3-0 證據。

- **DePlot 兩階段法**（圖→線性化表格→再推理），one-shot 勝過微調 SOTA 24%。**目前的兩階段架構方向正確。**
- **Charts-of-Thought**（抽取→驗證→分析再作答）：VLAT 基準三模型全面提升（GPT-4.5 +21.8%、Claude-3.7 +13.5%、Gemini-2.0 +9.4%）。
- **PlotExtract**：zero-shot CoT 序列，二軸圖 >90% precision。

實作：在 extraction prompt 中加入明確的「**先抽取 → 自我驗證 → 再下結論**」步驟，並要求模型標注不確定性。

### 1.3 最重要的跨領域結論

> 3-0 通過 (arXiv 2510.06782)：**模型架構的影響遠大於提示工程。**

1. **升級到最新世代模型**比狂調 prompt 更能提升讀圖準確度（本專案已用 Opus 4.8，贏在起跑點）。值得用實際圖種測 Opus 4.8 vs 舊基準。
2. **不要把冗長的圖表文字描述塞進 prompt** —— 在複雜圖上長描述「幾乎總是降低準確度」。

### 1.4 範圍限制（不可外推）

路線(1) 的所有正面數字（90%/90%、+13~22%）**只在標準二軸 scatter/line/bar 圖驗證過，從未在等值線圖、填色場、Skew-T、雷達/衛星圖上驗證**。被駁回主張（0-3）：「LLM 可作為人工抽取的可行替代」—— 這條紅線印證為何仍需 human-in-the-loop（現有 `--extract` → 人工改 → `--synthesize` 流程應保留）。

**來源**
- https://journals.ametsoc.org/view/journals/aies/4/1/AIES-D-24-0029.1.xml
- https://arxiv.org/html/2405.08807v1 (SciFIBench)
- https://arxiv.org/pdf/2508.04842 (Charts-of-Thought)
- https://arxiv.org/abs/2503.12326 (PlotExtract)
- https://arxiv.org/pdf/2212.10505 (DePlot)
- https://arxiv.org/html/2510.06782v1 (架構 vs 提示)

---

## 路線 (3)：專用 CV / 微調 — 次要補強

> 本研究**證據最薄弱**。

唯一通過的相關技術是 **DePlot**（chart-to-table，圖→表模態轉換）。研究問題中提到的 nowcasting 深度模型、Skew-T/等值線微調、風標(wind barb)與鋒面符號偵測 OCR，**在 23 個通過主張中沒有任何證據支持其成效**。DePlot/MatCha 主要訓練於 bar/line/scatter 資料圖，**對氣象等值線圖與 Skew-T 的適配未經證實**。

→ 建議：**現在不投入微調**。待路線(2)+(1) 完成仍有缺口（如雷達 nowcasting）再單獨評估。

---

## 行動建議（對應本專案）

### 第一優先（高 CP 值、信心最高）

1. **Skew-T 改 MetPy 計算**：CWA OpenData 探空數值 → Siphon DataFrame 格式 → `mpcalc` 算 CAPE/CIN/PW/LI/SI/TT/LCL/LFC/EL。把 `claude_analyzer.py::_extract_skewt` 的 Pass 1（讀圖提取 JSON）替換為數值計算，Pass 2 分析保留。
2. **等高度場 / 水氣通量改 ECMWF `ecmwf-opendata`**：下 GRIB2 → xarray/MetPy 計算 → 結構化數據進 synthesis。

### 第二優先（零成本、立即做）

3. 對**仍需讀圖的圖種**（雷達、衛星、MJO、鋒面符號）：保留 vision，但 prompt 改成 Charts-of-Thought 式「抽取→自我驗證→標注不確定性」，並**移除冗長背景描述**。
4. 用 Opus 4.8 對實際圖種**自建小型基準**（人工標準答案 vs 模型讀數），量化各圖種準確度，決定哪些非改數值不可。

### 保留

- Human-in-the-loop（`--extract` / `--synthesize`）—— 研究明確支持「LLM 不能完全取代人工抽取」。

---

## Caveats（重要）

- **時效性**：所有負面證據（幻覺、72–76%）來自 2024 年 GPT-4V/4o/Gemini-1.5 世代。新世代（Opus 4.8）可能明顯更好，**舊數字不可直接套用，請自建基準實測**。
- **2-1 分裂票**：「超越人類基線」與 SciFIBench 數字為 2-1 通過，人類基線樣本小、「超越人類」僅限特定無時限情境，信心略低。
- **工程成本**：路線(2) 需新建 API + GRIB 資料管線，CWA 需申請 Authorization key。
- **被駁回主張**：
  1. 「LLM 可作為人工抽取的可行替代」（0-3）
  2. 「`skew.shade_cape/cin` 可計算 CAPE/CIN」（1-2，實為視覺化輔助，應用 `mpcalc.cape_cin`）

---

## 資料源實測結論（2026-06，路線 2 落地驗證）

實際串接後確認探空數值來源（見 `src/climate_auto/report/sounding.py`）：

| 來源 | 台灣探空逐層數值 | 即時性 | 需金鑰 | 結論 |
|------|----------------|--------|--------|------|
| University of Wyoming (Siphon) | ❌ 無台灣站（46692 整月 0 筆） | — | 否 | 不可用 |
| **NOAA IGRA2 (Siphon)** | ✅ 台北 `TWM00058968`、花蓮 `TWM00059362` | ⚠️ NCEI 有延遲，記錄到 ~2023 | 否 | **歷史/回測可用** |
| CWA OpenData REST | ❌ 免費層無逐層探空剖面（`O-B0075-001` 是海面觀測） | — | 是 | 僅地面/海面觀測 |

- **CWA 金鑰仍有價值**：用於數值預報場（gh/t/u/v/q）與地面觀測，**不是**用於探空剖面。
- **同日操作型探空**：IGRA2 有延遲、CWA 免費層沒有 → 當日報告的探空仍須讀 GIF，或改用 CWA 受限的 HDPS 付費資料服務。
- MetPy 計算端與來源無關：實測 IGRA2 台北 2023-07-15 00Z → CAPE 407 / LCL 916hPa / K-index 29.6 / PW 58mm，全部數值化成功。

## 未解問題（後續釐清）

1. 最新世代模型（Opus 4.8、GPT-5、Gemini 2.5/3）在等值線/填色/Skew-T/雷達衛星圖的**實測**準確度？是否縮小與人類差距？需自建基準。
2. **同日操作型台灣探空的數值來源**：IGRA2 延遲、CWA OpenData 免費層無剖面 → 是否值得申請 CWA HDPS，或解析 CWA 自有探空文字產品？（CWA 數值預報場 gh/t/u/v/q 仍可用金鑰取得，待驗證涵蓋度）
3. 影像前處理（去背景紋路、提高對比、tiling 切塊、座標軸校正）對多模態 LLM 讀氣象圖的實際增益？**本研究無直接量化證據**，需自行實驗。
4. 針對 Skew-T / 等值線圖微調或專用 CV（風標、鋒面符號、chart-to-table 微調）的成本與增益，是否值得相較於直接走數值計算路線？

---

## 完整來源清單（24 個，皆 primary）

| # | URL | 角度 | 採用主張數 |
|---|-----|------|-----------|
| 1 | journals.ametsoc.org/.../AIES-D-24-0029.1.xml (Pixels and Predictions) | LLM vision | 5 |
| 2 | arxiv.org/abs/2503.12326 (PlotExtract) | LLM vision | 4 |
| 3 | arxiv.org/pdf/2212.10505 (DePlot) | LLM vision | 3 |
| 4 | arxiv.org/pdf/2508.04842 (Charts-of-Thought) | LLM vision | 5 |
| 5 | arxiv.org/html/2510.06782v1 (架構 vs 提示) | LLM vision | 5 |
| 6 | arxiv.org/html/2405.08807v1 (SciFIBench) | LLM vision | 5 |
| 7 | unidata.github.io/MetPy/.../upperair_soundings.html | 數值資料 | 4 |
| 8 | unidata.github.io/siphon/.../Wyoming_Request.html | 數值資料 | 4 |
| 9 | unidata.github.io/MetPy/.../metpy.calc.html | 數值資料 | 5 |
| 10 | opendata.cwa.gov.tw/dist/opendata-swagger.html | 數值資料 | 4 |
| 11 | github.com/ecmwf/ecmwf-opendata | 數值資料 | 5 |
| 12 | github.com/google-research/.../deplot | Chart CV | 5 |
| 13 | arxiv.org/pdf/2305.14761 | Chart CV | 4 |
| 14 | nature.com/articles/s41586-021-03854-z | Chart CV | 4 |
| 15 | ncbi.nlm.nih.gov/pmc/articles/PMC10356617 | Chart CV | 5 |
| 16 | arxiv.org/pdf/2508.12198 | Skew-T/等值線 | 5 |
| 17 | arxiv.org/pdf/2509.17481 | Skew-T/等值線 | 4 |
| 18 | github.com/google-research/.../deplot/README.md | Skew-T/等值線 | 5 |
| 19 | wcd.copernicus.org/articles/3/113/2022 | Skew-T/等值線 | 4 |
| 20 | arxiv.org/abs/2406.18521 | 影像 vs 數值 | 4 |
| 21 | arxiv.org/html/2409.19058v1 | 影像 vs 數值 | 4 |
| 22 | ecmwf.int/.../ecmwf-achieve-fully-open-data-status-2025 | 影像 vs 數值 | 5 |
| 23 | arxiv.org/pdf/2511.10075 | 影像 vs 數值 | 5 |
