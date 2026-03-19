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

### Phase 2: 報告生成系統

**架構**
```
src/climate_auto/report/
├── __init__.py
├── models.py           # Pydantic 模型 (ChartImage, ReportSection, ReportContext)
├── discovery.py        # 掃描 report/ 目錄，自動建構結構化 context
├── analyzer.py         # BaseAnalyzer ABC + PlaceholderAnalyzer
├── generator.py        # discovery + analyzer + Jinja2 渲染
├── claude_analyzer.py  # ClaudeAnalyzer (Phase 3)
└── templates/
    └── daily_report.md.j2   # Jinja2 Markdown 模板
```

**功能**
- 自動掃描 `report/` 資料夾，依 section/subsection 結構建構 `ReportContext`
- Jinja2 模板渲染，含羅馬數字 section 編號
- `BaseAnalyzer` ABC 提供擴展點，預設 `PlaceholderAnalyzer` 顯示「待分析」
- 追蹤缺失圖片 pattern 並列於報告末尾
- 測試：11 個測試覆蓋 discovery、models、generator、template

### Phase 3: LLM 天氣圖分析

**ClaudeAnalyzer** — 使用 Claude Agent SDK 批次分析天氣圖

- **批次策略**：按 section 分組（~4 次 agent 呼叫），同 section 內的圖互相參照
- **System prompt**：氣象分析師角色，各圖類分析要點（500hPa/850hPa/探空/雷達/衛星/MJO）
- Agent 使用 `Read` 工具讀取圖片，回傳 JSON `{path: analysis_text}`
- `AnalyzerConfig`：model、max_turns、budget_limit_usd，可從 settings.yaml 設定
- Optional dependency：`claude-agent-sdk` 放在 `[project.optional-dependencies] llm`
- 錯誤處理：agent 失敗時 graceful degradation，log 後回傳空 dict
- CLI：`--analyze` flag 啟用 LLM 分析
- 測試：12 個測試（prompt 建構、JSON 解析、mock agent 呼叫、錯誤處理）

**實測結果 (2026-03-19)**
- 當日回顧：9/9 張分析完成 (~1.5 分鐘)
- f24h 預報：6/6 張分析完成 (~1 分鐘)
- f48h 預報：6/6 張分析完成 (~1 分鐘)
- 總共 21 張圖全部成功產生繁體中文綜觀分析

### 執行方式

```bash
# 全部來源
uv run python -m climate_auto.main

# 指定來源
uv run python -m climate_auto.main --source ncdr_ecmwf cwa_upper

# 指定日期
uv run python -m climate_auto.main --date 2026-03-19

# 僅生成報告（不下載）
uv run python -m climate_auto.main --report-only --date 2026-03-19

# 生成報告 + LLM 分析
uv run python -m climate_auto.main --report-only --analyze --date 2026-03-19
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

## 下一步

- （可選）整合 CWA OpenData — 取得數值探空資料計算 CAPE/CIN/PW
- 修復 BOM MJO / CWA 高空圖等 scraper 問題
- 排程自動化 (cron / systemd timer)
