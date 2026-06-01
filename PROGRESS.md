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

### Phase 2: 報告生成系統

**架構**
```
src/climate_auto/report/
├── __init__.py
├── models.py           # Pydantic 模型 (ChartImage, ReportSection, ReportContext)
├── discovery.py        # 掃描 report/ 目錄，自動建構結構化 context
├── analyzer.py         # BaseAnalyzer ABC + PlaceholderAnalyzer
├── generator.py        # discovery + extract/synthesize + Jinja2 渲染 + extractions.md 讀寫
├── claude_analyzer.py  # ClaudeAnalyzer 兩階段架構 (Phase 3)
├── docx_exporter.py    # Markdown → DOCX 轉換
├── references/
│   └── skew-t-guide.md # Skew-T 判讀參考
└── templates/
    └── daily_report.md.j2   # Jinja2 Markdown 模板
```

**功能**
- 自動掃描 `report/` 資料夾，依 section/subsection 結構建構 `ReportContext`
- Jinja2 模板渲染，含羅馬數字 section 編號
- `BaseAnalyzer` ABC 提供擴展點，預設 `PlaceholderAnalyzer` 顯示「待分析」
- 追蹤缺失圖片 pattern 並列於報告末尾
- 測試：11 個測試覆蓋 discovery、models、generator、template

### Phase 3: LLM 天氣圖分析（兩階段架構）

**ClaudeAnalyzer** — 使用 Claude Agent SDK 兩階段分析天氣圖

**Phase 1: Per-chart extraction（平行逐圖萃取）**
- 每張圖各跑一個獨立 agent（最多 5 concurrent），只做資訊提取不做診斷
- Skew-T 探空圖使用兩階段處理：Pass 1 提取結構化數據 JSON → Pass 2 對照閾值分析
- 結果存為 `extractions.md`（Markdown 格式，方便人工檢查/修改）

**Phase 2: Unified synthesis（統一天氣診斷）**
- 單一 agent 讀取所有萃取結果（含人工修改），跨圖交叉比對
- 產出四段式診斷：綜觀環境概述 → 當日回顧 → 未來展望 → 關鍵提醒

**Human-in-the-loop 流程**
- `--extract`：只跑 Phase 1，存 `extractions.md`
- 人工在編輯器中修改萃取結果
- `--synthesize`：讀取修改後的 `extractions.md`，跑 Phase 2 + 渲染報告
- `--analyze`：一次跑完兩階段（不中斷）

**其他特性**
- `AnalyzerConfig`：model、max_turns、budget_limit_usd、concurrency，可從 settings.yaml 設定
- Optional dependency：`claude-agent-sdk` 放在 `[project.optional-dependencies] llm`
- 錯誤處理：agent 失敗時 graceful degradation，回傳空字串不中斷報告
- 測試：17 個 claude_analyzer 測試 + 16 個 generator 測試

**實測結果 (2026-03-28)**
- Phase 1：17/17 張圖萃取完成 (~2.5 分鐘)
- Phase 2：統一天氣診斷完成 (~1 分鐘)
- 正確識別切斷低壓、副高偏南、華南鋒面水氣帶、Skew-T LI=-8.2 強不穩定訊號

### 執行方式

```bash
# 全部來源
uv run python -m climate_auto.main

# 指定來源
uv run python -m climate_auto.main --source ncdr_ecmwf cwa_upper

# 指定日期
uv run python -m climate_auto.main --date 2026-03-28

# 僅生成報告（不下載）
uv run python -m climate_auto.main --report-only --date 2026-03-28

# 一次跑完 LLM 分析（Phase 1 + Phase 2）
uv run python -m climate_auto.main --analyze --date 2026-03-28

# 分步驟：Phase 1 萃取 → 人工修改 → Phase 2 診斷
uv run python -m climate_auto.main --extract --date 2026-03-28
# 編輯 data/2026-03-28/report/extractions.md
uv run python -m climate_auto.main --synthesize --date 2026-03-28
```

---

### Phase 4: 數值資料路線（Route 2 — 以數值取代讀圖）

**動機**：深度研究（見 `docs/chart-recognition-research.md`）結論——純靠 vision 讀天氣圖有結構性幻覺風險；**能拿到數值就用數值計算**，影像辨識只留給無數值來源的圖。

**新增模組**
```
src/climate_auto/report/
├── sounding.py   # IGRA2 觀測探空 → MetPy 算 CAPE/CIN/PW/LI/K... (SoundingIndices)
├── forecast.py   # ECMWF open-data 預報場：500高度場特徵/700 RH/850水氣通量/預報探空/日雨量
├── cwa.py        # CWA OpenData 地面測站觀測 (O-A0001-001，需金鑰)
└── numeric.py    # 協調器 build_numeric_extractions() + 各格式化函式（失敗優雅降級）
```

**資料源實測結論（2026-06）**
| 來源 | 內容 | 即時性 | 金鑰 |
|------|------|--------|------|
| ECMWF open-data (`ecmwf-opendata`+cfgrib) | 500/700/850 場、預報探空、日雨量 tp | ✅ `date=-1` 最新 run | 否 |
| CWA OpenData O-A0001-001 | 地面測站即時觀測 | ✅ 當前時刻 | **是**（`.env` 的 `CWA_API_KEY`）|
| NOAA IGRA2 (siphon) | 觀測探空（台北=TWM00058968） | ⚠️ NCEI 延遲~2023 | 否 |
| U. Wyoming | （無台灣站） | — | — |
| CWA OpenData REST | **無**逐層探空剖面（O-B0075 是海面觀測） | — | — |

**整合**
- `--numeric` flag / `settings.yaml: numerical.enabled`；`NumericalConfig`（steps、sounding 點、`replace_chart_patterns`、`surface_stations`）
- 數值結果併入 `extractions.md`（可人工編輯），並 **對應到各圖段落**（`_remap_numeric_to_charts`：ECMWF500/700/850mf×f000/24/48 + dailyrn 第1/2天）
- `replace_chart_patterns` 跳過被取代的圖的 vision 讀取（預設 ECMWF500/700/850mf、dailyrn）
- CWA 金鑰：`.env`（gitignored）+ `.env.example`；pydantic-settings 讀取

**已數值化** 🟢：500高度場（副高中心/5880-5910線/脊線）、700 RH、850水氣通量、預報探空、日雨量、地面測站
**保留讀圖** 🔴：雷達/衛星（空間型態+免費格點受限）、集合雨量（離散度）、今日觀測探空（無免費即時）、MJO（BoM 403）

**真跡驗證**：ECMWF `date=-1` 實抓最新 run（18.6MB 全球場）跑通全管線；CWA 金鑰實抓地面站；`build_numeric_extractions` 一次產 14 數值區塊。驗證中修掉脊線誤抓熱帶邊緣的 bug（限制副熱帶帶 15-40N）。

**依賴**：`uv sync --extra numerical`（metpy/siphon/ecmwf-opendata/cfgrib/ecmwflibs/eccodes<2.41）
**測試**：sounding/forecast/cwa/numeric 整合共 +30 餘測試，全套 103 passed（裝/不裝 extra 皆過）

**已知小限制**
- CWA 站名子字串比對會誤收（如「南港」撈到南投「國姓南港」）→ 可改站號精確比對
- CWA 地面為當前 snapshot；海風進流時序需 CODiS（非單純 API）
- 脊線在副高遠離時會落在帶邊緣，屬「脊線不在此經度」訊號而非精確值

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

## 下一步

- **數值路線收尾**：CWA 站名改站號精確比對；評估雷達 QPESUMS 格點 / Himawari 衛星數值
- 強化「今日觀測探空」讀圖（唯一無數值來源）：專讀 Skew-T 文字框 + 標注待人工確認
- 對現有報告重跑 `--extract --numeric` 讓圖段落填上數值（Phase 4 修正對下次產生生效）
- 修復 BOM MJO（改抓 RMM 數值檔）/ CWA 高空圖等 scraper 問題
- 排程自動化 (cron / systemd timer)
