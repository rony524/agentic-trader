# 02 — Data Sources

All sources are **free and public**. Check each provider's terms of service and rate limits before building the
ingestor for it. Every record stores `source`, `source_url`, `published_at` (when the world could know it),
`retrieved_at` (when we fetched it) and `raw_hash`.

## Market data
| Source | What | Cadence | Access |
|--------|------|---------|--------|
| Alpaca Market Data | Daily/minute bars for the universe | Daily after close + intraday for execution | Free paper account keys, IEX feed |
| yfinance (fallback) | Long daily history for backtests (pre-Alpaca coverage) | On demand | No key. Unofficial, so cache aggressively |
| Alpaca News API | Headlines/summaries tagged by ticker | Every 30 min | Same keys. Confirm what the free tier includes |

## Chips
| Source | Signal use | Cadence |
|--------|-----------|---------|
| SEC EDGAR (8-K, 10-Q, 10-K) for hyperscalers + semis | Capex guidance changes, memory cost mentions, supply commentary | Daily. EDGAR requires a `User-Agent` with contact email and allows ≤10 req/s |
| TSMC monthly revenue (investor relations) | Foundry demand nowcast | Monthly (~10th) |
| Korea trade statistics (semiconductor exports) | Memory demand/price proxy. One of the earliest monthly prints | Monthly (1st of the month) |
| SIA / WSTS monthly global semiconductor sales | Industry cycle | Monthly |
| Company IR press releases (MU, SK Hynix, Samsung, NVDA, AMZN, MSFT, GOOGL, META) | Event detection | RSS/scrape daily |

## Energy
| Source | Signal use | Cadence |
|--------|-----------|---------|
| EIA Open Data API v2 | Electricity retail prices, natural gas (Henry Hub), power generation, storage | Weekly/monthly. Free API key |
| FRED (St. Louis Fed) | Oil, natgas, industrial production, PPI for electricity | Daily/monthly. Free API key. Use **ALFRED vintages** for point-in-time data |
| ISO/RTO public data (ERCOT, PJM) | Load and price spikes in data-center regions | Daily (optional, phase 3+) |
| FERC / utility press releases | Large-load interconnection & data-center power deals | Weekly |

## Supply chain
| Source | Signal use | Cadence |
|--------|-----------|---------|
| NY Fed Global Supply Chain Pressure Index (GSCPI) | Aggregate supply stress | Monthly |
| US Census International Trade API | Imports of semis/equipment by HS code | Monthly |
| FRED: ISM-related series, freight/transport indexes available there | Logistics stress | Monthly |
| US Commerce/BIS export control announcements (Federal Register) | Policy shocks to semis | Daily |

## News & events (broad)
| Source | Use | Cadence |
|--------|-----|---------|
| GDELT DOC 2.0 API | Theme-level news volume & tone (queries per theme, see below) | Every 1–3 h |
| Curated RSS (Reuters tech/energy, company newsrooms, EIA Today in Energy) | Headlines for LLM classification | Hourly |

### Theme queries (GDELT/RSS keyword sets)
- `memory`: "DRAM", "HBM", "NAND", "memory chip prices", "SK Hynix", "Micron"
- `ai_capex`: "capital expenditure", "capex", "data center spending" + hyperscaler names
- `power`: "data center power", "grid interconnection", "nuclear PPA", "gas turbine", "electricity demand"
- `fab_supply`: "TSMC", "ASML", "lithography", "fab", "CoWoS", "advanced packaging"
- `policy`: "export controls", "tariff", "CHIPS Act", "entity list"
- `logistics`: "port congestion", "shipping rates", "Red Sea", "rare earth"

## Storage layout
```
R2 bucket:  raw/<source>/<YYYY>/<MM>/<DD>/<retrieved_at>_<hash>.json   # immutable
Postgres:   normalized tables: bars, news, macro_series, filings, events
```
Alpaca bars and news are ingested by the `executor` service (the only holder of Alpaca keys, `01`). All other
sources are ingested by `jobs`.

## Normalized tables (Postgres)
- `bars(symbol, ts, open, high, low, close, volume, source)`
- `macro_series(series_id, obs_date, value, published_at, vintage, source)`
- `news(id, ts_published, ts_retrieved, source, url, title, summary, tickers[], themes[], tone, dedupe_key)`
- `filings(cik, ticker, form, filed_at, url, extracted_json)`
- `events(id, ts, theme, node_id, direction, magnitude, confidence, evidence_urls[])`. Produced by the agent's classifier (`06`) and consumed by the shock map (`14`)

## Data quality rules
- Deduplicate news by normalized title + domain + 24 h window.
- Reject records with missing `published_at`. Never fall back to `retrieved_at` in a backtest.
- Every macro series lists its known publication lag (e.g., GSCPI ~4 business days after month end), and the backtest uses that lag.
- News text is **untrusted input** (it may contain prompt injection). See `06_AGENT.md` § Guardrails.
