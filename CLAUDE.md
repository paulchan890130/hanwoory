# CLAUDE.md — Hanwory Immigration Management System

## Project identity
This is the internal immigration management system for Hanwory Administrative Office.

Current architecture:
- Frontend: Next.js app directory
- Backend: FastAPI
- Deployment: Render Docker
- Data: Google Sheets and Google Drive
- Public domain: https://www.hanwory.com

This is not a Streamlit project anymore.

## Absolute rules
- Do not refactor stable code unless explicitly requested.
- Do not change UI layout unless the task requires it.
- Prefer minimal localized patches.
- Never overwrite entire Google Sheets data.
- Persistence must be ID-based upsert.
- Deletion must require explicit confirmation.
- Do not auto-save user edits.
- Do not expose confidential handbook text on public pages.
- Do not mix public homepage routes with authenticated internal routes.

## Routing
- `/` = public homepage
- `/board` = public board
- `/board/[slug]` = public post detail
- `/login` = internal login
- Authenticated users continue using the internal system unchanged.

## Important docs
Read these only when relevant:
- `docs/AI_HANDOVER.md`
- `docs/ARCHITECTURE.md`
- `docs/DEV_COMMANDS.md`
- `docs/BUSINESS_RULES.md`
- `docs/KNOWN_BUGS.md`
- `docs/OCR_CONTEXT.md`
- `docs/HOMEPAGE_CONTEXT.md`

## Work style
Before editing:
1. Inspect relevant files.
2. Explain the root cause.
3. Propose a minimal patch plan.
4. Modify only necessary files.
5. Show changed files.
6. Provide verification commands.

## Never do
- Do not say "fixed" without showing changed files.
- Do not silently create a new architecture.
- Do not remove working logic.
- Do not convert this project back to Streamlit.
