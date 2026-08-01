# fsi-skills Trading Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

**Language**: **English** · [简体中文](README.zh-CN.md)

Multi-strategy quantitative signals + Claude CLI narrative analysis + moomoo paper-trading automation.

Targets leveraged and single-name US equities (**TQQQ / SOXL / DRAM / MULL / GLD / TSLA / NVDA / MSFT / AAPL / GOOGL / KLAC / AMAT**). Daily-candle main signal + 15-min intraday assist, blended with evolved-rule confluence, Trump Truth Social parsed via CLI, gold macro factors, and options gamma monitoring. Actionable decisions flow through `paper_trader` into a moomoo **SIMULATE** account (never live).

## Dashboard Preview

WebUI (`webui.bat` → http://127.0.0.1:8080) — zero-dependency `http.server` + single-page dashboard covering NAV, sector regimes, Trump sentiment, gold/oil macro, event calendar, and per-ticker cards with signals + option walls + Claude analysis.

![Dashboard overview](docs/dashboard-full.png)

### Per-ticker card contents

1. **Bull/bear confluence bar** + recommended action + confidence
2. **Mini options wall SVG** — call/put volume distribution by strike + spot dashed line + Max Pain
3. **Attack/defense table** — strike / premium / OI (open interest) / notional exposure
4. **Squeeze risk badge** — `gamma_up` / `put_break` / `max_pain_gravity`
5. **C/P ratio + beginner-friendly interpretation** — when Put OI >> Call OI, distinguish ATM panic vs OTM insurance
6. **🤖 Claude live analysis** — 3-line structured (综合/攻防/警示) for all 10+ tickers, cached by data hash
7. **🔗 Supply chain** — Claude-generated upstream/downstream/peers with confidence marks; optional FMP peers cross-verification; lazy-loaded, 14-day cache
8. **📊 4-year fundamentals** (or **8 quarters** via toggle) — CROIC / Piotroski F / financial debt / cash conversion cycle from yfinance; 30/15-day cache

### 🕸 Supply-chain spider web (Bloomberg SPLC style)

Each card has `🕸 1-hop / 🕸 2-hop` buttons in the supply-chain section:
- **1-hop**: direct neighbors (fast, uses local cache)
- **2-hop**: BFS expansion (NVDA depth=2 = 90 nodes / 233 edges — downstream's downstream + upstream's upstream)
- **Edge colors**: 🔴 supply / 🟢 customer / 🟡 peer; width ∝ weight; solid = high confidence, dashed = medium/low
- **Edge hover shows reason** (example: `TSM → NVDA · supply · exclusive foundry for H100/H200/B100/B200 leading-edge nodes (4N/3nm)`)
- FMP-verified peers get a green ring
- Drag nodes to rearrange, Esc / click backdrop to close
- Direct URL: `?graph=NVDA&depth=2`

**1-hop example (NVDA)**: ![NVDA direct neighbors](docs/supply-chain-nvda-graph.png)

**2-hop example (NVDA deep)**: ![NVDA 2-hop supply chain](docs/supply-chain-nvda-depth2.png)

### 📊 4-year fundamentals (StatementDog style, free)

Each card exposes 4 free metrics from yfinance (30-day cache, or 15-day for quarterly):

- **CROIC (Cash Return on Invested Capital)** — FCF ÷ Invested Capital; >10% healthy, >20% cash machine
- **Piotroski F-Score** — 9-point financial improvement scorecard; 7-9 strong, 4-6 normal, 0-3 warning
- **Financial debt** — ST + LT debt in $M; rising trend = leverage buildup
- **Cash conversion cycle** — DIO + DSO - DPO in days; <30 excellent, >120 inventory pressure
- Each cell: latest value + up/down arrow + 4-period sparkline + hover explanation
- ETFs mapped to a representative single stock (TQQQ/SOXL → NVDA, DRAM/MULL → MU); GLD skipped (commodity)
- **Also fed into Claude analysis** — Claude proactively flags CROIC crashes / debt surges / Piotroski < 4

Toggle button `📆 4 years · switch to quarterly` / `📅 8 quarters · switch to yearly` per ticker, choice remembered in localStorage. Quarterly mode uses **year-over-year same-quarter comparison** for Piotroski (avoids seasonality).

### 🔥 Large-order highlight + earnings integration

- Option wall OI ≥ 5K contracts or notional ≥ $30M → attack/defense table shows 🔥, mini SVG bar gets brighter fill + top 🟠 dot
- "Unusual volume" (today's vol > 0.5 × OI) → hover shows ⚡
- Each card gets an **📅 earnings badge** on top (related earnings stock + T-N days + implied move ± IM%)
  - MULL/DRAM ← MU earnings; SOXL/TQQQ ← NVDA earnings
  - T ≤ 3 days 🚨 red / T ≤ 14 days ⚠ yellow / T ≤ 60 days 📅 gray
  - Option expiries crossing earnings tagged "spans earnings" (premium expensive but hedge valid)

### Top row

📅 **Upcoming events calendar** (next 45 days) — FOMC / CPI / NFP / NVDA earnings with beginner hints on market impact.

**Expand-all view**: `?expand=all` (for screenshots / holistic review) — [see dashboard-full-expanded.png](docs/dashboard-full-expanded.png)

## Key features

- **Regime as single source** — computed once at pre-open → all modules read the same source; no independent detection allowed
- **Backtest gate** — any signal or decision change must pass `_backtest_modules_accuracy.py` etc. without hit-rate regression before merging
- **News through CLI** — RSS / Truth Social are NOT keyword-matched directly; they're first parsed by local Claude CLI into structured JSON, then consumed by rules
- **Multi-module accuracy** — 250-day historical backtest, quant (evolved rules) 20d hit-rate 70-78% on SOXL/MULL
- **Witching-day detection** — identifies quarterly 3/6/9/12 third-Friday, plus GEX proxy + related-earnings alerts
- **Claude AI price targets** — Claude outputs structured JSON (entry_ref / stop_ref), `paper_trader` auto-places limit + SELL STOP orders

## Ticker universe ([`agents/config.py`](agents/config.py))

| Ticker | Type | Leverage | Notes |
|---|---|---|---|
| TQQQ | Nasdaq-100 leveraged ETF | 3x | Primary tech long |
| SOXL | Semiconductor leveraged ETF | 3x | Semi long |
| DRAM | Roundhill Memory ETF | 1x | Memory sector (Micron + SK Hynix + Samsung exposure) |
| MULL | Micron leveraged ETF | 2x | DRAM/NAND single-name leverage |
| GLD | Gold ETF | 1x | Hedge / macro offset |
| NVDA / MSFT / AAPL | WATCH_ONLY | 1x | Bellwethers; signals only, no orders |
| TSLA / GOOGL / KLAC / AMAT | Satellite | 1x | Selected daily by universe picker |

## Quick start

```cmd
:: 1. Install deps (first-time)
cd f:\fsi-skills\agents
setup.bat

:: 2. Configure secrets (first-time)
copy secrets.example.json secrets.local.json
:: Edit secrets.local.json to fill FRED_API_KEY and MOOMOO_ACC_ID
:: ⚠ secrets.local.json is in .gitignore — NEVER commit; see SECURITY.md

:: 3. Enable pre-commit safety hook (first-time)
git config core.hooksPath .githooks
:: Blocks accidental commits of sk-... / ghp_... / AKIA... secret patterns

:: 4. Start moomoo OpenD (keep running)

:: 5. Pick a run mode
run.bat        :: Long-running orchestrator (5min scheduler checks + 5 ET windows)
snap.bat       :: One-shot daily snapshot (regime + Trump + signals + options + Claude)
tools.bat      :: Tools menu (trader status / regime / picks / flatten etc.)
backtest.bat   :: Backtest menu (regime / news / trump / modules / V-bounce)
trump.bat      :: Trump signal alone
weekly.bat     :: Weekend refresh of module_accuracy.md
webui.bat      :: WebUI dashboard at http://127.0.0.1:8080
```

## Config files

| File | Purpose | In git |
|---|---|---|
| [`agents/config.py`](agents/config.py) | Public config: TICKERS / leverage factors / windows / thresholds | ✅ |
| [`agents/secrets.example.json`](agents/secrets.example.json) | Secrets template (placeholders) | ✅ |
| `agents/secrets.local.json` | **Real** FRED_API_KEY / MOOMOO_ACC_ID etc. | ❌ (.gitignore) |
| `.claude/settings.local.json` | Claude Code permission whitelist | ✅ |
| [`SECURITY.md`](SECURITY.md) | Secrets management / pre-commit hook / vulnerability reporting | ✅ |
| [`.githooks/pre-commit`](.githooks/pre-commit) | Blocks accidental API-key commits (enable with `git config core.hooksPath .githooks`) | ✅ |

## Entry-point scripts

- [`run.bat`](agents/run.bat) — orchestrator loop, 5 ET windows (08:30 / 09:20 / 10:00 / 12:00 / 15:45) auto-trigger
- [`snap.bat`](agents/snap.bat) — one-shot snapshot: regime / Trump / witching / signals / decisions / event calendar / Claude narrative
- [`tools.bat`](agents/tools.bat) → [`tools_menu.py`](agents/tools_menu.py) — interactive menu
- [`backtest.bat`](agents/backtest.bat) → [`backtest_menu.py`](agents/backtest_menu.py) — backtest menu
- [`trump.bat`](agents/trump.bat) — Trump signal banner only
- [`weekly.bat`](agents/weekly.bat) — one-click refresh of module_accuracy.md (weekend)

## System architecture (data flow)

```
                        ┌─── moomoo OpenD (real-time quote + paper orders)
                        │
   FRED ────┐           │      ┌─── Trump signal (CNN truth_archive)
            ├── data_feeds + market_watch ──┤
   yfinance ┘           │      └─── Options chain (yfinance options)
                        │
                        ↓
            [Block 1-11 signal-collection layer]
                        ↓
   regime_today.py (single source, computed pre-open)
                        ↓
   ┌──────────────────────────────────────┐
   │ decision_agent._etf_rules /          │
   │ _gold_rules → action + conf + stop_ref│
   │ (V-bounce / Trump override / event-tier)│
   └──────────────────────────────────────┘
                        ↓
   claude_gate.py (pre-trade approval; run.bat defaults fail-closed)
                        ↓
   ┌──────────────────────────────────────┐
   │ paper_trader.execute() 7-stage chain:│
   │  ① window gating → ② discipline mgmt │
   │  ③ dedup → ④ action routing          │
   │  ⑤ vol-target sizing → ⑥ limit build │
   │  ⑦ moomoo SDK submission             │
   └──────────────────────────────────────┘
                        ↓
                  moomoo SIMULATE account

   ＊ Claude CLI narrative/report layer (out-of-band, separate from the gate):
     After run_cycle completes, invokes Claude CLI to summarize
     all 11 blocks into a 700-1000 word plain-language report
     + structured JSON price targets. Next cycle, paper_trader
     reads the JSON to adjust limit / stop-loss levels.
```

## Signal modules (Block numbers referenced by Claude prompts)

| # | Module | File |
|---|---|---|
| ① Base report | [`report_generator.py`](agents/report_generator.py) |
| ② Rule evolution | [`strategy_evolver.py`](agents/strategy_evolver.py) |
| ③ Win-rate leaderboard | [`strategy_engine.py`](agents/strategy_engine.py) `generate_pattern_leaderboard` |
| ④ Signal live (confluence) | [`confluence.py`](agents/confluence.py) + [`market_watch.py`](agents/market_watch.py) |
| ⑤ Event calendar | [`events_watch.py`](agents/events_watch.py) |
| ⑥ Trump signal | [`trump_signal.py`](agents/trump_signal.py) |
| ⑦ Options wall | [`option_walls.py`](agents/option_walls.py) |
| ⑧ MACD + ADX | [`market_watch.py`](agents/market_watch.py) |
| ⑨ SOX PCA | [`pca_sox.py`](agents/pca_sox.py) |
| ⑩ Gold macro | [`gold_macro.py`](agents/gold_macro.py) |
| ⑪ Options risk (witching / GEX / related earnings) | [`option_walls.py`](agents/option_walls.py) `get_options_risk_signal` |

## Decision modules

| File | Role |
|---|---|
| [`agents/decision_agent.py`](agents/decision_agent.py) | Rule engine: `_etf_rules` / `_gold_rules` → action + conf + stop_ref |
| [`agents/regime_today.py`](agents/regime_today.py) | Regime single source (writes `regime_state.json` at pre-open) |
| [`agents/paper_trader.py`](agents/paper_trader.py) | moomoo SIMULATE ordering + position sizing + TP/SL |
| [`agents/quant_signal.py`](agents/quant_signal.py) | Evolved-rule confluence scoring |
| [`agents/ai_prompt.py`](agents/ai_prompt.py) | Claude CLI invocation + prompt templates + structured JSON parsing |
| [`agents/claude_gate.py`](agents/claude_gate.py) | Claude second-opinion gate (pre-trade approval) |

## Backtests

| Script | Validates |
|---|---|
| [`_backtest_modules_accuracy.py`](agents/_backtest_modules_accuracy.py) | Per-module × 1d/5d/10d/20d hit-rate (baseline regression) |
| [`_backtest_regime_fix.py`](agents/_backtest_regime_fix.py) | Decision stability across regime-source refactors |
| [`_backtest_news_pipeline.py`](agents/_backtest_news_pipeline.py) | CLI-parsed vs keyword-match (event-landing accuracy) |
| [`_backtest_trump_signal.py`](agents/_backtest_trump_signal.py) | Trump signal direction hit-rate (vs trump-code baseline) |
| [`_backtest_v_bounce.py`](agents/_backtest_v_bounce.py) | V-reversal chase-buy (leveraged ETFs 5d/10d/20d) |
| [`_backtest_gold_macro.py`](agents/_backtest_gold_macro.py) | Gold macro signal injection backtest |
| [`backtest_engine.py`](agents/backtest_engine.py) | Lite / Mid / Heavy full-system backtest tiers |

Regression tests (run from `agents/`): `python -m unittest discover -s tests -v`

Output report: `agents/signals/module_accuracy.md` (actual file is gitignored).

## Backup

- Before major changes: `python _make_backup.py` → `backups/agents_backup_<timestamp>_with_AB.zip`
- Milestones: `git tag v0.x.x && git push --tags`

## Known limitations

- **Paper trading only** — moomoo SIMULATE account, never live
- DRAM ETF listed < 60 days when added; evolved rules untrained; only main decision flow applies
- Claude CLI calls take 30-60s each, ≤30/day per user (quota manageable)
- **No paid API keys** — everything uses free FRED + yfinance + Claude Code subscription CLI

## Changelog

Each tag's main changes. Full diffs at [GitHub Releases](https://github.com/zzwjlwwdtg/fsi-skills-agents/releases).

### [v0.3.0](https://github.com/zzwjlwwdtg/fsi-skills-agents/releases/tag/v0.3.0) — 2026-07-28

**Major release**: 15 system-capability upgrades + push notifications + WebUI + open-source ready

**New features (15-item checklist landed)**:

- **P1 observability**
  - [`docs/EDGE.md`](docs/EDGE.md) explicitly lists real edge / fake edge / non-edge
  - [`_benchmark_report.py`](agents/_benchmark_report.py) NAV vs SPY/QQQ weekly (Sharpe/Max DD/α)
  - [`_trade_postmortem.py`](agents/_trade_postmortem.py) BUY/SELL pairing + P&L attribution
- **P2/P3 risk + sizing**
  - Correlation-group position caps (`tech_3x` 50% / `tech_2x` 30% / `single_high_beta` 30% etc., 6 groups)
  - Probe positions (low conf = 30% size) + pyramid adds (≤3 layers)
  - Half-Kelly size tweak (min 10 trades, cap [0.5, 1.5])
- **P4 decision/timing**
  - Sitting minimum-hold (SELL rejected if position < 3 days)
  - Loss-streak pause (3 consecutive losses → 24h no new positions)
  - HMM meta-regime one-way tightening (volatile/crisis/bear → bull_thresh +1, never loosen)
  - **Inverse ETF OOS rejection**: SQQQ/SOXS triggers had 5d up-rate only 26.5% (-33pp inverse indicator) → not deployed
- **P5 infrastructure**
  - `TRADER_LIVE_FRACTION` env var for gradual rollout (0.0-1.0)
  - [`_data_source_health.py`](agents/_data_source_health.py) data-source health check
- **Push notifications** [`notifications.py`](agents/notifications.py)
  - Discord webhook + Telegram bot (either or both)
  - 5-min dedup to prevent spam
  - Hooks: trade filled / crisis regime / watchdog restart / loss-streak pause
- **WebUI Dashboard** (zero-dep Python `http.server`)
  - [`webui.py`](agents/webui.py) 8 API endpoints (health/nav/positions/trades/log/hmm/signals/banners/ai_analysis)
  - [`dashboard.html`](agents/dashboard.html) single-page SPA + Chart.js + marked.js
  - NAV time-series + per-ticker signal cards (bull/bear confluence bar + regime badge) + HMM + Trump/Gold Macro cards + Claude analysis markdown render
  - 30s auto-refresh, bound to 127.0.0.1 only
  - Launch via [`webui.bat`](agents/webui.bat)
- **Watchdog + auto-restart** [`_watchdog.py`](agents/_watchdog.py)
  - Windows Task Scheduler checks orchestrator PID every 30 min
  - Auto-clears stale lock + silently restarts via `pythonw` (no window)
- **Open source ready**
  - MIT [`LICENSE`](LICENSE)
  - [`SECURITY.md`](SECURITY.md) secrets management
  - [`.githooks/pre-commit`](.githooks/pre-commit) blocks sk-/ghp_/AKIA etc. patterns
  - `.gitignore` hardened for `.env.*` / credentials / pem / id_rsa
- **Backtest scientization**
  - OOS validation as hard gate (14 OOS samples ≥ 30, 5d edge ≥ 8pp before deployment)
  - `_backtest_overheated_oos.py` / `_backtest_divergence.py` / `_backtest_trend_capture.py` / `_backtest_inverse_etf.py` full OOS validation scripts

**Key bug fixes**:

- **conf_min not scaled to /5 range** — under TECHNICAL_ONLY all signals silently skipped (fix `conf_min * scale/10`)
- **A+B / C plan rollback** — OOS proved CAUTION layer + overheated multi-day accumulation + top divergence are all inverse indicators (-14 to -17pp)
- **.bat Chinese REM misparsed under Japanese CP932** — enforce ASCII-only
- **LOG_PATH not switching at midnight** — added `_DailyLogHandler` for auto file switch

### [v0.2.1](https://github.com/zzwjlwwdtg/fsi-skills-agents/releases/tag/v0.2.1) — 2026-06-23

Earnings-week implied-move guard + midnight log switch

- **Added** [`option_walls.get_earnings_implied_move(stock)`](agents/option_walls.py): reads ATM straddle of earnings week to compute implied ±% (with ATM±1 smoothing) + C/P vol ratio + IV
- **Added** [`decision_agent._apply_earnings_guard()`](agents/decision_agent.py): tiered dampening by `leveraged_im = im × ETF leverage`
  - `> 20%` → force HOLD; `12-20%` → conf-3 (<6 → HOLD); `6-12%` → conf-2; T-1/T-0 always HOLD
- orchestrator injects `events.earnings_implied_move` per cycle (MU/NVDA related stocks within 30 days)
- Backtest ([`_backtest_earnings_implied_move.py`](agents/_backtest_earnings_implied_move.py)): MU 5-year 20 earnings, MULL empirical beta=2.08x (validated); MULL |move|>20% probability 25%; 2024-12-18 MULL single-day -32.74%
- Live: MU 6-25 earnings, MULL/DRAM `WATCH_BUY` auto-downgraded to HOLD

### [v0.2.0](https://github.com/zzwjlwwdtg/fsi-skills-agents/releases/tag/v0.2.0) — 2026-06-22

JP Social Reco integration + Block ⑫

- Integrated [`jp_social_reco`](agents/jp_social_reco/) subsystem into main framework (snap.bat / orchestrator / Claude prompt)
- Added `get_jp_social_with_backtest()`: signals + creator historical hit-rate + per-ticker per-horizon backtest verification
- Claude prompt gained **block ⑫** JP influencer picks, ≥★★★ tickers must appear in morning watchlist
- Star algorithm (mentions × creator count): ★★★★★ / ★★★★ / ★★★ / ★★ / ★

### [v0.1.0](https://github.com/zzwjlwwdtg/fsi-skills-agents/releases/tag/v0.1.0) — 2026-06-21

Initial release

- Regime single source (pre-open compute + -5% crisis override)
- 5 tickers: TQQQ / SOXL / DRAM / MULL / GLD
- Evolved-rule confluence + 250-day module accuracy backtest (quant 20d 70-78%)
- Trump signal CLI parsing (80% hit-rate vs trump-code baseline)
- Gold macro (real_rate + DXY + WALCL + FOMC + oil + 10Y)
- Options monitoring (Call/Put Wall + Max Pain + GEX + witching + related earnings)
- V-bounce chase-buy (1x WATCH_BUY / leveraged LONG_HOLD split)
- Event tiering (CPI/FOMC/NFP critical, PCE/PPI/Retail high, earnings moderate)
- Claude CLI narrative + structured JSON price targets (Plan A)
- decision_agent auto-computes stop_ref (Plan B) → paper_trader submits real SELL STOP
- 7-stage vol-target order chain
- Secrets isolated to agents/secrets.local.json (gitignore)

## License

MIT — see [LICENSE](LICENSE). Free to use, modify, and distribute; **no warranty**, use at your own risk. Paper-trading only.

## Related projects

- [`F:\trump-code`](F:\trump-code) — Trump Truth Social tweets → US equity signal backtest; this system's `trump_signal` module draws on its key learnings

## Maintenance

Main memory files live at `C:\Users\masa\.claude\projects\f--fsi-skills\memory\`:
- `feedback_trading_style.md` — user preferences (chase strong trends / 3-tier indicators / no markdown in CMD / etc.)
- `feedback_regime_first.md` — regime single-source principle
- `feedback_backtest_gate.md` — any change requires backtest validation
- `feedback_news_pipeline.md` — news must be CLI-parsed into structured JSON before use
