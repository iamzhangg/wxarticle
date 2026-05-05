# Project Status

Last updated: 2026-05-05

## Current State

wxarticle v2 is an MVP content generation and formatting tool. The core flow is working:

- Track-based article generation.
- Hot topic search and AI topic selection.
- AI article writing through SiliconFlow.
- AI image generation, with stock image search kept as an optional mode.
- HTML formatting for rich text editor paste workflows.
- Web console for article browsing, preview, copying HTML, downloading covers, editing settings, and triggering generation.
- Daily scheduled generation through the app's internal scheduler.
- Initial Windows Server deployment through Python venv and Windows Scheduled Task.

Primary local entry:

```bash
python start_web.py
```

Default URL:

```text
http://127.0.0.1:8080
```

Validation command:

```bash
python src/main.py --dry-run --skip-search
```

## Current Configuration Snapshot

- Main branch: `master`
- Web host: `127.0.0.1`
- Web port: `8080`
- Enabled track: `AI赛道`
- Articles per day: `1`
- Image source: `ai`
- Inline image count: `2`
- Schedule time: `08:00`

Do not read or edit `.env` unless Gio explicitly asks for it.

## Product Shape

The project is organized around tracks. Each track owns its prompt, keywords, image style, enabled state, and daily article count. This keeps content direction separate from the generation pipeline.

The Web console is not just a viewer. It can generate content, change settings, delete articles, update code, and restart the service. Public access must be protected by authentication, Basic Auth, IP whitelist, or firewall rules.

## Important Files

```text
AGENTS.md                         Project working rules
README.md                         Public project introduction
TECH_STACK.md                     Technical overview and debt list
config.yaml                       Business configuration
start_web.py                      Web console entry
src/main.py                       Generation pipeline entry
src/web_app.py                    FastAPI backend and Web APIs
src/web/static/index.html         Single-file frontend SPA
src/article_generator.py          Article generation and self-check
src/formatter.py                  HTML formatting and preview generation
tracks/*/prompt.md                Track-specific writing constraints
docs/deployment.md                Deployment notes
docs/workflow.md                  Multi-conversation workflow
output/                           Generated article files
```

## Known Risks

- No formal Web authentication inside the app yet.
- `src/web_app.py` is too broad and mixes routing, system actions, scheduling, and generation process control.
- `src/formatter.py` is large and high risk because it directly affects rich text paste output.
- `src/web/static/index.html` is a large single-file frontend.
- Generation job state is mostly in memory plus `meta.json`; restarts and failures need better persistence.
- There is no test suite or lint setup.
- Public deployment is safe only when kept behind reverse proxy protection or firewall restrictions.

## Current Workstreams

Use separate Codex conversations for these workstreams:

- 陈序 / Project Control: roadmap, priority, cross-conversation handoff.
- 林蓝 / Product and PRD: feature definition, user flows, acceptance criteria.
- 周衡 / Architecture and Stability: refactors, task state, safety, tests, AI client abstraction.
- 沈修 / Feature Development and Bug Fixes: clear feature work, bug fixes, and small scoped improvements.
- 顾舟 / GitHub Release and Deployment: commits, release notes, deployment, server operations.
- 袁启 / Original MVP Archive: initial MVP history only, not new tasks.

## Handoff Rule

Every workstream should read this file first, then `docs/conversation_roles.md` and `docs/workflow.md`, then the files relevant to the assigned task.

At the end of each task, the conversation must output the handoff format from `docs/handoff_template.md`. The Project Control conversation should use that handoff to update this status file when needed.
