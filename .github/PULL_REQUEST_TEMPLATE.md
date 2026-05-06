<!-- Thanks for the PR! Keep this short. -->

## What changed
<!-- One-line summary, then bullets if needed. -->

## Why
<!-- The motivation. Link an issue if there is one: Fixes #123 / Closes #123 -->

## How
<!-- Anything tricky a reviewer should know — schema changes, new env vars, breaking behaviour. -->

## Checklist
- [ ] Touched only one concern (or this PR is small enough that combining is fine)
- [ ] If schema changed → added an Alembic revision under `alembic/versions/`
- [ ] If a new env var is needed → added to `.env.example` with a comment
- [ ] `ruff check packages/` passes
- [ ] Manually verified via `docs/E2E.md` if the change touches the runtime path
