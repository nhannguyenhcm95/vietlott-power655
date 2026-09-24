# Vietlott Power 6/55 research — session guide

Before any task, read `AI-agent.md` (the multi-agent operating model), `agent.md` (scope and rules) and `docs/TASKBOARD.md` (current tasks).

- The main session is the **Project Lead**. It classifies each task, delegates it to the project agents in `.claude/agents/`, keeps `docs/TASKBOARD.md` current, and asks the human to approve CRITICAL items.
- Effort policy (AI-agent.md §27): only `medium` and `high` are allowed. Use the project agents, whose effort is set in their frontmatter. Do not use generic agents for role work, because their effort cannot be controlled.
- The implementer never approves its own work. Reviews go to data-qa, qa-runner or methodology-auditor.
- Out of scope: betting advice, number selection, betting optimisation and ticket purchasing.
- Tests: `python -m pytest`. On Windows, set `PYTHONIOENCODING=utf-8` before running CLI commands in Git Bash.
