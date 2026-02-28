"""Audit logging helpers."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from monitor_bot.db_models import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    actor_user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        ),
    )
    await db.commit()
