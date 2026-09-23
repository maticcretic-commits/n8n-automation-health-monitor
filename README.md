# n8n Automation Health Monitor

**Practice/demo toolkit for learning how to monitor and maintain n8n workflows.**
Modeled on the type of work described in a real **$1,000 fixed-price Upwork posting**
("Automation Partner for n8n and AI Workflows") — a long-term partnership where a
freelancer not only builds automations but keeps them running: failure monitoring,
error alerting, and uptime reporting.

> This is a learning project. It contains no client data, no client work, and no
> claim of paid experience — just a working demo of the maintenance discipline
> that long-term automation clients pay for.

## What it does

- Pulls workflow executions from an n8n instance (Public API, key auth)
- Lists failed executions in a time window (default: last 24 hours)
- Aggregates error counts by workflow, so you see *which* automation is sick
- Computes per-workflow success rate / uptime
- Renders a plain-text **alert digest** — ready to paste into an email or Slack message
- Writes a dated **daily health report** (`reports/health-YYYY-MM-DD.md`)

Everything runs **offline** with bundled sample data via `--mock`, so you can
demo and test it without an n8n instance.

## Quick start (demo, no n8n needed)

```bash
python3 monitor.py --mock
```

This loads `data/sample_executions.json`, shifts the timestamps to "now", prints
the failure digest, and writes `reports/health-<today>.md`.

Sample digest output:

```
n8n Health Digest — last 24h
========================================
4 failed execution(s) across 2 workflow(s):

[Lead capture to CRM] 3 failure(s)
  - 2026-09-23T05:00:00Z: Request failed with status code 429: rate limit exceeded
  ...
```

## Pointing it at a real n8n instance

1. In n8n: **Settings → n8n API → Create API key**.
2. Copy `.env.example` to `.env` and fill it in:

```bash
N8N_BASE_URL=https://your-n8n.example.com
N8N_API_KEY=your-api-key-here
ALERT_WINDOW_HOURS=24   # optional
REPORT_DIR=./reports    # optional
```

3. Run it:

```bash
python3 monitor.py
```

The script uses the n8n Public API (`GET /api/v1/executions`) with the API key
in the `X-N8N-API-KEY` header. **Never commit your `.env`** — it is gitignored.

## Running the tests

```bash
pip install pytest        # test-only dependency
python3 -m pytest tests/ -q
```

Tests use `MockN8nClient` and the bundled sample data — fully offline.

## Maintenance runbook (the part clients actually pay for)

When someone hires an "automation partner", they are buying this discipline:

### Daily (~10 minutes)
- [ ] Run the digest for the last 24h (`python3 monitor.py --mock` or live)
- [ ] Any failures? Note workflow name, error message, first occurrence time
- [ ] Retry or fix transient errors (rate limits, expired tokens)
- [ ] Confirm the daily health report was written to `reports/`

### Weekly (~30 minutes)
- [ ] Review 7 days of digests: which workflows fail most often?
- [ ] For the top offender, add retry logic or error handling in n8n
- [ ] Check n8n instance health: disk space, queued executions, version updates
- [ ] Rotate/refresh any expiring API credentials used by workflows

### Monthly (~1 hour)
- [ ] Compute monthly success rates from the daily reports
- [ ] Share a one-page uptime summary with the client (transparency = renewals)
- [ ] Archive old reports; prune executions older than the retention policy
- [ ] Review which workflows grew in volume — plan capacity before it breaks

## Learning roadmap

1. Run the demo, read `monitor.py` end to end
2. Add a new analysis: failure rate *per hour of day* (when do things break?)
3. Send the digest to Slack via an incoming webhook (stdlib `urllib` is enough)
4. Schedule the script with cron so the digest arrives every morning
5. Point it at a real self-hosted n8n instance and monitor a workflow you built
6. Package the digest as an n8n workflow itself (dogfooding: monitor with n8n)

## Project layout

```
monitor.py                    # the monitor: clients, analysis, digest, report, CLI
data/sample_executions.json   # 19 mock n8n executions (6 failures, 4 workflows)
tests/test_monitor.py         # offline pytest suite
.env.example                  # env vars for a live n8n instance
```

## ❤️ Support My Work

> If you find this project useful, please consider supporting my work with a Bitcoin donation:
>
> **₿ `BC1Q6Q75K8ZJXVW7W02LMDPRPY6XX6QK4LZZ2RMVAY`**

## ☕ Support my work
If this project was useful, you can support it with Bitcoin: `bc1q6q75k8zjxvw7w02lmdprpy6xx6qk4lzz2rmvay`
