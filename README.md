# Climate Auto

Automated weather data collection and report generation for the [TACOCO](https://www.tacoco.tw/) daily weather discussion.

## Features

- **Multi-source scraping** — collects weather charts from 7 sources (NCDR ECMWF/DWP/CorrDiff, CWA satellite/radar/marine/sounding, BOM MJO)
- **Report folder curation** — selects relevant charts and organizes them by report section
- **Markdown report generation** — renders structured daily weather reports via Jinja2 templates
- **LLM chart analysis** (optional) — uses Claude Agent SDK to generate synoptic analysis for each chart
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

# Generate report with LLM analysis
uv run climate-auto --report-only --analyze --date 2026-03-19
```

### CLI options

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Target date (defaults to today in Asia/Taipei) |
| `--config PATH` | Path to settings YAML (defaults to `config/settings.yaml`) |
| `--source NAME [NAME ...]` | Run specific sources only (e.g. `ncdr_ecmwf cwa_main`) |
| `--report-only` | Skip data collection, generate report from existing data |
| `--analyze` | Enable LLM chart analysis via Claude Agent SDK |

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
└── report/daily_report.md      # Generated report
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
