# Probe: real hook input shapes (observed 2026-11-25, Claude Code 2.1.241)

Method: scratch project in a temp dir with a project-local `PreToolUse` (matcher `*`) and `SubagentStop`
hook that appended raw stdin to a log; the repo's `agents/orchestrator.md` and `worker.md` copied to the
scratch `.claude/agents/`; run as `AGENT_WORKFLOW=1 claude --agent orchestrator -p "<dispatch worker to create hello.txt>" --permission-mode acceptEdits`.
Nothing in `~/.claude` or this repo's settings was changed. Payloads (sanitised paths) are in `real/`.

## Answers (all observed)

(a) **Main thread under `claude --agent orchestrator`:** `agent_type` is `"orchestrator"` and `agent_id` is ABSENT.
    Spec assumption "no agent_id = main thread" holds; `agent_type == "orchestrator"` also works. Detect the
    Orchestrator as `agent_type == "orchestrator"` OR `agent_id` absent.
(b) **`Agent` PreToolUse:** `tool_name: "Agent"`, `tool_input` keys `description`, `prompt`, `run_in_background`,
    `subagent_type`. The prompt text holds the `DONE_WHEN:` / `DONE_WHEN_FILES:` lines as written by the Orchestrator.
    The dispatch event has `agent_type: "orchestrator"`, no `agent_id`. Observed `subagent_type` value: `"worker"`.
(c) **Worker PreToolUse:** `agent_id` present, `agent_type: "worker"` (exact string). `session_id` is IDENTICAL to the
    Orchestrator's, so G8 state is keyed by `session_id` (no git-root fallback needed). Write input: `tool_input.file_path`,
    `content`. Bash input: `tool_input.command`, `description`.
(d) **SubagentStop:** keys `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, `stop_hook_active`
    (false on first stop), `session_id`, `cwd`, `transcript_path`. The final message is in `last_assistant_message` and
    contains free text BEFORE the `=== WORKER REPORT ===` block, so G1 must search for the markers inside the message,
    not require them at the start.
(e) **Hook exit code 1 does NOT block:** with a `PreToolUse` hook exiting 1, the Bash call `touch exit1.txt` still ran
    (file created). Blocking hooks must exit 2.
(f) Dispatch prompt format seen: lines `DONE_WHEN: \`test -f hello.txt\` ...` (value wrapped in backticks, with trailing prose) and
    `DONE_WHEN_FILES: hello.txt`. The parser must strip backticks and trailing punctuation.

## Spec deltas

- Role detection: `orchestrator` if `agent_type == "orchestrator"` or `agent_id` absent (spec §5 said only the latter).
- G8 state key: `session_id` only (spec §9 fallback not needed).
- G1: locate the report block anywhere in `last_assistant_message`; `agent_transcript_path` is a fallback only.
- `DONE_WHEN` parsing strips surrounding backticks.
