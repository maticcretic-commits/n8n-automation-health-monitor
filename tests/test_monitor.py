"""Offline tests for the n8n automation health monitor.

All tests run through MockN8nClient or plain record lists — no network.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monitor import (  # noqa: E402
    MockN8nClient,
    error_counts_by_workflow,
    error_message,
    failed_executions,
    is_failure,
    render_digest,
    shift_timestamps_to_now,
    success_rate,
    uptime_report,
    workflow_name,
    write_daily_report,
)

NOW = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_executions.json")
WF_LEAD = "Lead capture to CRM"
WF_SOCIAL = "Social auto-poster"
WF_TRIAGE = "Gmail triage to Slack"
WF_FAQ = "AI FAQ webhook responder"


def make(status, name="Demo workflow", hours_ago=1, err=None, base=None):
    base = base or NOW
    rec = {
        "id": "1",
        "finished": True,
        "status": status,
        "startedAt": base.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workflowData": {"id": "wf-1", "name": name},
    }
    if err:
        rec["data"] = {"resultData": {"error": {"message": err}}}
    return rec


def sample_executions():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


# --- failure detection -----------------------------------------------------

def test_failed_executions_filter_status():
    records = [
        make("success"),
        make("error", err="boom"),
        make("failed", err="kaboom"),
        make("waiting"),
    ]
    failures = failed_executions(records)
    assert len(failures) == 2
    assert all(is_failure(e) for e in failures)


def test_failed_executions_window():
    records = sample_executions()
    recent = failed_executions(records, window_hours=24, now=NOW)
    # sample errors are at 1, 3, 8, 20, 30, 45 hours before NOW
    assert len(recent) == 4
    all_failures = failed_executions(records, now=NOW)
    assert len(all_failures) == 6


def test_failed_executions_unparseable_timestamp_excluded_from_window():
    records = [make("error", err="x")]
    records[0]["startedAt"] = "not-a-date"
    assert failed_executions(records, window_hours=24, now=NOW) == []


# --- aggregation -----------------------------------------------------------

def test_error_counts_by_workflow():
    records = sample_executions()
    counts = error_counts_by_workflow(records, window_hours=24, now=NOW)
    assert counts == {WF_LEAD: 3, WF_SOCIAL: 1}


def test_error_counts_empty():
    assert error_counts_by_workflow([make("success")]) == {}


# --- success rate math -----------------------------------------------------

def test_success_rate_math():
    records = [make("success") for _ in range(3)] + [make("error", err="x")]
    assert success_rate(records) == pytest.approx(0.75)


def test_success_rate_workflow_scoped():
    records = sample_executions()
    # Lead capture: 5 success, 3 failed of 8
    assert success_rate(records, workflow=WF_LEAD) == pytest.approx(5 / 8)
    assert success_rate(records, workflow="no such workflow") == 1.0


def test_success_rate_empty_is_one():
    assert success_rate([]) == 1.0


def test_uptime_report_structure():
    report = uptime_report(sample_executions())
    assert set(report) == {WF_LEAD, WF_SOCIAL, WF_TRIAGE, WF_FAQ}
    lead = report[WF_LEAD]
    assert lead == {"total": 8, "failures": 3, "success_rate": pytest.approx(0.625)}


# --- helpers ---------------------------------------------------------------

def test_workflow_name_fallbacks():
    assert workflow_name({"status": "success"}) == "unknown workflow"
    assert workflow_name({"workflowName": "X", "status": "success"}) == "X"


def test_error_message_missing():
    assert error_message(make("error")) is None
    assert error_message(make("error", err="nope")) == "nope"


def test_shift_timestamps_to_now():
    records = sample_executions()
    shifted = shift_timestamps_to_now(records, now=NOW)
    latest = max(
        datetime.fromisoformat(e["startedAt"].replace("Z", "+00:00"))
        for e in shifted
    )
    assert latest <= NOW
    assert (NOW - latest).total_seconds() == pytest.approx(300, abs=60)


# --- rendering ---------------------------------------------------------------

def test_render_digest_with_failures():
    records = sample_executions()
    failures = failed_executions(records, window_hours=24, now=NOW)
    digest = render_digest(failures, window_hours=24)
    assert "4 failed execution(s)" in digest
    assert WF_LEAD in digest
    assert "429" in digest


def test_render_digest_empty():
    digest = render_digest([], window_hours=24)
    assert "No failed executions" in digest


def test_render_digest_unknown_error_message():
    digest = render_digest([make("error")])
    assert "Unknown error" in digest


def test_write_daily_report(tmp_path):
    records = sample_executions()
    path = write_daily_report(records, report_dir=str(tmp_path),
                              window_hours=24, now=NOW)
    assert os.path.isfile(path)
    body = open(path, encoding="utf-8").read()
    assert "# n8n Health Report" in body
    assert WF_LEAD in body
    assert "Failures: 4" in body


# --- mock client -------------------------------------------------------------

def test_mock_client_loads_sample_file():
    client = MockN8nClient.from_file(DATA_PATH)
    executions = client.get_executions(limit=200)
    assert len(executions) == 19
    assert all(isinstance(e, dict) for e in executions)


def test_mock_client_limit():
    client = MockN8nClient.from_file(DATA_PATH)
    assert len(client.get_executions(limit=5)) == 5
