"""Paths and settings. Every value has a safe default, so no config file is required.

Optional file: $AGENT_DASHBOARD_DIR/config.yaml (default ~/.claude/agent-dashboard/config.yaml)

    privacy:
      store_result_text: false   # keep WORKER/ADVISOR report text in the DB (redacted)
      store_prompts: false       # keep headless prompts (redacted)
      redact: [ '(?i)api[_-]?key\\s*[:=]\\s*\\S+' ]   # extra regexes, added to the built-ins
    retention:
      raw_days: 30               # raw_events, tool_events, otel_* tables
      structured_days: 180       # dispatches, guardrail_hits, runs, plan_items
    budget:
      daily_usd: 20
    server:
      port: 8765
      otlp_port: 4318
"""
import copy
import os

from . import yaml_lite

DEFAULTS = {
    "privacy": {"store_result_text": False, "store_prompts": False, "redact": []},
    "retention": {"raw_days": 30, "structured_days": 180},
    "budget": {"daily_usd": 20.0},
    "server": {"host": "127.0.0.1", "port": 8765, "otlp_port": 4318},
    "loop": {"max_advisor_rounds": 2},
}


def data_dir():
    return os.environ.get("AGENT_DASHBOARD_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "agent-dashboard")


def paths(base=None):
    d = base or data_dir()
    return {
        "dir": d,
        "events": os.environ.get("AGENT_DASHBOARD_LOG") or os.path.join(d, "events.jsonl"),
        "otel": os.path.join(d, "otel.jsonl"),
        "db": os.environ.get("AGENT_DASHBOARD_DB") or os.path.join(d, "dashboard.sqlite3"),
        "config": os.path.join(d, "config.yaml"),
        "alerts": os.environ.get("AGENT_DASHBOARD_ALERTS") or os.path.join(d, "alerts.yaml"),
        "snapshots": os.path.join(d, "snapshots"),
    }


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    p = path or paths()["config"]
    if os.path.exists(p):
        try:
            _merge(cfg, yaml_lite.load_file(p) or {})
        except Exception as e:  # a broken config must not break ingestion
            cfg["_config_error"] = str(e)
    if os.environ.get("AGENT_DASHBOARD_LOG_CONTENT") == "1":
        cfg["privacy"]["store_result_text"] = True
    return cfg
