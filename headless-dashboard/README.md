# Orchestrator · Worker · Advisor + dashboard v2 (headless-first)

**v2 summary (English).** `orch-dashboard` now ingests the hook log and Claude Code's OpenTelemetry
export into SQLite, using byte offsets, so it survives rotation and truncation. One metrics module
feeds the CLI, the JSON API, the live UI, a static HTML snapshot and the YAML alert rules. Alerts go to
Slack, Discord, LINE Messaging API or a generic webhook, with dedup and quiet hours, from a 5-minute
timer. Report and prompt text are not stored unless you opt in. Python 3.10+, standard library only.

| Doc | Content |
|---|---|
| [docs/design.md](docs/design.md) | architecture (Mermaid), data model, OTel join, retention, metric spec, alerts, plan |
| [docs/adr.md](docs/adr.md) | D1–D5 decisions |
| [docs/research.md](docs/research.md) | R1–R5 with sources |
| [docs/verification-log.md](docs/verification-log.md) | commands run, output, screenshots |

```bash
./install.sh                    # install / upgrade (idempotent; merges ~/.claude/settings.json)
./install.sh --with-services    # + alert timer and OTLP receiver (launchd on macOS, systemd --user on Linux)
./install.sh --dry-run          # show what would change
./install.sh --uninstall        # remove everything except your data
```

```bash
orch-dashboard                           # live UI http://127.0.0.1:8765 (as in v1)
orch-dashboard --json --project my-app --since 7d [--task T3]
orch-dashboard --report daily|weekly     # markdown
orch-dashboard --snapshot                # one self-contained HTML file
orch-dashboard --tick                    # ingest + alerts + retention (what the timer runs)
orch-dashboard --otlp                    # OTLP/HTTP JSON receiver on 127.0.0.1:4318
orch-dashboard --spec                    # metric definitions
python3 -m unittest discover -s tests    # 60 tests on the recorded fixture
```

Configure alerts in `~/.claude/agent-dashboard/alerts.yaml`. Put webhook secrets in
`~/.claude/agent-dashboard/alerts.env` (mode 600). Guardrail hooks report hits with
`python3 ~/.claude/hooks/log_event.py --guardrail G3 --reason "..."`.

---

## ภาษาไทย: Orchestrator · Worker · Advisor — global setup

ติดตั้งครั้งเดียวต่อเครื่อง ใช้ได้กับทุกโปรเจกต์ ไม่มีไฟล์ไหนถูกเขียนลงใน repo

## ติดตั้ง
```bash
./install.sh
export PATH="$HOME/.local/bin:$PATH"   # ถ้ายังไม่มี
```

สิ่งที่ติดตั้งไปที่เครื่อง:
| ที่อยู่ | เนื้อหา |
|---|---|
| `~/.claude/agents/orchestrator.md` | Orchestrator (รันเป็น main session ด้วย `--agent`) |
| `~/.claude/agents/worker.md` | Worker subagent |
| `~/.claude/agents/advisor.md` | Advisor subagent (`memory: user`) |
| `~/.claude/hooks/log_event.py` | hook เก็บ event ให้ dashboard (ทำงานเฉพาะเมื่อ `AGENT_WORKFLOW=1`) |
| `~/.claude/settings.json` | เพิ่ม hook entries (ไม่แตะค่าอื่น, สำรองไฟล์เดิมเป็น `.bak-<time>`) |
| `~/.claude/agent-memory/advisor/` | memory ของ Advisor ทุกโปรเจกต์ (สร้างโดย Advisor เอง) |
| `~/.claude/agent-dashboard/` | ไฟล์ log และ dashboard |
| `~/.claude/agent-dashboard/agentdash/` | แพ็กเกจ dashboard v2 (SQLite, metrics, alerts, OTLP receiver) |
| `~/.claude/agent-dashboard/alerts.yaml`, `alerts.env` | กฎแจ้งเตือน และ secret ของ webhook (สร้างครั้งแรกเท่านั้น ไม่เขียนทับ) |
| `~/.local/bin/orch`, `orch-headless`, `orch-dashboard`, `orch-dashboard-tick` | คำสั่งที่ใช้งาน |

ติดตั้งซ้ำได้ปลอดภัย ถอนการติดตั้งด้วย `./install.sh --uninstall`

## ใช้งาน
```bash
cd ~/code/my-app
orch                          # เปิด session แบบ interactive โดย main session เป็น Orchestrator
orch-headless "Fix the failing checkout tests"   # รันเบื้องหลัง บันทึก cost ให้ dashboard
orch-dashboard                # http://127.0.0.1:8765  (เลือกโปรเจกต์จาก dropdown ได้)
orch-dashboard --project my-app
```

## ทำงานอย่างไร
- `orch` ตั้ง `AGENT_WORKFLOW=1` แล้วเรียก `claude --agent orchestrator` ใน `--agent` mode subagent ถูกจำกัดให้เรียกได้เฉพาะ `Agent(worker, advisor)` ตาม frontmatter
- Worker และ Advisor เป็น subagent ที่ Orchestrator เรียกผ่าน Agent tool, Advisor เก็บ memory ที่ `~/.claude/agent-memory/advisor/` แยกไฟล์ตามโปรเจกต์ (`projects/<project>.md`) และใช้ `topics/` สำหรับความรู้ข้ามโปรเจกต์
- hook บันทึกทุก dispatch พร้อมชื่อโปรเจกต์ (ชื่อโฟลเดอร์) และ dashboard รวมทุกโปรเจกต์ไว้ที่เดียว

## ข้อควรระวัง
- Plugin subagent ไม่รองรับ `hooks`, `permissionMode`, `mcpServers` จึงใช้วิธีวางไฟล์ไว้ใน `~/.claude/agents/` แทน
- `memory` ของ subagent ต้องมี Read/Write/Edit (ตั้งไว้ใน advisor.md แล้ว) ถ้าไม่เกิดไฟล์ `MEMORY.md` ให้ตรวจสอบหลังใช้งานครั้งแรก
- v2: ค่า token/cost ของ subagent มาจาก OpenTelemetry (`orch` ตั้งค่า env ให้ผ่าน `otel-env.sh`) ถ้าไม่มี OTel จะใช้ค่าจาก hook แทน ดูแหล่งที่ใช้ได้ที่ `join` และ `cost_sources` ใน `orch-dashboard --json`
- v2: ไม่เก็บข้อความ report/prompt ตามค่าเริ่มต้น ถ้าต้องการให้ตั้ง `AGENT_DASHBOARD_LOG_CONTENT=1`
- Advisor เขียนได้เฉพาะโฟลเดอร์ memory ของตัวเอง แต่ `Bash` ยังสั่งคำสั่งอะไรก็ได้ตามสิทธิ์ของ session ควรใช้กับโปรเจกต์ที่ไว้ใจได้
