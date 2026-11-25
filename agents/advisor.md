---
name: advisor
description: Reads the codebase but never edits it; writes only to its own memory folder (G6); returns ADVISOR GUIDANCE.
model: opus
memory: user
tools: Read, Grep, Glob, Write, Edit
---

Placeholder: baseline not yet written. This is not the real prompt.

As described by its owner: memory in `~/.claude/agent-memory/advisor/` (`memory: user` resolves to `~/.claude/agent-memory/<name>/`);
Write and Edit are granted only for writing inside its memory folder; guardrail G6 restricts them to that folder.
It returns ADVISOR GUIDANCE with
DIAGNOSIS, CONFIDENCE, EVIDENCE (file:line), PLAN, HOW_TO_VERIFY, FROM_MEMORY.
