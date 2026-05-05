# Roadmap

Last updated: 2026-05-05

## P1: Stabilize and Protect

### Web Console Authentication

Goal: protect all write-capable Web console operations before broader public use.

Scope:

- Add simple login or API token protection.
- Protect `POST /api/generate`.
- Protect `PUT /api/settings`.
- Protect `POST /api/update`.
- Protect `POST /api/restart`.
- Protect `DELETE /api/articles/...`.
- Document public deployment safety rules.

### Generation Job Stability

Goal: make generation status easier to track, debug, and recover.

Scope:

- Introduce a `job_id`.
- Persist job status beyond in-memory state.
- Show failure reason and log entry in the Web console.
- Keep generated output directory state consistent.
- Consider SQLite for job records.

### Deployment Safety Documentation

Goal: make local, server, and public deployment boundaries clear.

Scope:

- Keep default `127.0.0.1`.
- Document reverse proxy protection.
- Add Basic Auth or IP whitelist examples.
- Add Windows Scheduled Task troubleshooting.
- Add backup and restore notes for `.env` and `output/`.

### Repository Cleanup

Goal: reduce root directory noise without losing useful deployment history.

Scope:

- Identify temporary scripts, logs, screenshots, and zip files.
- Move useful scripts into `scripts/`.
- Move useful images into `docs/assets/`.
- Delete only after Gio explicitly confirms.

## P2: Refactor for Maintainability

### Split `src/web_app.py`

Target structure:

```text
src/web/
├── app.py
├── routes/
│   ├── articles.py
│   ├── generation.py
│   ├── settings.py
│   └── system.py
├── services/
│   ├── article_store.py
│   ├── generation_runner.py
│   └── scheduler.py
└── security.py
```

### Split `src/formatter.py`

Target structure:

```text
src/formatting/
├── markdown_parser.py
├── html_renderer.py
├── image_placement.py
├── style_inliner.py
└── preview_page.py
```

Rules:

- Preserve current paste behavior.
- Verify with generated article previews.
- Keep changes small and reversible.

### Abstract AI Client

Goal: centralize provider calls and error behavior.

Target structure:

```text
src/ai/
├── client.py
├── text_generation.py
├── image_generation.py
└── prompt_templates.py
```

Benefits:

- Shared timeout and retry behavior.
- Clear logs.
- Easier model/provider changes.
- Better cost and failure tracking later.

### Frontend Modularization

Short-term target:

```text
src/web/static/
├── index.html
├── styles.css
├── api.js
├── state.js
└── app.js
```

Do not migrate to a frontend framework until the current feature set clearly needs it.

### Basic Tests

First useful coverage:

- Config loading.
- Output path safety.
- Formatter basic conversion.
- Inline image insertion.
- Dry-run generation flow.
- Web API smoke tests.

## P3: Product and Operations Expansion

### Content Workflow

Possible later features:

- Draft status.
- Manual review.
- Article rating.
- Rewrite/regenerate variants.
- Version history.
- Publish records.

### Standard Deployment Options

Possible later docs and scripts:

- Docker Compose.
- Linux systemd.
- Nginx Basic Auth.
- HTTPS setup.
- Backup and migration guide.

### Multi-user and Permissions

Long-term direction:

- User login.
- Role permissions.
- Project isolation.
- Operation audit log.

### Data Layer Upgrade

Long-term direction:

- SQLite for article index and job records.
- File system still stores images and HTML.
- Better search, filtering, tags, and archive state.

## Priority Rule

When there is conflict, prefer work that protects generated data, prevents public exposure, improves failure visibility, or reduces the risk of breaking article output.

