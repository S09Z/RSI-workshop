"""orch-dashboard: one command for every output. No browser is needed for anything but --serve.

  orch-dashboard                          live UI on http://127.0.0.1:8765 (same as v1)
  orch-dashboard --json [--project P] [--since 7d] [--task T3]
  orch-dashboard --report daily|weekly [--project P] [--out FILE]
  orch-dashboard --snapshot [FILE]        self-contained HTML (default: snapshots/<time>.html)
  orch-dashboard --trends [--weeks 12]    weekly trends as JSON
  orch-dashboard --spec                   metric definitions (markdown table)
  orch-dashboard --ingest                 ingest new lines and exit
  orch-dashboard --alerts [--dry-run]     evaluate alert rules and send
  orch-dashboard --tick                   ingest + rollup + alerts (+ retention once a day): for the timer
  orch-dashboard --retention              apply the retention policy now
  orch-dashboard --otlp                   run the OTLP/HTTP JSON receiver on 127.0.0.1:4318
"""
import argparse
import datetime as _dt
import json
import os
import sys
import time

from . import alerts, config, ingest, metrics, report, retention, server, store


def _parser():
    p = argparse.ArgumentParser(prog="orch-dashboard", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="print the metrics document and exit")
    p.add_argument("--report", choices=["daily", "weekly"], help="print a markdown report and exit")
    p.add_argument("--snapshot", nargs="?", const="", metavar="FILE", help="write a static HTML snapshot")
    p.add_argument("--trends", action="store_true")
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--spec", action="store_true")
    p.add_argument("--ingest", action="store_true")
    p.add_argument("--alerts", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="with --alerts/--tick: print, do not send or record")
    p.add_argument("--tick", action="store_true")
    p.add_argument("--retention", action="store_true")
    p.add_argument("--otlp", action="store_true")
    p.add_argument("--project", default=None)
    p.add_argument("--since", default=None, help="24h, 7d, 2w, ISO date or epoch")
    p.add_argument("--until", default=None)
    p.add_argument("--task", default=None, help="with --json: only this task ID")
    p.add_argument("--out", default=None)
    p.add_argument("--legacy", action="store_true", help="with --json: v1 /api/state shape")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--dir", default=None, help="data dir (default ~/.claude/agent-dashboard)")
    p.add_argument("--log", default=None, help="events.jsonl path (v1 flag)")
    p.add_argument("--db", default=None)
    p.add_argument("--rules", default=None, help="alerts.yaml path")
    p.add_argument("--now", type=float, default=None, help=argparse.SUPPRESS)
    return p


def main(argv=None):
    a = _parser().parse_args(argv)
    paths = config.paths(a.dir)
    if a.log:
        paths["events"] = a.log
    if a.db:
        paths["db"] = a.db
    if a.rules:
        paths["alerts"] = a.rules
    cfg = config.load(os.path.join(paths["dir"], "config.yaml"))
    srv = cfg["server"]

    if a.otlp:
        from . import otlp
        port = a.port or srv.get("otlp_port", 4318)
        print(f"OTLP/HTTP JSON receiver on http://127.0.0.1:{port}  -> {paths['otel']}", file=sys.stderr)
        otlp.serve(paths["otel"], "127.0.0.1", port, keep_content=cfg["privacy"]["store_result_text"])
        return 0

    conn = store.connect(paths["db"])
    now = a.now or time.time()
    since, until = server.parse_since(a.since, now), server.parse_since(a.until, now)
    quiet_ingest = a.json or a.report or a.trends or a.spec

    def do_ingest():
        r = ingest.run(conn, paths, cfg)
        metrics.rollup(conn, now=now)
        return r

    if a.spec:
        print("| name | title | formula | source | unit | min sample | alert |\n|---|---|---|---|---|---:|---|")
        for m in metrics.spec():
            print(f"| `{m['name']}` | {m['title']} | {m['formula']} | {m['source']} | {m['unit']} | {m['min_sample']} | {m['alert']} |")
        return 0
    if a.ingest:
        print(json.dumps(do_ingest(), indent=2))
        return 0
    if a.retention:
        do_ingest()
        print(json.dumps(retention.apply(conn, cfg, now=now), indent=2))
        return 0
    if a.alerts or a.tick:
        out = {"ingest": do_ingest()}
        out["alerts"] = alerts.run(conn, paths["alerts"], cfg, now=now, dry_run=a.dry_run)
        if a.tick:
            out["retention"] = retention.maybe_daily(conn, cfg, now=now)
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        return 0
    if quiet_ingest or a.snapshot is not None:
        do_ingest()
    if a.json:
        res = metrics.compute(conn, project=a.project, since=since, until=until, now=now)
        if a.task:
            res["tasks"] = [t for t in res["tasks"] if t["task"] == a.task.upper()]
            res["timeline"] = [d for d in res["timeline"] if d["task"] == a.task.upper()]
        if a.legacy:
            res = metrics.legacy_state(res)
        _emit(json.dumps(res, indent=2, ensure_ascii=False, default=str), a.out)
        return 0
    if a.report:
        _emit(report.markdown(conn, a.report, a.project, now=now), a.out)
        return 0
    if a.trends:
        _emit(json.dumps(metrics.trends(conn, a.project, a.weeks, now=now), indent=2), a.out)
        return 0
    if a.snapshot is not None:
        path = a.snapshot or os.path.join(paths["snapshots"], _dt.datetime.now().strftime("%Y%m%d-%H%M%S") +
                                          (f"-{a.project}" if a.project else "") + ".html")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(report.snapshot_html(conn, a.project, now=now))
        print(path)
        return 0
    conn.close()
    host, port = a.host or srv.get("host", "127.0.0.1"), a.port or srv.get("port", 8765)
    print(f"Dashboard: http://{host}:{port}   (log: {paths['events']}, db: {paths['db']})")
    server.serve(paths, cfg, host, port)
    return 0


def _emit(text, out):
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(out)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
