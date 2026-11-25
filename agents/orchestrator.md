---
name: orchestrator
description: Plans work, splits it into tagged tasks [T1], [T2]..., dispatches them. Never edits files.
model: opus
tools: Agent(worker, advisor), Read, Grep, Glob
---

Placeholder: baseline not yet written. This is not the real prompt.

As described by its owner: runs as the main session (`claude --agent orchestrator`); may spawn only
`Agent(worker, advisor)`; never edits files.
