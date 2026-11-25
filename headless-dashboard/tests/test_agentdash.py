"""Tests for dashboard v2, run on the recorded fixture. Standard library only.

    python3 -m unittest discover -s tests -v
"""
import gzip
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "claude-home", "agent-dashboard")
HOOK = os.path.join(ROOT, "claude-home", "hooks", "log_event.py")
sys.path.insert(0, PKG_DIR)
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))

from agentdash import alerts, config, ingest, metrics, otlp, parse, report, retention, server, store, yaml_lite  # noqa: E402
import make_fixture  # noqa: E402


def cfg(**privacy):
    c = config.load("/nonexistent/config.yaml")
    c["privacy"].update(privacy)
    return c


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="agentdash-test-")
        cls.fx = os.path.join(cls.tmp, "fx")
        cls.exp = make_fixture.main(cls.fx)
        cls.NOW = cls.exp["now"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self, name="db", **privacy):
        d = tempfile.mkdtemp(dir=self.tmp)
        paths = {"dir": d, "events": os.path.join(d, "events.jsonl"), "otel": os.path.join(d, "otel.jsonl"),
                 "db": os.path.join(d, f"{name}.sqlite3"), "alerts": os.path.join(d, "alerts.yaml"),
                 "snapshots": os.path.join(d, "snap")}
        shutil.copy(os.path.join(self.fx, "events.jsonl"), paths["events"])
        shutil.copy(os.path.join(self.fx, "otel.jsonl"), paths["otel"])
        conn = store.connect(paths["db"])
        ingest.run(conn, paths, cfg(**privacy))
        return conn, paths


class TestMetricsOnFixture(Base):
    def setUp(self):
        self.conn, self.paths = self.fresh()
        self.res = metrics.compute(self.conn, since=0, now=self.NOW)
        self.m = self.res["metrics"]

    def test_fixture_shape(self):
        self.assertGreaterEqual(len({t["project"] for t in self.res["tasks"]}), 3)
        self.assertGreaterEqual(self.exp["tasks"], 20)
        self.assertGreater(self.exp["stuck"], 0)
        self.assertGreater(self.exp["memory_hits"], 0)
        self.assertGreaterEqual(len(self.exp["guardrail_hits"]), 8)

    def test_task_states(self):
        p = self.res["progress"]
        self.assertEqual(p["tasks_total"], self.exp["tasks"])
        self.assertEqual(p["done"], self.exp["done"])
        self.assertEqual(p["stuck"], self.exp["stuck"])
        self.assertEqual(p["active"], self.exp["active"])
        stuck = sorted(t["key"] for t in self.res["tasks"] if t["state"] == "stuck")
        self.assertEqual(stuck, sorted(self.exp["stuck_keys"]))

    def test_ratio_metrics_match_independent_count(self):
        e = self.exp
        cases = {
            "first_try_success_pct": (e["first_try"], e["with_report"]),
            "escalation_pct": (e["escalated_terminal"], e["with_report"]),
            "advisor_fix_pct": (e["fixed"], e["escalated_terminal"]),
            "worker_success_pct": (e["works_reports"], e["worker_reports"]),
            "fake_works_pct": (e["fake_works"], e["works_reports"]),
            "memory_hit_pct": (e["memory_hits"], e["advisor_with_field"]),
            "memory_assisted_success_pct": (e["memory_tasks_done"], e["memory_tasks_terminal"]),
        }
        for name, (num, den) in cases.items():
            with self.subTest(metric=name):
                self.assertEqual((self.m[name]["num"], self.m[name]["den"]), (num, den))
                self.assertAlmostEqual(self.m[name]["value"], round(100 * num / den, 2))

    def test_guardrails_by_number(self):
        g = self.res["guardrails"]
        self.assertEqual(g["total"], self.exp["guardrail_total"])
        for k, n in self.exp["guardrail_hits"].items():
            self.assertEqual(g["by_guardrail"][k]["hits"], n, k)
        self.assertEqual(g["unattributed"], 0)

    def test_rounds_distribution(self):
        self.assertEqual(self.res["advisor_rounds_distribution"], self.exp["rounds"])

    def test_cost_one_source_per_session(self):
        self.assertAlmostEqual(self.m["cost_usd"]["value"], self.exp["cost_usd"], places=3)
        for src, v in self.exp["cost_by_source"].items():
            self.assertAlmostEqual(self.res["cost_sources"][src], v, places=3)
        self.assertAlmostEqual(self.m["cost_per_solved_task_usd"]["value"], self.exp["cost_usd"] / self.exp["done"], places=3)

    def test_min_sample_flag(self):
        r = metrics.compute(self.conn, project="mobile-app", since=0, now=self.NOW)
        self.assertFalse(r["metrics"]["memory_assisted_success_pct"]["sufficient"])
        self.assertTrue(self.m["worker_success_pct"]["sufficient"])

    def test_project_filter(self):
        for proj, e in self.exp["projects"].items():
            r = metrics.compute(self.conn, project=proj, since=0, now=self.NOW)
            self.assertEqual(r["progress"]["done"], e["done"], proj)
            self.assertEqual(r["progress"]["stuck"], e["stuck"], proj)

    def test_otel_join_and_tokens(self):
        j = self.res["join"]
        self.assertGreater(j.get("trace", 0), 0)
        traced = self.conn.execute("SELECT COUNT(*) FROM dispatches WHERE join_method='trace'").fetchone()[0]
        expected = self.conn.execute("SELECT COUNT(*) FROM dispatches d JOIN otel_spans s ON s.tool_use_id=d.tool_use_id "
                                     "AND s.name='claude_code.tool'").fetchone()[0]
        self.assertEqual(traced, expected)
        self.assertGreater(self.res["agents"]["_token_sources"].get("otel_logs", 0), 0)

    def test_window_counts_each_task_once(self):
        days = metrics.days_with_data(self.conn)
        total = 0
        for d in days:
            s, e = metrics._day_bounds(d)
            total += metrics.compute(self.conn, since=s, until=e, now=self.NOW, include_detail=False)["metrics"]["tasks_done"]["value"]
        self.assertEqual(total, self.exp["done"])

    def test_weekly_trends_are_exact(self):
        metrics.rollup(self.conn, now=self.NOW)
        tr = metrics.trends(self.conn, weeks=8, now=self.NOW)["series"]
        self.assertEqual(sum(p["value"] for p in tr["tasks_done"]), self.exp["done"])
        ws = tr["worker_success_pct"]
        self.assertEqual(sum(p["num"] for p in ws), self.exp["works_reports"])
        self.assertGreaterEqual(len(ws), 3)
        self.assertEqual(sum(sum(p["value"] for p in tr[f"guardrail_hits_{g}"]) for g in metrics.ALL_GUARDRAILS),
                         self.exp["guardrail_total"])

    def test_spec_complete(self):
        names = {m["name"] for m in metrics.spec()}
        for required in ("first_try_success_pct", "escalation_pct", "advisor_fix_pct", "worker_success_pct", "avg_task_sec",
                         "throughput_per_day", "cost_usd", "guardrail_hits_per_task", "fake_works_pct", "memory_hit_pct",
                         "memory_assisted_success_pct", "cost_per_solved_task_usd"):
            self.assertIn(required, names)
        for m in metrics.spec():
            self.assertTrue(m["formula"] and m["source"] and m["unit"], m)


class TestIngestion(Base):
    def _paths(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        return {"dir": d, "events": os.path.join(d, "events.jsonl"), "otel": os.path.join(d, "otel.jsonl"),
                "db": os.path.join(d, "x.sqlite3")}

    def _lines(self):
        with open(os.path.join(self.fx, "events.jsonl"), encoding="utf-8") as f:
            return f.readlines()

    def _count(self, conn):
        return conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]

    def test_incremental_and_partial_line(self):
        p, lines = self._paths(), self._lines()
        conn = store.connect(p["db"])
        with open(p["events"], "w") as f:
            f.writelines(lines[:100])
            f.write(lines[100].rstrip("\n")[:30])         # writer is mid-line
        ingest.run(conn, p, cfg())
        self.assertEqual(self._count(conn), 100)
        off1 = conn.execute("SELECT offset FROM ingest_state WHERE source='events'").fetchone()[0]
        with open(p["events"], "a") as f:
            f.write(lines[100].rstrip("\n")[30:] + "\n")
            f.writelines(lines[101:])
        r = ingest.run(conn, p, cfg())
        self.assertEqual(self._count(conn), len(lines))
        self.assertEqual(r["events"]["lines"], len(lines) - 100)   # only new bytes were read
        self.assertGreater(conn.execute("SELECT offset FROM ingest_state WHERE source='events'").fetchone()[0], off1)
        r = ingest.run(conn, p, cfg())
        self.assertEqual(r["events"]["lines"], 0)

    def test_rotation_drains_old_file(self):
        p, lines = self._paths(), self._lines()
        conn = store.connect(p["db"])
        with open(p["events"], "w") as f:
            f.writelines(lines[:150])
        ingest.run(conn, p, cfg())
        with open(p["events"], "a") as f:                   # written after the last ingest ...
            f.writelines(lines[150:200])
        os.rename(p["events"], p["events"] + ".1")         # ... then rotated away
        with open(p["events"], "w") as f:
            f.writelines(lines[200:])
        r = ingest.run(conn, p, cfg())
        self.assertEqual(self._count(conn), len(lines))
        self.assertTrue(any("rotated" in n for n in r["notes"]))

    def test_truncation_and_copytruncate_are_idempotent(self):
        p, lines = self._paths(), self._lines()
        conn = store.connect(p["db"])
        with open(p["events"], "w") as f:
            f.writelines(lines)
        ingest.run(conn, p, cfg())
        n = self._count(conn)
        with open(p["events"], "w") as f:                   # truncated in place, then new lines
            f.writelines(lines[:5])
        r = ingest.run(conn, p, cfg())
        self.assertTrue(any("truncated" in x for x in r["notes"]))
        self.assertEqual(self._count(conn), n)               # the 5 re-read lines are duplicates
        self.assertEqual(r["events"]["dup"], 5)

    def test_bad_lines_are_skipped(self):
        p = self._paths()
        conn = store.connect(p["db"])
        with open(p["events"], "w") as f:
            f.write('not json\n{"event":"x"}\n[1,2]\n{"ts": 1, "event": "Stop"}\n')
        r = ingest.run(conn, p, cfg())
        self.assertEqual(r["events"]["bad"], 3)
        self.assertEqual(self._count(conn), 1)

    def test_missing_files_are_fine(self):
        p = self._paths()
        conn = store.connect(p["db"])
        r = ingest.run(conn, p, cfg())
        self.assertEqual(r["events"]["lines"], 0)

    def test_migrations_idempotent(self):
        p = self._paths()
        c1 = store.connect(p["db"])
        v = store.current_version(c1)
        c1.close()
        c2 = store.connect(p["db"])
        self.assertEqual(store.current_version(c2), v)
        self.assertEqual(v, store.SCHEMA_VERSION)
        self.assertEqual(c2.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], len(store.MIGRATIONS))


class TestV1Compatibility(Base):
    def test_v1_demo_log_gives_same_core_numbers_as_v1_server(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        with zipfile.ZipFile(os.path.join(ROOT, "agent-workflow.zip")) as z:
            for name in ("server.py", "demo.py"):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(z.read(f"agent-workflow/claude-home/agent-dashboard/{name}"))
        subprocess.run([sys.executable, os.path.join(d, "demo.py")], check=True, capture_output=True)
        log = os.path.join(d, "demo-events.jsonl")
        sys.path.insert(0, d)
        try:
            import importlib
            v1 = importlib.import_module("server")
            importlib.reload(v1)
            old = v1.compute(v1.load_events(log))
        finally:
            sys.path.remove(d)
        conn = store.connect(":memory:")
        ingest.run(conn, {"events": log, "otel": os.path.join(d, "none")}, cfg())
        new = metrics.legacy_state(metrics.compute(conn, since=0))
        self.assertEqual(set(old.keys()) - {"generated_at"}, set(new.keys()) - {"generated_at"})
        self.assertEqual(old["progress"]["by_state"].get("done"), new["progress"]["by_state"].get("done"))
        self.assertEqual(old["progress"]["by_state"].get("stuck"), new["progress"]["by_state"].get("stuck"))
        self.assertEqual(old["progress"]["planned_total"], new["progress"]["planned_total"])
        self.assertEqual(old["performance"]["worker_success_pct"], new["performance"]["worker_success_pct"])
        for a in ("worker", "advisor"):
            self.assertEqual(old["agents"][a]["dispatches"], new["agents"][a]["dispatches"], a)
        self.assertEqual(old["agents"]["worker"]["works"], new["agents"]["worker"]["works"])
        self.assertAlmostEqual(old["performance"]["cost_usd"], new["performance"]["cost_usd"])


class TestPrivacy(Base):
    def _dump(self, path):
        conn = sqlite3.connect(path)
        return "\n".join(str(r) for t in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                         for r in conn.execute(f"SELECT * FROM {t}"))

    def test_no_report_or_prompt_text_stored_by_default(self):
        conn, p = self.fresh()
        conn.close()
        dump = self._dump(p["db"])
        self.assertNotIn("=== WORKER REPORT ===", dump)      # v1 events carry it; it must be dropped
        self.assertNotIn("SECRET PROMPT TEXT", dump)        # OTel prompt attribute is never stored
        c = sqlite3.connect(p["db"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dispatches WHERE result_text IS NOT NULL").fetchone()[0], 0)

    def test_opt_in_keeps_redacted_text(self):
        conn, p = self.fresh(store_result_text=True)
        n = conn.execute("SELECT COUNT(*) FROM dispatches WHERE result_text LIKE '%WORKER REPORT%'").fetchone()[0]
        self.assertGreater(n, 0)

    def test_redaction_rules(self):
        s = "key sk-ant-abcdefghijklmnop123 and AKIAABCDEFGHIJKLMNOP, mail a.b@example.com, password=hunter2"
        out = parse.redact(s)
        for secret in ("sk-ant-abcdefghijklmnop123", "AKIAABCDEFGHIJKLMNOP", "a.b@example.com", "hunter2"):
            self.assertNotIn(secret, out)
        custom = parse.compile_redactions([r"ACME-\d+"])
        self.assertNotIn("ACME-42", parse.redact("ticket ACME-42", custom))

    def test_otlp_scrub(self):
        body = {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"attributes": [
            {"key": "prompt", "value": {"stringValue": "secret"}}, {"key": "session.id", "value": {"stringValue": "s"}}]}]}]}]}
        otlp.scrub(body)
        keys = [a["key"] for a in body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]]
        self.assertEqual(keys, ["session.id"])


class TestHook(Base):
    def _run(self, stdin, env_extra, args=()):
        d = tempfile.mkdtemp(dir=self.tmp)
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_WORKFLOW", "AGENT_DASHBOARD_LOG_CONTENT")}
        env.update({"AGENT_DASHBOARD_DIR": d, "PYTHONPATH": PKG_DIR}, **env_extra)
        r = subprocess.run([sys.executable, HOOK, *args], input=stdin, env=env, capture_output=True, text=True, timeout=20)
        path = os.path.join(d, "events.jsonl")
        lines = []
        if os.path.exists(path):
            with open(path) as f:
                lines = f.read().splitlines()
        return r, [json.loads(x) for x in lines]

    POST = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_use_id": "toolu_1", "session_id": "s1",
                       "cwd": "/x/proj", "tool_input": {"subagent_type": "worker", "description": "[T1] Fix it"},
                       "tool_response": {"content": [{"type": "text", "text": "=== WORKER REPORT ===\nSTATUS: WORKS\n"
                                         "VERIFICATION:\n- command: pytest\nATTEMPTS: 1/3\nsecret code here"}],
                                         "totalDurationMs": 1200, "totalTokens": 900}})

    def test_noop_without_env(self):
        r, ev = self._run(self.POST, {})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(ev, [])

    def test_structured_and_content_free(self):
        r, ev = self._run(self.POST, {"AGENT_WORKFLOW": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(ev[0]["report"]["status"], "WORKS")
        self.assertEqual(ev[0]["report"]["attempts"], 1)
        self.assertEqual(ev[0]["tool_use_id"], "toolu_1")
        self.assertNotIn("result_text", ev[0])
        self.assertNotIn("secret code", json.dumps(ev))

    def test_content_opt_in(self):
        _, ev = self._run(self.POST, {"AGENT_WORKFLOW": "1", "AGENT_DASHBOARD_LOG_CONTENT": "1"})
        self.assertIn("secret code", ev[0]["result_text"])

    def test_garbage_and_unwritable_never_fail(self):
        r, _ = self._run("{not json", {"AGENT_WORKFLOW": "1"})
        self.assertEqual(r.returncode, 0)
        r = subprocess.run([sys.executable, HOOK], input=self.POST, capture_output=True, text=True, timeout=20,
                           env={**os.environ, "AGENT_WORKFLOW": "1", "AGENT_DASHBOARD_DIR": "/dev/null/nope"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_guardrail_mode(self):
        stdin = json.dumps({"session_id": "s1", "tool_use_id": "toolu_9", "cwd": "/x/proj"})
        r, ev = self._run(stdin, {"AGENT_WORKFLOW": "1"}, ["--guardrail", "g3", "--reason", "WORKS without test run"])
        self.assertEqual(ev[0]["event"], "guardrail_hit")
        self.assertEqual(ev[0]["guardrail"], "G3")
        self.assertEqual(ev[0]["tool_use_id"], "toolu_9")

    def test_failure_marker(self):
        stdin = json.dumps({"hook_event_name": "PostToolUseFailure", "tool_name": "Edit", "session_id": "s1", "cwd": "/x/p",
                            "error": "GUARDRAIL G8: acceptance test tests/test_x.py may not be edited"})
        _, ev = self._run(stdin, {"AGENT_WORKFLOW": "1"})
        self.assertEqual(ev[0]["guardrails"], ["G8"])
        self.assertNotIn("acceptance test", json.dumps(ev))


class TestAlerts(Base):
    def setUp(self):
        self.conn, self.paths = self.fresh()
        self.sent = []

    def sender(self, url, body, headers):
        self.sent.append((url, body, headers))
        return 200

    def doc(self, **defaults):
        return {"version": 1, "defaults": {"dashboard_url": "http://127.0.0.1:8765", "max_per_channel_per_run": 50, **defaults},
                "channels": {"hook": {"type": "webhook", "url": "http://example.invalid/hook"},
                             "slack": {"type": "slack", "url": "http://example.invalid/slack"}},
                "rules": [
                    {"id": "task_stuck", "kind": "task_stuck", "severity": "high", "lookback": "60d", "channels": ["hook"]},
                    {"id": "g3g8", "kind": "guardrail_hit", "guardrails": ["G3", "G8"], "severity": "critical",
                     "lookback": "60d", "channels": ["hook"]},
                    {"id": "budget", "kind": "cost_over_budget", "budget_usd": 0.01, "severity": "high", "channels": ["hook"]},
                    {"id": "fix", "kind": "advisor_fix_rate", "last_n": 5, "below_pct": 90, "severity": "warning",
                     "notify_resolved": True, "channels": ["hook"]},
                    {"id": "silent", "kind": "no_events", "minutes": 15, "severity": "high", "notify_resolved": True,
                     "channels": ["hook"]}]}

    def test_default_rules_and_payload(self):
        now = self.exp["base"] + 21 * 86400 + 20 * 3600   # day of s-data-2, after its events
        doc = self.doc()
        res = alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now), now=now, sender=self.sender)
        bodies = [b for _, b, _ in self.sent]
        by_rule = {}
        for b in bodies:
            by_rule.setdefault(b["rule"], []).append(b)
        self.assertEqual(len(by_rule["task_stuck"]), self.exp["stuck"])
        self.assertEqual(len(by_rule["g3g8"]), self.exp["guardrail_hits"]["G3"] + self.exp["guardrail_hits"]["G8"])
        self.assertEqual(len(by_rule["budget"]), 1)
        self.assertIn("fix", by_rule)
        for b in bodies:
            self.assertEqual(b["schema"], "agentdash.alert/v1")
            for k in ("project", "summary", "inspect", "dedup_key", "severity", "status"):
                self.assertIn(k, b)
            self.assertIn("orch-dashboard", b["inspect"]["command"])
        stuck = by_rule["task_stuck"][0]
        self.assertTrue(stuck["task_id"].startswith("T"))
        self.assertIn("--task", stuck["inspect"]["command"])
        self.assertTrue(all(d["ok"] for d in res["deliveries"]))

    def test_dedup(self):
        now = self.NOW
        doc = self.doc()
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now), now=now, sender=self.sender)
        first = len(self.sent)
        self.assertGreater(first, 0)
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now + 300), now=now + 300, sender=self.sender)
        self.assertEqual(len(self.sent), first)

    def test_quiet_hours_hold_then_release(self):
        qh = {"start": "00:00", "end": "06:00", "tz": "UTC", "allow_severity": ["critical"]}
        doc = self.doc(quiet_hours=qh)
        now = self.NOW + 3600                                   # 01:00 UTC: quiet
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now), now=now, sender=self.sender)
        self.assertTrue(self.sent)
        self.assertTrue(all(b["severity"] == "critical" for _, b, _ in self.sent))
        held = self.conn.execute("SELECT COUNT(*) FROM alert_state WHERE held=1").fetchone()[0]
        self.assertGreater(held, 0)
        self.sent.clear()
        later = self.NOW + 7 * 3600                             # 07:00 UTC: quiet hours over
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, later), now=later, sender=self.sender)
        self.assertEqual(len(self.sent), held)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alert_state WHERE held=1").fetchone()[0], 0)

    def test_quiet_hours_wrap_midnight(self):
        qh = {"start": "22:00", "end": "07:00", "tz": "Asia/Bangkok"}
        base = self.exp["base"]                                  # 00:00 UTC = 07:00 Bangkok
        self.assertFalse(alerts.in_quiet_hours(qh, base))
        self.assertTrue(alerts.in_quiet_hours(qh, base - 3600))  # 06:00 Bangkok
        self.assertTrue(alerts.in_quiet_hours(qh, base + 15 * 3600 + 60))  # 22:01 Bangkok

    def test_no_events_fires_and_resolves(self):
        t0 = self.NOW
        with open(self.paths["events"], "a") as f:
            f.write(json.dumps({"ts": t0, "event": "run_start", "project": "shop-api", "run_id": "run-x"}) + "\n")
        ingest.run(self.conn, self.paths, cfg())
        doc = self.doc()
        doc["rules"] = [r for r in doc["rules"] if r["id"] == "silent"]
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, t0 + 600), now=t0 + 600, sender=self.sender)
        self.assertEqual(self.sent, [])
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, t0 + 1200), now=t0 + 1200, sender=self.sender)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][1]["status"], "firing")
        with open(self.paths["events"], "a") as f:
            f.write(json.dumps({"ts": t0 + 1300, "event": "run_result", "project": "shop-api", "run_id": "run-x"}) + "\n")
        ingest.run(self.conn, self.paths, cfg())
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, t0 + 1400), now=t0 + 1400, sender=self.sender)
        self.assertEqual(self.sent[-1][1]["status"], "resolved")

    def test_failed_delivery_is_retried(self):
        doc = self.doc()
        doc["rules"] = [r for r in doc["rules"] if r["id"] == "budget"]
        now = self.exp["base"] + 21 * 86400 + 20 * 3600

        def boom(url, body, headers):
            raise urllib.error.URLError("offline")
        r = alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now), now=now, sender=boom)
        self.assertFalse(r["deliveries"][0]["ok"])
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now + 300), now=now + 300, sender=self.sender)
        self.assertEqual(len(self.sent), 1)

    def test_transport_formats(self):
        p = {"severity": "critical", "status": "firing", "summary": "Guardrail G3 hit", "project": "shop-api", "task_id": "T1",
             "inspect": {"command": "orch-dashboard --json --project shop-api --task T1", "url": "http://127.0.0.1:8765/"},
             "dedup_key": "k"}
        s = alerts.format_for("slack", [p])
        self.assertIn("text", s)
        self.assertEqual(s["blocks"][0]["type"], "section")
        d = alerts.format_for("discord", [p] * 12)
        self.assertLessEqual(len(d["content"]), 2000)
        self.assertLessEqual(len(d["embeds"]), 10)
        os.environ["AGENTDASH_LINE_TOKEN"], os.environ["AGENTDASH_LINE_TO"] = "tok", "U123"
        try:
            ok, err = alerts.deliver({"type": "line"}, [p], self.sender)
        finally:
            del os.environ["AGENTDASH_LINE_TOKEN"], os.environ["AGENTDASH_LINE_TO"]
        url, body, headers = self.sent[-1]
        self.assertTrue(ok)
        self.assertEqual(url, "https://api.line.me/v2/bot/message/push")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(body["to"], "U123")
        self.assertEqual(body["messages"][0]["type"], "text")
        ok, err = alerts.deliver({"type": "slack", "url_env": "AGENTDASH_UNSET_X"}, [p], self.sender)
        self.assertFalse(ok)
        self.assertTrue(err.startswith("skipped"))

    def test_example_rules_file_loads(self):
        doc = alerts.load_rules(os.path.join(PKG_DIR, "alerts.example.yaml"))
        kinds = {r["kind"] for r in doc["rules"]}
        self.assertTrue({"task_stuck", "guardrail_hit", "cost_over_budget", "advisor_fix_rate", "no_events"} <= kinds)
        alerts.evaluate(self.conn, doc, self.NOW)


class TestOtlpReceiver(Base):
    def test_receiver_roundtrip(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        out = os.path.join(d, "otel.jsonl")
        holder = {}
        ready = threading.Event()

        def run():
            srv = otlp.ThreadingHTTPServer(("127.0.0.1", 0), otlp.make_handler(otlp._Writer(out)))
            holder["srv"] = srv
            ready.set()
            srv.serve_forever()
        threading.Thread(target=run, daemon=True).start()
        ready.wait(5)
        port = holder["srv"].server_address[1]
        with open(os.path.join(self.fx, "otel.jsonl")) as f:
            sample = [json.loads(x) for x in f if '"logs"' in x][0]["body"]
        body = json.dumps(sample).encode()

        def post(path, data, ctype="application/json", enc=None):
            h = {"Content-Type": ctype}
            if enc:
                h["Content-Encoding"] = enc
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
        self.assertEqual(post("/v1/logs", body), 200)
        self.assertEqual(post("/v1/logs", gzip.compress(body), enc="gzip"), 200)
        self.assertEqual(post("/v1/logs", b"\x0a\x01", "application/x-protobuf"), 415)
        self.assertEqual(post("/v1/nope", body), 404)
        self.assertEqual(post("/v1/logs", b"{bad"), 400)
        holder["srv"].shutdown()
        holder["srv"].server_close()
        with open(out) as f:
            text = f.read()
        self.assertNotIn("SECRET PROMPT", text)
        conn = store.connect(":memory:")
        r = ingest.run(conn, {"events": os.path.join(d, "none"), "otel": out}, cfg())
        self.assertEqual(r["otel"]["logs"], 1)               # identical records are deduplicated
        self.assertEqual(conn.execute("SELECT name FROM otel_logs").fetchone()[0], "api_request")

    def test_refuses_non_loopback(self):
        with self.assertRaises(SystemExit):
            otlp.serve("/tmp/x", host="0.0.0.0", port=0)
        with self.assertRaises(SystemExit):
            server.serve({}, {}, host="0.0.0.0", port=0)


class TestOutputs(Base):
    def setUp(self):
        self.conn, self.paths = self.fresh()

    def cli(self, *args):
        from agentdash import cli
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = cli.main(["--dir", self.paths["dir"], "--now", str(self.NOW), *args])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_cli_json(self):
        out = json.loads(self.cli("--json", "--since", "60d"))
        self.assertEqual(out["schema"], "agentdash.metrics/v1")
        self.assertEqual(out["progress"]["done"], self.exp["done"])
        one = json.loads(self.cli("--json", "--project", "shop-api", "--task", "T2"))
        self.assertTrue(one["tasks"] and all(t["task"] == "T2" and t["project"] == "shop-api" for t in one["tasks"]))
        legacy = json.loads(self.cli("--json", "--legacy"))
        self.assertIn("performance", legacy)

    def test_cli_reports(self):
        md = self.cli("--report", "weekly")
        self.assertIn("# Agent workflow — weekly report", md)
        self.assertIn("## Weekly trend", md)
        self.assertIn("Fake-WORKS rate", md)
        self.assertIn("| Metric |", self.cli("--report", "daily", "--project", "data-pipeline"))

    def test_cli_since_filter(self):
        a = json.loads(self.cli("--json", "--since", "2d"))
        b = json.loads(self.cli("--json", "--since", "60d"))
        self.assertLess(a["metrics"]["tasks_done"]["value"], b["metrics"]["tasks_done"]["value"])

    def test_snapshot_self_contained(self):
        path = os.path.join(self.paths["dir"], "snap.html")
        self.cli("--snapshot", path)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("window.__SNAPSHOT__", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("SECRET PROMPT", html)
        blob = html.split("window.__SNAPSHOT__ = ", 1)[1].split(";</script>", 1)[0]
        data = json.loads(blob.replace("<\\/", "</"))
        self.assertEqual(data["v1"]["progress"]["done"], self.exp["done"])

    def test_cli_spec_and_tick(self):
        self.assertIn("`fake_works_pct`", self.cli("--spec"))
        out = json.loads(self.cli("--tick", "--rules", os.path.join(PKG_DIR, "alerts.example.yaml"), "--dry-run"))
        self.assertIn("alerts", out)

    def test_api(self):
        holder, ready = {}, threading.Event()
        server.Handler.paths, server.Handler.cfg = self.paths, cfg()

        def run():
            srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            holder["srv"] = srv
            ready.set()
            srv.serve_forever()
        threading.Thread(target=run, daemon=True).start()
        ready.wait(5)
        base = f"http://127.0.0.1:{holder['srv'].server_address[1]}"

        def get(p):
            with urllib.request.urlopen(base + p, timeout=10) as r:
                return r.status, r.read().decode()
        try:
            s, body = get("/api/v1/metrics?since=0")
            self.assertEqual(json.loads(body)["metrics"]["tasks_done"]["value"], self.exp["done"])
            s, body = get("/api/state?project=shop-api")
            self.assertEqual(json.loads(body)["progress"]["by_state"]["done"], self.exp["projects"]["shop-api"]["done"])
            for p in ("/api/v1/health", "/api/v1/spec", "/api/v1/trends", "/api/v1/tasks?state=stuck", "/api/v1/guardrails",
                      "/api/v1/alerts", "/api/v1/projects", "/", "/snapshot.html"):
                self.assertEqual(get(p)[0], 200, p)
            stuck = json.loads(get("/api/v1/tasks?state=stuck&since=0")[1])["tasks"]
            self.assertEqual(len(stuck), self.exp["stuck"])
            with self.assertRaises(urllib.error.HTTPError) as cm:
                get("/api/v1/nope")
            self.assertEqual(cm.exception.code, 404)
        finally:
            holder["srv"].shutdown()
            holder["srv"].server_close()


class TestRetention(Base):
    def test_rollup_then_delete(self):
        conn, p = self.fresh()
        metrics.rollup(conn, now=self.NOW)
        before = metrics.trends(conn, weeks=52, now=self.NOW)["series"]["tasks_done"]
        far = self.NOW + 400 * 86400
        r = retention.apply(conn, cfg(), now=far)
        self.assertGreater(r["deleted"]["raw_events"], 0)
        self.assertGreater(r["deleted"]["dispatches"], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0], 0)
        after = metrics.trends(conn, weeks=52, now=self.NOW)["series"]["tasks_done"]
        self.assertEqual(before, after)                       # daily aggregates are kept forever
        self.assertEqual(retention.maybe_daily(conn, cfg(), now=far + 60)["skipped"], "ran within the last 24h")


class TestYamlLite(unittest.TestCase):
    def test_subset(self):
        doc = yaml_lite.load("""
# comment
a: 1
b: "x # not a comment"
c: [G3, G8]
d:
  e: true
  f: 2.5
rules:
  - id: one
    kind: k   # trailing comment
    list:
      - x
      - y
  - id: two
    m: {k: v}
""", force_lite=True)
        self.assertEqual(doc["a"], 1)
        self.assertEqual(doc["b"], "x # not a comment")
        self.assertEqual(doc["c"], ["G3", "G8"])
        self.assertEqual(doc["d"], {"e": True, "f": 2.5})
        self.assertEqual(doc["rules"][0], {"id": "one", "kind": "k", "list": ["x", "y"]})
        self.assertEqual(doc["rules"][1]["m"], {"k": "v"})

class TestReviewFixes(Base):
    """Regression tests for the 2026-11-25 code review (findings 1-10)."""

    def setUp(self):
        self.conn, self.paths = self.fresh()
        self.sent = []

    def sender(self, url, body, headers):
        self.sent.append((url, body, headers))
        return 200

    def append(self, *events):
        with open(self.paths["events"], "a") as f:
            for e in events:
                f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")
        return ingest.run(self.conn, self.paths, cfg())

    # 1
    def test_bad_guardrail_name_does_not_break_metrics(self):
        r = self.append({"ts": self.NOW - 60, "event": "guardrail_hit", "guardrail": "GX", "project": "shop-api"},
                        {"ts": self.NOW - 50, "event": "guardrail_hit", "guardrail": "G3a", "project": "shop-api"},
                        {"ts": self.NOW - 40, "event": "guardrail_hit", "guardrail": "g03", "project": "shop-api"})
        self.assertEqual(r["events"]["bad_guardrail"], 2)
        # an old row with a bad name (written before this fix) must not crash the sort either
        self.conn.execute("INSERT INTO guardrail_hits(line_hash,ts,project,guardrail,source) VALUES ('x',?,'p','GX','event')",
                          (self.NOW - 30,))
        res = metrics.compute(self.conn, since=0, now=self.NOW)
        self.assertEqual(res["guardrails"]["by_guardrail"]["G3"]["hits"], self.exp["guardrail_hits"]["G3"] + 1)
        self.assertEqual(list(res["guardrails"]["by_guardrail"])[-1], "GX")
        self.assertEqual(parse.guardrail_name(" g8 "), "G8")
        self.assertIsNone(parse.guardrail_name(3))

    # 2
    def test_dry_run_tick_writes_nothing(self):
        from agentdash import cli
        self.append({"ts": self.NOW - 40 * 86400, "event": "PostToolUse", "tool": "Bash", "project": "old"})
        with open(self.paths["events"], "a") as f:
            f.write(json.dumps({"ts": self.NOW - 10, "event": "PostToolUse", "tool": "Read", "project": "new"}) + "\n")

        def snap():
            c = sqlite3.connect(self.paths["db"])
            out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                   ("raw_events", "daily_aggregates", "alert_state", "alert_log", "ingest_state", "rollup_dirty")}
            out["offsets"] = c.execute("SELECT * FROM ingest_state ORDER BY source").fetchall()
            c.close()
            return out
        before = snap()
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            rc = cli.main(["--dir", self.paths["dir"], "--db", self.paths["db"], "--now", str(self.NOW),
                           "--tick", "--dry-run", "--rules", "/nonexistent.yaml"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["retention"], {"skipped": "dry run"})
        self.assertEqual(out["ingest"]["events"]["new"], 1)   # it did read the new line, in memory
        self.assertEqual(snap(), before)

    # 3
    def test_broken_file_channel_and_bad_rule_do_not_stop_the_tick(self):
        bad = os.path.join(self.tmp, "not-a-dir")
        open(bad, "w").close()
        doc = {"version": 1, "defaults": {"max_per_channel_per_run": 50},
               "channels": {"hook": {"type": "webhook", "url": "http://example.invalid/h"},
                            "log": {"type": "file", "path": os.path.join(bad, "x.log")}},
               "rules": [{"id": "nope", "kind": "no_such_kind"},
                         {"id": "m", "kind": "metric_threshold", "metric": "no_such_metric", "value": 1},
                         {"id": "budget", "kind": "cost_over_budget", "budget_usd": 0.01, "severity": "high",
                          "channels": ["hook", "log"]}]}
        ok, err = alerts.deliver(doc["channels"]["log"], [{"x": 1}])
        self.assertFalse(ok)
        self.assertIn("Error", err)
        now = self.exp["base"] + 21 * 86400 + 20 * 3600
        errors = []
        found = alerts.evaluate(self.conn, doc, now, errors=errors)
        self.assertEqual([e["rule"] for e in errors], ["nope", "m"])
        self.assertEqual(len(found), 1)
        alerts.process(self.conn, doc, found, now=now, sender=self.sender)
        self.assertEqual(len(self.sent), 1)
        row = self.conn.execute("SELECT send_count, held FROM alert_state WHERE rule_id='budget'").fetchone()
        self.assertEqual(tuple(row), (1, 0))          # delivered on the webhook, so not re-sent
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now + 300, errors=[]), now=now + 300, sender=self.sender)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(alerts.check_rules(doc)[:2], ["rule nope: unknown kind 'no_such_kind'; rule skipped",
                                                       "rule m: unknown metric 'no_such_metric'; rule skipped"])

    # 4
    def test_redaction_covers_common_secret_shapes(self):
        for secret in ['{"password": "hunter2"}', '{"api_key":"abc123"}', 'MY_SECRET_KEY=abc',
                       'AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI', 'Authorization: Bearer abcdefghijklmnop',
                       'sk-proj-abcdefghij_klmnopqrstuv-wxyz', 'AIza' + 'A' * 35]:
            out = parse.redact(secret)
            self.assertIn("[REDACTED]", out, secret)
            for leak in ("hunter2", "abc123", "wJalr", "abcdefghijklmnop", "klmnop", "AAAA"):
                self.assertNotIn(leak, out, secret)
        self.assertEqual(parse.redact("input_tokens=500 tokens: 12"), "input_tokens=500 tokens: 12")

    # 5
    def test_hook_redacts_kept_text_and_drops_text_without_parser(self):
        h = TestHook("test_noop_without_env")
        h.tmp = self.tmp
        post = json.loads(TestHook.POST)
        post["tool_input"]["description"] = "[T1] rotate api_key=sk-abc123SECRETabc123SECRET"
        post["tool_response"]["content"][0]["text"] += "\napi_key=sk-abc123SECRET"
        # parser available: description redacted at capture
        r, ev = h._run(json.dumps(post), {"AGENT_WORKFLOW": "1"})
        self.assertNotIn("SECRET", ev[0]["description"])
        # parser not importable + LOG_CONTENT=1: result_text is dropped, not written raw
        r, ev = h._run(json.dumps(post), {"AGENT_WORKFLOW": "1", "AGENT_DASHBOARD_LOG_CONTENT": "1", "PYTHONPATH": ""})
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("result_text", ev[0])
        self.assertEqual(ev[0]["result_text_dropped"], "parser_unavailable")
        self.assertNotIn("SECRET", json.dumps(ev[0]))
        r, ev = h._run("{}", {"AGENT_WORKFLOW": "1"}, ["--guardrail", "G3", "--reason", "token=abcdef123"])
        self.assertNotIn("abcdef123", ev[0]["reason"])

    # 6
    def test_install_keeps_user_hooks(self):
        home = tempfile.mkdtemp(dir=self.tmp)
        ch = os.path.join(home, "claude")
        os.makedirs(ch)
        user = {"model": "x", "hooks": {"PostToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/log_event.py"'},
                                       {"type": "command", "command": "my-audit-logger --keep"}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/local/bin/my_log_event.py"}]},
            {"matcher": "Edit", "hooks": [{"type": "command",
                                           "command": "python3 ~/.claude/hooks/log_event.py --guardrail G3 --reason x"}]}]}}
        sp = os.path.join(ch, "settings.json")
        with open(sp, "w") as f:
            json.dump(user, f)
        env = {**os.environ, "CLAUDE_HOME": ch, "BIN_DIR": os.path.join(home, "bin"), "SERVICE_HOME": home}

        def install(*a):
            r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), *a], env=env, capture_output=True, text=True,
                               timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)

        def commands():
            with open(sp) as f:
                d = json.load(f)
            return [h["command"] for g in d.get("hooks", {}).get("PostToolUse", []) for h in g["hooks"]]
        install()
        mine = ["my-audit-logger --keep", "/usr/local/bin/my_log_event.py",
                "python3 ~/.claude/hooks/log_event.py --guardrail G3 --reason x"]
        self.assertEqual(commands()[:3], mine)
        self.assertEqual(len(commands()), 4)            # plus exactly one of ours
        with open(sp) as f:
            first = f.read()
        install()
        with open(sp) as f:
            self.assertEqual(f.read(), first)           # idempotent
        install("--uninstall")
        self.assertEqual(commands(), mine)
        with open(sp, "w") as f:
            f.write("// comment\n{}")
        r = subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not valid JSON", r.stderr)

    # 7
    def test_poison_line_is_skipped_not_retried(self):
        r = self.append({"ts": self.NOW - 30, "event": "PostToolUse", "tool": "Bash", "session_id": {"a": 1}},
                        {"ts": self.NOW - 20, "event": "PostToolUse", "tool": "Bash", "agent_type": 5, "project": "p"},
                        {"ts": self.NOW - 10, "event": "PostToolUse", "tool": "Read", "project": "p", "session_id": "ok"})
        self.assertEqual((r["events"]["new"], r["events"]["bad"]), (1, 2))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM raw_events WHERE session_id='ok'").fetchone()[0], 1)
        self.assertEqual(ingest.run(self.conn, self.paths, cfg())["events"]["lines"], 0)

    # 8
    def test_skipped_channel_is_retried_and_guardrail_keys_survive_retention(self):
        doc = {"version": 1, "defaults": {}, "channels": {"hook": {"type": "webhook", "url_env": "AGENTDASH_TEST_HOOK"}},
               "rules": [{"id": "budget", "kind": "cost_over_budget", "budget_usd": 0.01, "severity": "high",
                          "channels": ["hook"]}]}
        now = self.exp["base"] + 21 * 86400 + 20 * 3600
        os.environ.pop("AGENTDASH_TEST_HOOK", None)
        r = alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now), now=now, sender=self.sender)
        self.assertTrue(r["deliveries"][0]["error"].startswith("skipped"))
        os.environ["AGENTDASH_TEST_HOOK"] = "http://example.invalid/h"
        try:
            alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, now + 300), now=now + 300, sender=self.sender)
        finally:
            os.environ.pop("AGENTDASH_TEST_HOOK", None)
        self.assertEqual(len(self.sent), 1)
        # guardrail alert keys use line_hash, so a reused integer id cannot suppress a new hit
        g = {"id": "g", "kind": "guardrail_hit", "guardrails": ["G3"], "lookback": "60d"}
        keys = {a["dedup_key"] for a in alerts.k_guardrail_hit(self.conn, g, self.NOW, {})}
        self.assertTrue(keys and all(len(k.split(":")) == 3 and k.endswith(":G3") for k in keys))

    # 9
    def test_late_events_recompute_an_old_day(self):
        day_ts = self.exp["base"] + 86400 * 2 + 3600
        day = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(day_ts))
        metrics.rollup(self.conn, now=self.NOW)
        self.conn.execute("DELETE FROM rollup_dirty")
        q = "SELECT num FROM daily_aggregates WHERE day=? AND project='*' AND metric='tool_failure_pct'"
        before = self.conn.execute(q, (day,)).fetchone()
        self.append({"ts": day_ts, "event": "PostToolUseFailure", "tool": "Bash", "project": "shop-api", "session_id": "late"})
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM rollup_dirty WHERE day=?", (day,)).fetchone())
        metrics.rollup(self.conn, now=self.NOW)
        after = self.conn.execute(q, (day,)).fetchone()
        self.assertEqual((after[0] or 0), (before[0] if before else 0) + 1)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM rollup_dirty WHERE day=?", (day,)).fetchone())

    # 10
    def test_from_memory_none_variants(self):
        def fm(v):
            return parse.report(f"FROM MEMORY: {v}\nCONFIDENCE: high\n", "advisor")["from_memory"]
        for v in ("none", "none (no relevant lesson)", "None.", "n/a", "-", "**none**"):
            self.assertEqual(fm(v), "none", v)
        self.assertEqual(fm("[L12] retry flaky test"), "hit")
        self.assertEqual(parse.report("FROM MEMORY:\nCONFIDENCE: high", "advisor")["from_memory"], "none")

    def test_resolved_notice_waits_for_quiet_hours_to_end(self):
        t0 = self.NOW
        self.append({"ts": t0, "event": "run_start", "project": "shop-api", "run_id": "run-q"})
        qh = {"start": "00:00", "end": "06:00", "tz": "UTC"}
        doc = {"version": 1, "defaults": {"quiet_hours": qh}, "channels": {"hook": {"type": "webhook", "url": "http://x.invalid"}},
               "rules": [{"id": "silent", "kind": "no_events", "minutes": 15, "severity": "critical",
                          "notify_resolved": True, "channels": ["hook"]}]}
        qh["allow_severity"] = ["critical"]
        fire = t0 + 1200                                   # 00:20 UTC, quiet, but critical is allowed
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, fire), now=fire, sender=self.sender)
        self.assertEqual([b["status"] for _, b, _ in self.sent], ["firing"])
        self.append({"ts": t0 + 1300, "event": "run_result", "project": "shop-api", "run_id": "run-q"})
        quiet = t0 + 1400
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, quiet), now=quiet, sender=self.sender)
        self.assertEqual(len(self.sent), 1)                # resolved notice held
        after = t0 + 7 * 3600
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, after), now=after, sender=self.sender)
        self.assertEqual([b["status"] for _, b, _ in self.sent], ["firing", "resolved"])
        alerts.process(self.conn, doc, alerts.evaluate(self.conn, doc, after + 300), now=after + 300, sender=self.sender)
        self.assertEqual(len(self.sent), 2)

    def test_cumulative_metric_points_are_stored_as_deltas(self):
        def pt(t, v):
            return {"timeUnixNano": str(int(t * 1e9)), "startTimeUnixNano": "1", "asDouble": v,
                    "attributes": [{"key": "session.id", "value": {"stringValue": "cum-1"}}]}
        body = {"resourceMetrics": [{"scopeMetrics": [{"metrics": [{"name": "claude_code.cost.usage", "sum": {
            "aggregationTemporality": 2, "isMonotonic": True,
            "dataPoints": [pt(self.NOW - 30, 1.0), pt(self.NOW - 20, 1.5), pt(self.NOW - 10, 2.5)]}}]}]}]}
        with open(self.paths["otel"], "a") as f:
            f.write(json.dumps(body) + "\n")
        ingest.run(self.conn, self.paths, cfg())
        total = self.conn.execute("SELECT SUM(value) FROM otel_metric_points WHERE session_id='cum-1'").fetchone()[0]
        self.assertAlmostEqual(total, 2.5)

    def test_since_accepts_trailing_z_and_quiet_hours_accept_ints(self):
        self.assertEqual(server.parse_since("2026-11-02T00:00:00Z"), 1793577600.0)
        qh = {"start": 1320, "end": 420, "tz": "UTC"}      # PyYAML reads unquoted 22:00 as 1320
        self.assertTrue(alerts.in_quiet_hours(qh, self.exp["base"] + 23 * 3600))
        self.assertFalse(alerts.in_quiet_hours(qh, self.exp["base"] + 12 * 3600))
        self.assertFalse(alerts.in_quiet_hours({"start": "bogus"}, self.NOW))


if __name__ == "__main__":
    unittest.main()
