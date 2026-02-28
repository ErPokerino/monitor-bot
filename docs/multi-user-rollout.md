# Multi-User Rollout and Smoke Test Plan

## Backend Validation Checklist
- [ ] `uv run pytest tests/test_multi_user_services.py`
- [ ] `uv run ruff check src/monitor_bot`
- [ ] `uv run python -c "import monitor_bot.app"`
- [ ] `uv run python -c "import asyncio, monitor_bot.app; from monitor_bot.database import init_db; asyncio.run(init_db())"`

## Frontend Validation Checklist
- [ ] `npm run build` in `frontend/`
- [ ] Login as admin: verify navbar role badge (`ADMIN`) and visibility of `Admin` page link
- [ ] Open `Admin` page and create a regular user
- [ ] Login as regular user: verify `Admin` page is not accessible and role badge shows `USER`
- [ ] Verify regular user can create/update only own sources/queries/settings
- [ ] Verify shared agenda badge increments after an item is shared to the user
- [ ] Verify `Shared with me` tab shows shared item and marks it as seen
- [ ] Verify chatbot greeting and responses include user-specific context
- [ ] Verify voice mode authenticates via first WebSocket auth message (no token in URL)

## Staged Rollout Sequence
1. Deploy backend with schema changes and RBAC/session support.
2. Run startup migration and admin bootstrap checks in a staging environment.
3. Validate admin user management and per-user data isolation with two test accounts.
4. Enable sharing features and confirm badge + shared tab UX behavior.
5. Deploy frontend with role-aware navigation and admin UI.
6. Monitor auth/session failures, 401/403 rates, and sharing API usage for at least one release cycle.
7. Promote to production after verification sign-off.
