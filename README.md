# Climate Auto

Automated weather data collection and report generation for the [TACOCO](https://www.tacoco.tw/) daily weather discussion.

## Features

- **Multi-source scraping** — collects weather charts from 7 sources (NCDR ECMWF/DWP/CorrDiff, CWA satellite/radar/marine/sounding, BOM MJO)
- **Report folder curation** — selects relevant charts and organizes them by report section
- **Markdown report generation** — renders structured daily weather reports via Jinja2 templates
- **LLM chart analysis** (optional) — two-phase architecture: parallel per-chart extraction + unified weather diagnosis via Claude Agent SDK
- **DOCX export** — converts the Markdown report to Word format

## Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager
- [Playwright](https://playwright.dev/python/) browsers (for some scrapers)

## Installation

```bash
git clone https://github.com/ericakcc/climate-auto.git
cd climate-auto

# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium

# (Optional) Install LLM analysis support
uv sync --extra llm
```

## Usage

### Collect data and generate report

```bash
# Run all sources for today
uv run climate-auto

# Specify a date
uv run climate-auto --date 2026-03-19

# Run specific sources only
uv run climate-auto --source ncdr_ecmwf cwa_upper

# Generate report from existing data (skip download)
uv run climate-auto --report-only --date 2026-03-19

# Generate report with full LLM analysis (extract + synthesize in one go)
uv run climate-auto --report-only --analyze --date 2026-03-19
```

### Human-in-the-loop analysis

The analysis pipeline can be split into separate steps, allowing you to review and correct LLM extraction results before the final synthesis:

```bash
# Step 1: Run Phase 1 only — each chart gets an independent LLM extraction
uv run climate-auto --extract --date 2026-03-19
# → Produces data/2026-03-19/report/extractions.md

# Step 2: Review and edit extractions.md in your editor
#   Each chart is a ## section — fix any errors, add missing details

# Step 3: Run Phase 2 — reads your edited extractions, synthesizes diagnosis
uv run climate-auto --synthesize --date 2026-03-19
# → Produces daily_report.md and daily_report.docx using your corrections
```

### CLI options

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Target date (defaults to today in Asia/Taipei) |
| `--config PATH` | Path to settings YAML (defaults to `config/settings.yaml`) |
| `--source NAME [NAME ...]` | Run specific sources only (e.g. `ncdr_ecmwf cwa_main`) |
| `--report-only` | Skip data collection, generate report from existing data |
| `--analyze` | Full LLM pipeline: extract + synthesize in one run |
| `--extract` | Phase 1 only: extract chart info, save `extractions.md` |
| `--synthesize` | Phase 2 only: load `extractions.md`, synthesize and render report |

> `--analyze`, `--extract`, `--synthesize` are mutually exclusive. `--extract` and `--synthesize` imply `--report-only`.

### Configuration

Edit `config/settings.yaml` to toggle sources, adjust concurrency, or configure the LLM analyzer:

```yaml
# Enable/disable individual sources
sources:
  ncdr_ecmwf:
    enabled: true
  cwa_main:
    enabled: true

# LLM analyzer settings
analyzer:
  enabled: false
  model: "claude-sonnet-4-6"
  budget_limit_usd: 5.0
```

## Schedule daily runs

You can use **cron** (macOS/Linux) to run the collection automatically at a fixed time each day.

### 1. Find the full path to `uv`

```bash
which uv
# e.g. /Users/yourname/.local/bin/uv
```

### 2. Edit your crontab

```bash
crontab -e
```

### 3. Add a cron entry

```cron
# Run daily at 08:30 (Asia/Taipei)
30 8 * * * cd /path/to/climate-auto && /path/to/uv run climate-auto >> /path/to/climate-auto/cron.log 2>&1
```

Replace `/path/to/climate-auto` and `/path/to/uv` with your actual paths.

**Common schedules:**

| Schedule | Cron expression |
|----------|----------------|
| Every day at 06:00 | `0 6 * * *` |
| Every day at 08:30 | `30 8 * * *` |
| Every day at 18:00 | `0 18 * * *` |
| Weekdays only at 07:00 | `0 7 * * 1-5` |

### 4. Verify

```bash
crontab -l
```

> **Tip:** Make sure the cron environment has access to the required tools. If Playwright browsers fail in cron, add the full `PATH` to the crontab file:
> ```cron
> PATH=/usr/local/bin:/usr/bin:/bin:/Users/yourname/.local/bin
> ```

## Analysis architecture

When `--analyze` is enabled, the report generator uses a **two-phase LLM pipeline** to produce a unified weather diagnosis from all available charts.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Phase 1: Extraction                         │
│                     (parallel, per-chart agents)                   │
│                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       ┌──────────┐      │
│  │ 500hPa   │  │ 850hPa   │  │ Satellite │  ...  │ Skew-T   │      │
│  │ chart    │  │ chart    │  │ chart    │       │ chart    │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       └────┬─────┘      │
│       │              │              │                  │            │
│       ▼              ▼              ▼                  ▼            │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐        ┌─────────┐       │
│  │ Agent 1 │   │ Agent 2 │   │ Agent 3 │   ...  │ Agent N │       │
│  │ (Read)  │   │ (Read)  │   │ (Read)  │        │ 2-pass  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       └────┬─────┘      │
│       │              │              │                  │            │
│       ▼              ▼              ▼                  ▼            │
│   extracted       extracted      extracted         extracted        │
│    info 1          info 2         info 3           info N           │
└───────┬──────────────┬──────────────┬──────────────────┬────────────┘
        │              │              │                  │
        └──────────────┴──────┬───────┴──────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Phase 2: Synthesis                            │
│                   (single agent, all context)                      │
│                                                                    │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │              All extracted info (1..N)                      │   │
│   │  ┌───────┐ ┌───────┐ ┌───────┐         ┌───────┐          │   │
│   │  │info 1 │ │info 2 │ │info 3 │  . . .  │info N │          │   │
│   │  └───────┘ └───────┘ └───────┘         └───────┘          │   │
│   └─────────────────────────┬───────────────────────────────────┘   │
│                             │                                      │
│                             ▼                                      │
│                    ┌─────────────────┐                              │
│                    │ Synthesis Agent │                              │
│                    │  (no tools)     │                              │
│                    └────────┬────────┘                              │
│                             │                                      │
│                             ▼                                      │
│                  Unified Weather Diagnosis                          │
│                  ├─ 綜觀環境概述                                    │
│                  ├─ 當日天氣回顧                                    │
│                  ├─ 未來天氣展望                                    │
│                  └─ 關鍵提醒                                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Report Rendering                             │
│                                                                    │
│   daily_report.md                                                  │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  ## 天氣診斷分析          ← synthesis output                │   │
│   │  ## 1. 當日回顧                                             │   │
│   │     ![500hPa](...)       ← chart image                     │   │
│   │     extracted info 1     ← per-chart extraction             │   │
│   │     ![850hPa](...)                                          │   │
│   │     extracted info 2                                        │   │
│   │  ## 2. 24h 預報                                             │   │
│   │     ...                                                     │   │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Per-chart extraction (`--extract`)

Each chart image gets its own independent agent call (up to 5 concurrent). The agent uses the **Read** tool to view the image and outputs a concise, factual description of visible meteorological features — no diagnosis or forecast at this stage.

Results are saved to `extractions.md` — a human-readable Markdown file where each chart is a `##` section. You can review and edit this file before proceeding to Phase 2.

**Skew-T sounding diagrams** receive special two-pass treatment:
1. **Pass 1 (Data extraction)**: Extract structured numeric data (temperatures, indices, wind barbs) into JSON
2. **Pass 2 (Interpretation)**: Analyze the extracted data against reference thresholds to produce a meteorological summary

### Phase 2: Unified synthesis (`--synthesize`)

A single synthesis agent receives **all** extraction results (from `extractions.md`, including any human edits) — across every section (review, 24h, 48h, MJO context). It cross-references information between charts to produce a coherent weather diagnosis covering synoptic environment, current conditions, outlook, and key alerts.

### Why this architecture?

| Concern | Solution |
|---------|----------|
| Each chart needs careful, focused reading | Phase 1: dedicated agent per chart |
| LLM chart reading is imperfect | Human-in-the-loop editing via `extractions.md` |
| Weather diagnosis requires cross-chart reasoning | Phase 2: one agent sees everything |
| Charts are independent for extraction | Parallel agent calls (asyncio) |
| Skew-T diagrams have dense numeric data | Two-pass extraction → interpretation |
| Agent failures shouldn't break the report | Graceful degradation (shows "待分析") |

## Output structure

```
data/{YYYY-MM-DD}/
├── report/                     # Curated charts for the daily report
│   ├── 1_review/               # Section 1: Today's review
│   │   ├── analysis/           # ECMWF analysis fields (500/700/850 hPa)
│   │   ├── sounding/           # Skew-T diagrams
│   │   ├── precip/             # Radar / rainfall
│   │   └── surface/            # Surface weather charts
│   ├── 2_f24h/                 # Section 2: +24h forecast
│   ├── 3_f48h/                 # Section 3: +48h forecast
│   └── 4_context/mjo/          # MJO context
├── ncdr_ecmwf/                 # Raw downloads (all sources)
├── cwa_main/
├── ...
├── manifest.json               # Download status tracking
└── report/
    ├── daily_report.md         # Generated report
    ├── daily_report.docx       # DOCX export
    └── extractions.md          # Per-chart LLM extractions (editable)
```

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check . --fix && uv run ruff format .
```

## License

MIT
