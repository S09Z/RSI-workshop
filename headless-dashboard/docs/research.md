# Research log R1–R5

All sources were opened on **2026-11-25**. None of the pages showed a "last updated" date, so the date
given is the access date. GitHub figures (stars, last push, license) come from `gh api repos/<owner>/<repo>`
run at 2026-11-25 02:41 UTC. Quotes are kept short. Anything not found in a source is marked
**not verified**.

## R1. Claude Code OpenTelemetry today

Sources:
* "Monitoring", https://code.claude.com/docs/en/monitoring-usage (accessed 2026-11-25). Part of the
  event list, roughly `assistant_response` through `retention_sweep`, was read only as a summary; the
  attribute lists for those events are marked (s).
* "Observability with OpenTelemetry" (Agent SDK), https://code.claude.com/docs/en/agent-sdk/observability
  (accessed 2026-11-25).
* "Hooks reference", https://code.claude.com/docs/en/hooks (accessed 2026-11-25), for the join keys on the
  hook side.

**Enable / env vars.** `CLAUDE_CODE_ENABLE_TELEMETRY=1` (required). `OTEL_METRICS_EXPORTER`
(`console|otlp|prometheus|none`), `OTEL_LOGS_EXPORTER`, `OTEL_TRACES_EXPORTER` (beta).
`OTEL_EXPORTER_OTLP_PROTOCOL` = `grpc|http/json|http/protobuf`; it defaults to `http/protobuf` for an
http(s) endpoint from v2.1.323. `OTEL_EXPORTER_OTLP_ENDPOINT`, plus per-signal endpoint, protocol and
headers. Export intervals: metrics 60000 ms, logs 5000 ms, traces 5000 ms.
`OTEL_RESOURCE_ATTRIBUTES` takes `key=value`, comma-separated, with no spaces. Delta temporality is the
default. Cardinality switches: `OTEL_METRICS_INCLUDE_SESSION_ID` (default true), `…_VERSION` (false),
`…_ACCOUNT_UUID` (true).

**Metrics** (meter `com.anthropic.claude_code`): `claude_code.session.count`, `.lines_of_code.count`,
`.pull_request.count`, `.commit.count`, `.cost.usage` (USD), `.token.usage` (tokens; `type` =
input/output/cacheRead/cacheCreation), `.code_edit_tool.decision`, `.active_time.total` (s). Cost and
token metrics carry `model` and `query_source` (`main|subagent|auxiliary|…`). Agent, skill and MCP name
attribution requires `OTEL_LOG_TOOL_DETAILS`.

**Events (logs).** Every event has `session.id`, `event.name`, `event.timestamp` and `event.sequence`.
`prompt.id` links all events from one user prompt. `agent_id` / `parent_agent_id` are on events from
**v2.1.310** and are absent on main-session events. `tool_use_id` is on `tool_result`, `tool_decision`
and `safety_event`. `claude_code.user_prompt` carries `prompt_length`, and `prompt` only with
`OTEL_LOG_USER_PROMPTS=1`. `claude_code.api_request` (s) carries `model`, `cost_usd`, `duration_ms`,
`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `request_id` and
`query_source`. Also (s): `api_error`, `tool_result`, `tool_decision`, `subagent_completed` (`agent_type`,
`total_tokens`, `total_tool_uses`, `duration_ms`), `compaction`, `hook_execution_*`.

**Traces (beta).** Enabled by `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` plus `OTEL_TRACES_EXPORTER`; the
docs say "Tracing is off by default." Hierarchy: `claude_code.interaction` (one per user prompt) →
`claude_code.llm_request`, `claude_code.tool` (→ `.tool.blocked_on_user`, `.tool.execution`), and
`claude_code.hook`, which needs `ENABLE_BETA_TRACING_DETAILED` plus `BETA_TRACING_ENDPOINT`. **Subagent
nesting**: "When the Agent tool, or legacy Task tool, spawns a subagent, the subagent's API and tool
spans nest under the parent's `claude_code.tool` span." The SDK page adds that the whole delegation
chain "appears as one trace". `claude_code.tool` attributes include `tool_name`, `tool_use_id`,
`gen_ai.tool.call.id`, `subagent_type`, `agent_id`, `parent_agent_id` and `duration_ms`.
`claude_code.llm_request` carries `model`, `gen_ai.request.model`, `query_source`, `agent_id`, token
counts, `ttft_ms` and `success`. Stability: "Span names and attributes may change between releases."
`TRACEPARENT` is honoured in SDK and `claude -p` sessions, not in interactive ones.

**Not exported by default.** Prompt text (length only), assistant response text, tool input and
parameters, tool content in spans, raw API bodies (`OTEL_LOG_RAW_API_BODIES`), host name and ID,
repository attributes, and managed-settings values. Always present: `user.id`, an anonymous random ID.
Present under OAuth: `user.email`. Export failures are silent unless `CLAUDE_CODE_OTEL_DIAG_STDERR=1`
(v2.1.179+). Project and local `.claude/settings*.json` cannot set the exporter variables.

**Per-version caveats used in this design.** v2.1.310 (`agent_id` on events), v2.1.323 (default
protocol), v2.1.268 (many span attributes), v2.1.300 (cache 5m/1h token split), v2.1.326
(`OTEL_RESOURCE_INCLUDE_HOST`). The installed Claude Code version on this machine was **not checked**.

**Hook side of the join** ("Hooks reference"). Common input fields include `session_id`, `prompt_id`,
`transcript_path`, `cwd` and `hook_event_name`. `agent_type` is "present when the session uses --agent
or the hook fires inside a subagent". PreToolUse has `tool_use_id`; the PostToolUse example also has
`duration_ms`. PostToolUseFailure has `error` and `is_interrupt` (s). SubagentStop has `agent_id`,
`agent_type`, `agent_transcript_path` and `last_assistant_message` (s). `async: true` "runs in the
background without blocking". The default command-hook timeout is 600 s, and it is not enforced for
async hooks. When a PreToolUse hook exits 2, stderr becomes the denial reason.

## R2. OTel GenAI semantic conventions

Sources:
* "Moved: Generative AI semantic conventions", https://opentelemetry.io/docs/specs/semconv/gen-ai/
  (accessed 2026-11-25). The GenAI conventions now live in a separate repository.
* `open-telemetry/semantic-conventions-genai`, file `docs/gen-ai/gen-ai-agent-spans.md` and
  `docs/gen-ai/execute-tool.md`, read via the GitHub API (accessed 2026-11-25). Latest commit on main
  is 2026-11-24T23:34Z. No release tag was visible; the README's "Schema URL" section says TODO.

**Status.** "Development" for the document and for every attribute listed below.

**Spans we would emit.**
* `invoke_agent` (in-process agent). Span name `invoke_agent {gen_ai.agent.name}`, kind `INTERNAL`.
  `gen_ai.operation.name` Required. `gen_ai.agent.name` and `gen_ai.agent.description` Conditionally
  Required ("when available"). `gen_ai.conversation.id` Conditionally Required. `gen_ai.request.model`
  Recommended. `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` Recommended.
  `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions` and
  `gen_ai.tool.definitions` are **Opt-In**, meaning content is off unless enabled. The spec says not to
  report the span when the invocation is "an internal implementation detail" of another operation.
* `create_agent`: name `create_agent {gen_ai.agent.name}`; `gen_ai.provider.name` Required;
  `gen_ai.agent.id` Conditionally Required.
* `execute_tool`: name `execute_tool {gen_ai.tool.name}`, kind `INTERNAL`. `gen_ai.tool.name`
  Required. `gen_ai.tool.call.id` Conditionally Required. `gen_ai.tool.type` and
  `gen_ai.tool.description` Recommended.
* `gen_ai.conversation.id` is the attribute meant to propagate across nested instrumentations.

**What v2 does with this.** v2 emits no spans of its own; Claude Code already emits `claude_code.*`
spans, and they include `gen_ai.tool.call.id` and `gen_ai.request.model`. If we add spans later, for
example a "task" span per [Tn], the attributes to set are: `gen_ai.operation.name=invoke_workflow` for
the orchestrator loop and `invoke_agent` for worker and advisor dispatches; `gen_ai.agent.name`
(worker / advisor); `gen_ai.conversation.id` = Claude Code `session.id`; `gen_ai.tool.call.id` = the
Agent `tool_use_id`; usage tokens. Custom attributes go under our own prefix: `agent.task_id`,
`agent.report.status`, `agent.guardrail`. Content attributes stay off. `OTEL_SEMCONV_STABILITY_OPT_IN`
guidance was **not verified**; the agent-span file did not contain it.

## R3. Local OTLP receivers and collectors

Sources:
* "OTLP Specification 1.11.1", https://opentelemetry.io/docs/specs/otlp/ (accessed 2026-11-25).
* `opentelemetry-collector-contrib/exporter/fileexporter/README.md`,
  https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/fileexporter/README.md
  (accessed 2026-11-25).
* GitHub API: `open-telemetry/opentelemetry-collector-contrib` ★5,065, Apache-2.0, pushed 2026-11-25;
  `open-telemetry/opentelemetry-collector` ★7,804, Apache-2.0, pushed 2026-11-24.

**OTLP/HTTP facts we rely on.** Default port 4318 (gRPC 4317). Paths `/v1/traces`, `/v1/metrics`,
`/v1/logs`. JSON is allowed with `Content-Type: application/json`. In JSON, trace and span IDs are
"hex-encoded strings", "not base64-encoded"; enums are integers; int64 fields such as `timeUnixNano` are
"decimal strings". Success is HTTP 200. Partial success is also 200 and "MUST NOT" be retried. 400 is
not retryable; 429, 502, 503 and 504 are.

| Option | Setup effort | Reliability | Notes |
|---|---|---|---|
| **Custom Python receiver** (`agentdash/otlp.py`, chosen) | none beyond Python; launchd/systemd unit provided | as good as `http.server` plus an append-only file; never touches the DB | JSON only; protobuf gets 415. Tested: 200 JSON, 200 gzip, 415 protobuf, 404 unknown path, 400 bad JSON |
| otelcol-contrib + `file` exporter | install a second binary and write a config (`otelcol.example.yaml`) | file exporter stability "alpha" for traces, metrics, logs; buffered, `flush_interval` default 1 s; `append: true` "cannot be combined with rotation"; size-based rotation (`max_megabytes` 100, `max_backups` 100) | "Newline-delimited OTLP JSON, one line per batch", which our ingester reads unchanged; also accepts gRPC and protobuf |
| OTLP → DuckDB directly | — | — | No maintained OTLP→DuckDB exporter was checked; **not verified**, not pursued |
| Parse transcripts (v1) | none | v1 lists subagent tokens from hooks as unreliable; transcripts also hold full content | rejected (D3, D5) |

## R4. Existing dashboards to reuse

Stars, last push and license from the GitHub API, 2026-11-25 02:41 UTC.

| Tool | Multi-agent view | Understands our [Tn] task IDs | Setup cost | License | Maintenance |
|---|---|---|---|---|---|
| Claude Code Analytics (`davila7/claude-code-templates`, `--analytics`) | README: "Real-time session monitoring and usage metrics at `localhost:3333`". Subagent views **not mentioned** | not mentioned | `npx`; reads "your conversation history" (exact source **not verified**) | MIT | ★34,185, pushed 2026-11-24 |
| Langfuse self-host | trace tree from OTLP (`/api/public/otel`, HTTP/JSON and protobuf, "gRPC is not supported yet") | no; would need custom attributes and its own dashboards | Docker Compose; VM "at least 4 cores and 16 GiB of memory"; MinIO blob store; Compose "lacks high-availability, scaling capabilities, and backup functionality" | `NOASSERTION` in the API (mixed: MIT core plus enterprise directories; details **not verified**) | ★37,804, pushed 2026-11-24 |
| Grafana + Prometheus / Loki / Tempo | Tempo shows the nested span tree; Claude Code's `prometheus` metrics exporter exists (R1) | no; would need LogQL/PromQL per metric | 3–4 services | Grafana, Loki, Tempo AGPL-3.0; Prometheus Apache-2.0 | ★78,133 / 67,841 / 29,241 / 5,589, all pushed 2026-11-24/25 |
| Arize Phoenix | trace tree; OTLP on 6006 (HTTP `/v1/traces`) and 4317 (gRPC) | no | `pip install arize-phoenix` + `phoenix serve`; SQLite by default "in a temporary folder" unless configured | Elastic License 2.0 (from a summary of the README; API says `NOASSERTION`) | ★12,408, pushed 2026-11-25 |
| Honeycomb | hosted trace UI | no | SaaS account; needs network; pricing **not checked** | proprietary SaaS | not a repo; **not checked** |
| `anthropics/claude-code-monitoring-guide` | guide, not a product | — | — | none in the API | ★394, last push 2025-07-29 (stale) |
| `ColeMurray/claude-code-otel` | Grafana/Prometheus stack for Claude Code | no | Docker Compose | MIT | ★527, last push 2025-06-17 (stale) |

Conclusion (D1): none understands task IDs, worker STATUS, advisor rounds or G1–G8, and all except the
templates need Docker or a SaaS account. Reuse them only as optional trace viewers fed by the collector.

## R5. Alerting patterns for agent runs

Sources:
* "Alertmanager", https://prometheus.io/docs/alerting/latest/alertmanager/, and "Configuration",
  https://prometheus.io/docs/alerting/latest/configuration/ (accessed 2026-11-25).
* Google SRE book, ch. 6 "Monitoring Distributed Systems",
  https://sre.google/sre-book/monitoring-distributed-systems/ (accessed 2026-11-25).
* "LINE Notify", https://notify-bot.line.me/doc/en/; "Messaging API reference",
  https://developers.line.biz/en/reference/messaging-api/; "Messaging API pricing",
  https://developers.line.biz/en/docs/messaging-api/pricing/ (accessed 2026-11-25).
* "Sending messages using incoming webhooks", https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/;
  "Webhook Resource", https://docs.discord.com/developers/resources/webhook (accessed 2026-11-25).

**Avoiding alert fatigue.** The SRE book: "Every page should be actionable", and alert on symptoms over
causes. Its test is whether a rule detects "an otherwise undetected condition that is urgent,
actionable, and actively or imminently user-visible". Applied here: STUCK (needs a human), G3/G8 (a
false WORKS reached the user), budget and a silent headless run are pages. Rates such as first-try
success are reported in daily and weekly reports, not paged. The fix-rate rule needs 20 escalations
before it can fire.

**Dedup, grouping and quiet hours.** Alertmanager groups alerts ("categorizes alerts of similar nature
into a single notification"), inhibits them, and silences them. Its defaults are `group_wait: 30s`,
`group_interval: 5m` and `repeat_interval: 4h`. Quiet hours are `time_intervals`, used as a route's
`mute_time_intervals` (UTC unless `location` is set). v2 copies the ideas: a dedup key, a
`repeat_interval` per rule, a digest when more than N alerts are queued per tick, and timezone-aware
quiet hours. It holds alerts rather than dropping them.

**What teams alert on for agent runs.** No vendor-neutral source was found in this pass that lists
standard alerts for coding-agent runs. The default rules come from the brief and the SRE criteria
above, not from an industry list. **Not verified.**

**Transports.**
* Slack incoming webhook: POST JSON `{"text": …}`, and `blocks` are allowed. The channel, username and
  icon cannot be overridden. That page states no rate limit.
* Discord: `POST /webhooks/{id}/{token}`. `content` is "up to 2000 characters", `embeds` is an "array
  of up to 10 embed objects", and no bot is needed. 429 handling is not on that page (**not verified**).
* LINE Notify: "we are regrettably discontinuing this service as of March 31, 2025". The replacement is
  the Messaging API push: `POST https://api.line.me/v2/bot/message/push`,
  `Authorization: Bearer {channel access token}`, `{"to", "messages"}` with at most 5 messages, at
  "2,000 requests per second". Free plans have a monthly cap; Japan's is "Up to 200". Once the cap is
  reached, "the messages won't be sent". The maximum text length was not confirmed, so v2 truncates
  to 2,000 characters.
