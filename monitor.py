#!/usr/bin/env python3
"""n8n Automation Health Monitor — practice/demo toolkit.

Monitors n8n workflow executions for failures, aggregates error counts per
workflow, computes success-rate / uptime stats, and renders a plain-text
alert digest (suitable for email/Slack) plus a daily markdown health report.

All network access is isolated in N8nClient subclasses. Use MockN8nClient
for offline demos and tests; HttpN8nClient talks to a real n8n Public API.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

FAILURE_STATUSES = {"error", "failed"}


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def parse_ts(value):
    """Parse an ISO-8601 timestamp; return None when missing/unparseable."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

def workflow_name(execution):
    """Best-effort workflow name from an n8n execution record."""
    data = execution.get("workflowData") or {}
    return data.get("name") or execution.get("workflowName") or "unknown workflow"


def error_message(execution):
    """Best-effort error message extraction; None when there is none."""
    data = execution.get("data") or {}
    result = data.get("resultData") or {}
    err = result.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("name")
    else:
        msg = err
    if msg:
        return str(msg)
    direct = execution.get("error") or execution.get("lastError")
    return str(direct) if direct else None


def is_failure(execution):
    """True when the execution record represents a failed run."""
    return str(execution.get("status", "")).lower() in FAILURE_STATUSES


# ---------------------------------------------------------------------------
# Clients — network code lives only here, so tests can run fully offline
# ---------------------------------------------------------------------------

class N8nClient:
    """Interface: fetch executions from an n8n instance."""

    def get_executions(self, limit=100):
        raise NotImplementedError


class HttpN8nClient(N8nClient):
    """Real n8n Public API client (urllib, stdlib only).

    Reads the API key from the environment (N8N_API_KEY) via load_config().
    """

    def __init__(self, base_url, api_key, timeout=15):
        if not base_url or not api_key:
            raise ValueError("base_url and api_key are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get_executions(self, limit=100):
        url = f"{self.base_url}/api/v1/executions?limit={limit}"
        req = urllib.request.Request(url, headers={"X-N8N-API-KEY": self.api_key})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict):
            return payload.get("data", [])
        return payload


class MockN8nClient(N8nClient):
    """Offline client serving a fixed list of execution records (demos/tests)."""

    def __init__(self, executions):
        self._executions = list(executions)

    @classmethod
    def from_file(cls, path, shift_to_now=False):
        with open(path, "r", encoding="utf-8") as f:
            executions = json.load(f)
        if shift_to_now:
            executions = shift_timestamps_to_now(executions)
        return cls(executions)

    def get_executions(self, limit=100):
        return self._executions[:limit]


def shift_timestamps_to_now(executions, now=None):
    """Shift all startedAt/stoppedAt so the newest lands ~5 min before `now`.

    Keeps bundled sample data useful for demos regardless of when it is run,
    while preserving the relative spacing between executions.
    """
    now = now or now_utc()
    stamps = [
        parse_ts(e.get("startedAt")) or parse_ts(e.get("stoppedAt"))
        for e in executions
    ]
    stamps = [s for s in stamps if s]
    if not stamps:
        return executions
    delta = now - timedelta(minutes=5) - max(stamps)
    shifted = []
    for execution in executions:
        execution = dict(execution)
        for key in ("startedAt", "stoppedAt"):
            ts = parse_ts(execution.get(key))
            if ts is not None:
                execution[key] = (ts + delta).isoformat().replace("+00:00", "Z")
        shifted.append(execution)
    return shifted


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def failed_executions(executions, window_hours=None, now=None):
    """Return failed executions, optionally restricted to the last N hours."""
    now = now or now_utc()
    out = []
    for execution in executions:
        if not is_failure(execution):
            continue
        if window_hours is not None:
            ts = parse_ts(execution.get("startedAt")) or parse_ts(execution.get("stoppedAt"))
            if ts is None or (now - ts) > timedelta(hours=window_hours):
                continue
        out.append(execution)
    return out


def error_counts_by_workflow(executions, window_hours=None, now=None):
    """Map workflow name -> number of failed executions (optional time window)."""
    failures = failed_executions(executions, window_hours=window_hours, now=now)
    return dict(Counter(workflow_name(e) for e in failures))


def success_rate(executions, workflow=None):
    """Fraction of executions that succeeded (1.0 when there are none)."""
    scoped = [
        e for e in executions
        if workflow is None or workflow_name(e) == workflow
    ]
    if not scoped:
        return 1.0
    ok = sum(1 for e in scoped if not is_failure(e))
    return ok / len(scoped)


def uptime_report(executions):
    """Per-workflow stats: {name: {total, failures, success_rate}}."""
    groups = {}
    for execution in executions:
        name = workflow_name(execution)
        group = groups.setdefault(name, {"total": 0, "failures": 0})
        group["total"] += 1
        if is_failure(execution):
            group["failures"] += 1
    for group in groups.values():
        total, failures = group["total"], group["failures"]
        group["success_rate"] = round((total - failures) / total, 4) if total else 1.0
    return groups


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def render_digest(failures, window_hours=24):
    """Plain-text alert digest, suitable for email/Slack bodies."""
    lines = [f"n8n Health Digest — last {window_hours}h", "=" * 40]
    if not failures:
        lines.append("No failed executions in this window. All workflows healthy.")
        return "\n".join(lines) + "\n"
    by_workflow = Counter(workflow_name(e) for e in failures)
    lines.append(
        f"{len(failures)} failed execution(s) across {len(by_workflow)} workflow(s):"
    )
    lines.append("")
    for name, count in by_workflow.most_common():
        lines.append(f"[{name}] {count} failure(s)")
        for execution in [e for e in failures if workflow_name(e) == name][:5]:
            ts = execution.get("startedAt") or execution.get("stoppedAt") or "unknown time"
            lines.append(f"  - {ts}: {error_message(execution) or 'Unknown error'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_daily_report(executions, report_dir="reports", window_hours=24, now=None):
    """Write a markdown health report; return the path written."""
    now = now or now_utc()
    os.makedirs(report_dir, exist_ok=True)
    failures = failed_executions(executions, window_hours=window_hours, now=now)
    report = uptime_report(executions)
    path = os.path.join(report_dir, f"health-{now.strftime('%Y-%m-%d')}.md")
    lines = [
        f"# n8n Health Report — {now.strftime('%Y-%m-%d')}",
        "",
        f"Window: last {window_hours}h | Total executions: {len(executions)} "
        f"| Failures: {len(failures)}",
        "",
        "## Per-workflow success rates",
    ]
    for name in sorted(report):
        group = report[name]
        lines.append(
            f"- {name}: {group['total'] - group['failures']}/{group['total']} "
            f"succeeded ({group['success_rate'] * 100:.1f}%)"
        )
    lines += ["", "## Failures"]
    if failures:
        for execution in failures:
            ts = execution.get("startedAt") or "unknown time"
            lines.append(
                f"- [{workflow_name(execution)}] {ts}: "
                f"{error_message(execution) or 'Unknown error'}"
            )
    else:
        lines.append("None.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_config():
    return {
        "base_url": os.environ.get("N8N_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("N8N_API_KEY", ""),
        "window_hours": int(os.environ.get("ALERT_WINDOW_HOURS", "24")),
        "report_dir": os.environ.get("REPORT_DIR", "reports"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="n8n automation health monitor (practice toolkit)"
    )
    parser.add_argument("--mock", action="store_true",
                        help="use bundled sample data instead of a live n8n instance")
    parser.add_argument("--data", default="data/sample_executions.json",
                        help="sample data file used with --mock")
    args = parser.parse_args(argv)

    config = load_config()
    if args.mock:
        client = MockN8nClient.from_file(args.data, shift_to_now=True)
    else:
        if not config["base_url"] or not config["api_key"]:
            print("Set N8N_BASE_URL and N8N_API_KEY (see .env.example), "
                  "or run with --mock.", file=sys.stderr)
            return 2
        client = HttpN8nClient(config["base_url"], config["api_key"])

    executions = client.get_executions(limit=200)
    failures = failed_executions(executions, window_hours=config["window_hours"])
    print(render_digest(failures, window_hours=config["window_hours"]))
    path = write_daily_report(executions, report_dir=config["report_dir"],
                              window_hours=config["window_hours"])
    print(f"Daily report written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
