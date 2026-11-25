---
name: advisor
description: Reads the codebase, cannot edit it; keeps persistent memory; returns ADVISOR GUIDANCE.
model: opus
memory: user
tools: Read, Grep, Glob, Write, Edit
---

Placeholder: baseline not yet written. This is not the real prompt.

As described by its owner: memory in `~/.claude/agent-memory/advisor/` (`memory: user` resolves to `~/.claude/agent-memory/<name>/`);
Write and Edit are granted only for that memory folder; guardrail G6 restricts them to it.
It returns ADVISOR GUIDANCE with
DIAGNOSIS, CONFIDENCE, EVIDENCE (file:line), PLAN, HOW_TO_VERIFY, FROM_MEMORY.
