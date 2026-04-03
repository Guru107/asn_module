---
name: handoff
description: Write a session handoff document for future agents or sessions. Use when the user asks to summarize the current session into `docs/agents/handoff/`, continue work across sessions, or create a durable status note that captures accomplishments, decisions, branch state, and pickup context.
---

# Handoff

Write a durable handoff document in `docs/agents/handoff/` that a fresh agent can use without re-discovering the session.

## Workflow

1. Determine today's date.
Use the `current_date` or equivalent session date context if available. Do not browse for the date.

2. Inspect existing handoff files.
List files under `docs/agents/handoff/`. For the current date, find the highest `NNN` already used in filenames matching `YYYY-MM-DD-NNN-<slug>.md`. Increment by one. Start at `001` if none exist for that date.

3. Derive the topic slug.
Use the current session name if available. Otherwise derive a short kebab-case slug from the main subject of the session. Keep it specific and short.

4. Propose the filename and stop for confirmation.
Propose:
`docs/agents/handoff/YYYY-MM-DD-NNN-<slug>.md`

Ask exactly:
`Proposed filename: <path> — is that correct? If not, provide the filename to use instead.`

Do not write the file until the user confirms or provides a corrected filename.

5. Write the handoff document to the confirmed path.
Match the style and depth of existing handoff docs in `docs/agents/handoff/`. If none exist, keep the document concise, structured, and operational.

## Required Content

Include these sections:

- `What was accomplished`
- `Key decisions`
- `Important context for future sessions`

Populate them with concrete details:

- deliverables completed
- files created or changed
- commands run when they matter for verification or reproducibility
- architectural choices and trade-offs
- ideas explicitly rejected and why
- branch status
- open work, blockers, or known residual risks
- locations of relevant docs, plans, specs, tests, or PRs

## Style

- Write for a fresh agent picking up the work later.
- Prefer concrete facts over narrative.
- Keep it compact but sufficient to continue work safely.
- Do not include fluff, process commentary, or generic advice.
- Do not invent state. If something is uncertain, say so explicitly.

## Guardrails

- Never overwrite an existing handoff file without explicit user approval.
- If `docs/agents/handoff/` does not exist, create it only after the user confirms the proposed filename.
- Keep the filename date and sequence consistent with existing files for that same day.
