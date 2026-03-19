from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import AlertQueue, QuranProgressEntry, Rule, Task


# -------- RULES --------
async def list_rules(session: AsyncSession) -> list[Rule]:
    res = await session.execute(select(Rule).order_by(Rule.id.asc()))
    return list(res.scalars().all())


async def count_rules(session: AsyncSession) -> int:
    res = await session.execute(select(Rule))
    return len(list(res.scalars().all()))


async def insert_rules(session: AsyncSession, rules: list[Rule]) -> None:
    session.add_all(rules)
    await session.commit()


# -------- TASKS --------
async def add_task(session: AsyncSession, task: Task) -> Task:
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def create_task(
    session: AsyncSession,
    title: str,
    planned_at: datetime | None,
    duration_min: int,
    category: str = "personal",
    context_status: str = "normal",
) -> Task:
    task = Task(
        title=title,
        planned_at=planned_at,
        duration_min=duration_min,
        category=category,
        context_status=context_status,
        status="todo",
        created_at=now_tz(),
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)

    return task


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    stmt = select(Task).where(Task.id == task_id)
    res = await session.execute(stmt)
    return res.scalars().first()


async def update_task(
    session: AsyncSession,
    task_id: int,
    *,
    title: str,
    planned_at: datetime | None,
    duration_min: int,
    category: str,
    context_status: str,
) -> Task | None:
    task = await get_task(session, task_id)
    if task is None:
        return None

    task.title = title
    task.planned_at = planned_at
    task.duration_min = duration_min
    task.category = category
    task.context_status = context_status

    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task_id: int) -> bool:
    task = await get_task(session, task_id)
    if task is None:
        return False

    await session.delete(task)
    await session.commit()
    return True


async def list_tasks_for_day(
    session: AsyncSession,
    day_start: datetime,
    day_end: datetime,
) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.planned_at.is_not(None))
        .where(Task.planned_at >= day_start)
        .where(Task.planned_at < day_end)
        .order_by(Task.planned_at.asc())
    )

    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_floating_tasks(session: AsyncSession) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.planned_at.is_(None))
        .where(Task.status == "todo")
        .order_by(Task.id.asc())
    )

    res = await session.execute(stmt)
    return list(res.scalars().all())


# -------- ALERT QUEUE --------
ACTIVE_ALERT_STATUSES = ("pending", "active", "firing")
OPEN_ALERT_STATUSES = ACTIVE_ALERT_STATUSES


async def get_alert(session: AsyncSession, alert_id: int) -> AlertQueue | None:
    return await session.get(AlertQueue, alert_id)


async def list_active_alerts(session: AsyncSession) -> list[AlertQueue]:
    stmt = (
        select(AlertQueue)
        .where(AlertQueue.status.in_(ACTIVE_ALERT_STATUSES))
        .order_by(AlertQueue.priority.desc(), AlertQueue.scheduled_for.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_open_alerts(session: AsyncSession) -> list[AlertQueue]:
    stmt = (
        select(AlertQueue)
        .where(AlertQueue.status.in_(OPEN_ALERT_STATUSES))
        .order_by(AlertQueue.priority.desc(), AlertQueue.scheduled_for.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_active_alert_by_key(
    session: AsyncSession,
    *,
    alert_type: str,
    entity_type: str,
    entity_id: str,
) -> AlertQueue | None:
    stmt = (
        select(AlertQueue)
        .where(AlertQueue.alert_type == alert_type)
        .where(AlertQueue.entity_type == entity_type)
        .where(AlertQueue.entity_id == entity_id)
        .where(AlertQueue.status.in_(ACTIVE_ALERT_STATUSES))
        .order_by(AlertQueue.created_at.desc(), AlertQueue.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def get_latest_alert_by_entity(
    session: AsyncSession,
    *,
    alert_type: str,
    entity_type: str,
    entity_id: str,
) -> AlertQueue | None:
    stmt = (
        select(AlertQueue)
        .where(AlertQueue.alert_type == alert_type)
        .where(AlertQueue.entity_type == entity_type)
        .where(AlertQueue.entity_id == entity_id)
        .order_by(AlertQueue.created_at.desc(), AlertQueue.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def add_alert(session: AsyncSession, alert: AlertQueue) -> AlertQueue:
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def create_or_reuse_alert(
    session: AsyncSession,
    *,
    alert_type: str,
    entity_type: str,
    entity_id: str,
    scheduled_for: datetime,
    repeat_interval_min: int | None,
    priority: int,
    payload_json: str | None,
    status: str = "pending",
) -> AlertQueue:
    now = now_tz()

    existing = await get_active_alert_by_key(
        session,
        alert_type=alert_type,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    if existing is not None:
        existing.scheduled_for = scheduled_for
        existing.repeat_interval_min = repeat_interval_min
        existing.priority = priority
        existing.payload_json = payload_json
        existing.status = status
        existing.updated_at = now
        existing.completed_at = None
        await session.commit()
        await session.refresh(existing)
        return existing

    alert = AlertQueue(
        alert_type=alert_type,
        entity_type=entity_type,
        entity_id=entity_id,
        scheduled_for=scheduled_for,
        repeat_interval_min=repeat_interval_min,
        status=status,
        priority=priority,
        payload_json=payload_json,
        last_fired_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def update_alert_status(
    session: AsyncSession,
    *,
    alert_id: int,
    status: str,
    completed_at: datetime | None = None,
) -> AlertQueue | None:
    alert = await get_alert(session, alert_id)
    if alert is None:
        return None

    alert.status = status
    alert.updated_at = now_tz()
    if completed_at is not None:
        alert.completed_at = completed_at

    await session.commit()
    await session.refresh(alert)
    return alert


async def claim_alert_for_fire(
    session: AsyncSession,
    *,
    alert_id: int,
) -> AlertQueue | None:
    now = now_tz()

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status.in_(("pending", "active")))
        .values(
            status="firing",
            last_fired_at=now,
            updated_at=now,
        )
    )
    result = await session.execute(stmt)
    await session.commit()

    if result.rowcount != 1:
        return None

    return await get_alert(session, alert_id)


async def complete_alert_if_open(
    session: AsyncSession,
    *,
    alert_id: int,
) -> bool:
    now = now_tz()

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status.in_(OPEN_ALERT_STATUSES))
        .values(
            status="done",
            completed_at=now,
            updated_at=now,
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def cancel_alert_if_open(
    session: AsyncSession,
    *,
    alert_id: int,
    payload_json: str | None = None,
) -> bool:
    now = now_tz()

    values: dict = {
        "status": "cancelled",
        "completed_at": now,
        "updated_at": now,
    }
    if payload_json is not None:
        values["payload_json"] = payload_json

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status.in_(OPEN_ALERT_STATUSES))
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def fail_alert_if_open(
    session: AsyncSession,
    *,
    alert_id: int,
    payload_json: str | None = None,
) -> bool:
    now = now_tz()

    values: dict = {
        "status": "failed",
        "updated_at": now,
    }
    if payload_json is not None:
        values["payload_json"] = payload_json

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status.in_(OPEN_ALERT_STATUSES))
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def reschedule_firing_alert(
    session: AsyncSession,
    *,
    alert_id: int,
    scheduled_for: datetime,
    payload_json: str | None = None,
    repeat_interval_min: int | None = None,
    priority: int | None = None,
) -> bool:
    now = now_tz()

    values: dict = {
        "status": "pending",
        "scheduled_for": scheduled_for,
        "updated_at": now,
        "completed_at": None,
    }
    if payload_json is not None:
        values["payload_json"] = payload_json
    if repeat_interval_min is not None:
        values["repeat_interval_min"] = repeat_interval_min
    if priority is not None:
        values["priority"] = priority

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status == "firing")
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def activate_firing_alert(
    session: AsyncSession,
    *,
    alert_id: int,
    payload_json: str | None = None,
) -> bool:
    now = now_tz()

    values: dict = {
        "status": "active",
        "updated_at": now,
        "completed_at": None,
    }
    if payload_json is not None:
        values["payload_json"] = payload_json

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status == "firing")
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def finalize_firing_alert(
    session: AsyncSession,
    *,
    alert_id: int,
    status: str,
    payload_json: str | None = None,
) -> bool:
    now = now_tz()

    values: dict = {
        "status": status,
        "updated_at": now,
    }
    if status in ("done", "cancelled", "failed"):
        values["completed_at"] = now
    if payload_json is not None:
        values["payload_json"] = payload_json

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status == "firing")
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


async def reset_alert_to_pending_for_recovery(
    session: AsyncSession,
    *,
    alert_id: int,
    scheduled_for: datetime,
) -> bool:
    now = now_tz()

    stmt = (
        update(AlertQueue)
        .where(AlertQueue.id == alert_id)
        .where(AlertQueue.status.in_(OPEN_ALERT_STATUSES))
        .values(
            status="pending",
            scheduled_for=scheduled_for,
            updated_at=now,
            completed_at=None,
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount == 1


# -------- QURAN PROGRESS --------
async def add_quran_progress(
    session: AsyncSession,
    *,
    surah: str,
    ayah: int,
    page: int,
) -> QuranProgressEntry:
    entry = QuranProgressEntry(
        surah=surah,
        ayah=ayah,
        page=page,
        created_at=now_tz(),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def get_latest_quran_progress(
    session: AsyncSession,
) -> QuranProgressEntry | None:
    stmt = (
        select(QuranProgressEntry)
        .order_by(QuranProgressEntry.created_at.desc(), QuranProgressEntry.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def get_latest_quran_progress_before(
    session: AsyncSession,
    *,
    before_dt: datetime,
) -> QuranProgressEntry | None:
    stmt = (
        select(QuranProgressEntry)
        .where(QuranProgressEntry.created_at < before_dt)
        .order_by(QuranProgressEntry.created_at.desc(), QuranProgressEntry.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def get_latest_quran_progress_for_day(
    session: AsyncSession,
    *,
    day_start: datetime,
    day_end: datetime,
) -> QuranProgressEntry | None:
    stmt = (
        select(QuranProgressEntry)
        .where(QuranProgressEntry.created_at >= day_start)
        .where(QuranProgressEntry.created_at < day_end)
        .order_by(QuranProgressEntry.created_at.desc(), QuranProgressEntry.id.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def list_quran_progress_for_day(
    session: AsyncSession,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[QuranProgressEntry]:
    stmt = (
        select(QuranProgressEntry)
        .where(QuranProgressEntry.created_at >= day_start)
        .where(QuranProgressEntry.created_at < day_end)
        .order_by(QuranProgressEntry.created_at.asc(), QuranProgressEntry.id.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())
