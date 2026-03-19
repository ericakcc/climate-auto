# TACOCO 天氣資料自動蒐集系統 — 進度記錄

## 已完成

### Phase 1: 資料蒐集自動化

**核心架構**
- Python 專案 (`uv` 管理), async/await 架構
- Pydantic 設定模型 + YAML 設定檔 (`config/settings.yaml`)
- 通用 async 下載器 (httpx, semaphore 並發控制, 指數退避重試)
- BaseScraper ABC → 各來源 scraper 實作
- manifest.json 追蹤下載狀態

**7 個資料來源 Scraper**

| Scraper | 來源 | 方式 | 狀態 |
|---------|------|------|------|
| `ncdr_ecmwf` | NCDR ECMWF Watch | 直接 URL 建構 | ✅ 27/27 |
| `ncdr_dwp` | NCDR DWP (AI 模式) | JSON config + URL 建構 | ✅ 18/27 (QV850 不可用) |
| `ncdr_corrdiff` | NCDR CorrDiff | JSON API + URL 建構 | ✅ 40/40 |
| `cwa_main` | CWA 氣象署 (雷達/衛星/雨量) | 已知 URL pattern | ⚠️ 4/6 (IR衛星/時間戳雷達 404) |
| `cwa_marine` | CWA NPD 海洋模式 | probe init time + URL | ✅ 25/50 (海流成功, SST URL 待修) |
| `cwa_upper` | CWA NPD 探空/地面/高空圖 | 直接 URL 建構 | ⚠️ 4/10 (探空+地面成功, 高空圖 404) |
| `bom_mjo` | BOM MJO 監測 | 需 Referer header | ❌ 0/5 (403/非圖片驗證問題) |

**報告資料夾篩選** (`report_selector.py`)
- 從全部下載中挑出報告需要的圖，按段落結構複製到 `report/` 資料夾
- 目前產出 21 張圖，對應報告的 3 個主要段落

### 報告資料夾結構

```
data/{YYYY-MM-DD}/
├── report/                          ← 報告用圖（篩選後）
│   ├── 1_review/                    ← 段落 1: 當日回顧
│   │   ├── analysis/                ← I. 分析場 (ECMWF 500/700/850/850mf f000)
│   │   ├── sounding/                ← II. 探空 (台北 Skew-T)
│   │   ├── precip/                  ← III. 降水熱區 (雷達/雨量 preview)
│   │   └── surface/                 ← IV. 地面天氣圖 (亞洲/台灣)
│   ├── 2_f24h/                      ← 段落 2: f24h 預報 (500/700/850/850mf f024 + 日雨量)
│   ├── 3_f48h/                      ← 段落 3: f48h 預報 (500/700/850/850mf f048 + 日雨量)
│   └── 4_context/mjo/               ← MJO 背景 (待修復)
├── ncdr_ecmwf/                      ← 原始下載（全部保留）
├── ncdr_dwp/
├── ncdr_corrdiff/
├── cwa_main/
├── cwa_marine/
├── cwa_upper/
├── bom_mjo/
└── manifest.json
```

### 執行方式

```bash
# 全部來源
uv run python -m climate_auto.main

# 指定來源
uv run python -m climate_auto.main --source ncdr_ecmwf cwa_upper

# 指定日期
uv run python -m climate_auto.main --date 2026-03-19
```

---

## 已知問題 (待修)

1. **BOM MJO scraper**: 需加 User-Agent header 或改用 Playwright，目前被 403 擋
2. **CWA 高空天氣圖**: URL 可能需要不同的 init time 或格式（目前只拿到探空 + 地面）
3. **CWA 雷達**: 只有 preview 縮圖，完整時間戳雷達圖需用 Playwright 攔截
4. **CWA Marine SST**: URL segment "T" 可能不正確，需確認
5. **NCDR DWP QV850**: AIFS 模式的 QV850 變數命名格式不同，下載失敗

---

## 報告中無法自動取得的資料

| 報告段落 | 所需資料 | 原因 |
|----------|---------|------|
| 1-II 探空 | GFS 預報探空（與觀測對比） | TACOCO 內部產出 |
| 1-III 降水 | 完整高解析雷達回波 | 需 Playwright 互動 (可改善) |
| 1-IV 地面觀測 | 測站時序圖（風向/溫度/雨量） | 需 CWA OpenData API 或 CODiS |
| 1-V 探空觀測 | 風廓線、CP 訊號 | TACOCO 特殊觀測儀器資料 |
| 1-VI TaiwanVVM | VVM 模擬結果 | 內部模擬系統 |
| 2-III / 3-IV SHAP | SHAP 預報分數圖 | TACOCO 內部 ML 系統 |
| 4 歷史個案 | TaiwanVVM 配對個案 | 內部資料庫 |

---

## 下一步: 報告生成規劃

### 目標
讀取 `report/` 資料夾中的圖片，結合天氣分析，產生 Markdown 格式的每日天氣討論報告。

### 報告生成架構

```
src/climate_auto/
└── report/
    ├── __init__.py
    ├── generator.py        # 主報告生成器
    ├── analyzer.py         # 天氣圖分析邏輯（讀取圖片→描述）
    └── templates/
        └── daily_report.md.j2   # Jinja2 Markdown 模板
```

### 生成流程

1. **讀取 manifest.json** — 確認今日有哪些圖成功下載
2. **圖片分析** — 對每張天氣圖提取關鍵資訊:
   - 500hPa: 太平洋高壓中心位置、5910/5940 線範圍、台灣上空流場方向
   - 850hPa: 風速風向、水氣傳送量
   - 850mf: 水氣通量分布
   - 探空: CAPE、CIN、PW（若能從圖中 OCR 或從 API 取數值）
   - 雷達: 降水範圍、強度
3. **模板渲染** — 用 Jinja2 填入分析結果和圖片路徑
4. **輸出 Markdown** — `data/{date}/report/daily_report.md`

### 分析方式選項

| 方式 | 優點 | 缺點 |
|------|------|------|
| **LLM 圖片分析** (Claude Vision) | 最智慧，能描述綜觀天氣特徵 | 需要 API key、成本 |
| **規則式描述** | 不需 API、穩定 | 無法真正「分析」圖片內容 |
| **搭配數值 API** | 可計算精確的 CAPE/CIN 等 | 需要 CWA OpenData API key |

### 建議實作順序

1. 先做 Jinja2 模板 — 定義報告結構、圖片插入位置
2. 實作基本生成器 — 圖片路徑嵌入 + 固定格式框架
3. （可選）整合 LLM 分析 — 用 Claude API 描述每張天氣圖的綜觀特徵
4. （可選）整合 CWA OpenData — 取得數值探空資料計算 CAPE/CIN/PW

### Markdown 報告範例結構

```markdown
# TACOCO 天氣討論會資料 — 2026-03-19

## 1. 當日回顧

### I. 分析場
![500hPa 分析場](1_review/analysis/ECMWF500_2026031812_f000.gif)
> [500hPa 天氣圖分析描述]

![850hPa 水氣通量](1_review/analysis/ECMWF850mf_2026031812_f000.gif)
> [850hPa 水氣通量分析描述]

### II. 探空
![台北探空](1_review/sounding/skewt_Taipei_26031900.gif)
> [探空分析描述: CAPE, CIN, PW, 風切]

### III. 降水熱區
![雷達回波](1_review/precip/radar_composite_preview.png)
> [雷達降水描述]

## 2. f24h 預報
...

## 3. f48h 預報
...
```

### 需要的額外依賴
- `jinja2` — 模板渲染
- （可選）`anthropic` — Claude API 圖片分析
